"""把本机 Chrome 会话 cookies 合并回 ~/auth.json。

Step1 浏览器任务（Playwright MCP Extension 连本机 Chrome 真实 profile）每天 9:10 跑，
登录态是活的；但 Step2 纯 requests 任务读的是 ~/auth.json 快照，2-3 天过期就要扫码。
本脚本在 Step1 结束后把 Chrome context 的 cookies（含 httpOnly）合并回 auth.json，
按 domain+name 为键、新覆盖旧——语义与 taobao_login.py 的 merge_auth_state 一致。

日志只打印数量和域名，绝不打印 cookie 值。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from chrome_mcp_bridge import PlaywrightMCPClient, load_env

AUTH_FILE = Path.home() / "auth.json"

# page.context() 是方法（extension 模式下 page.context 是 function）。
# storageState() 返回与 auth.json 相同的 Playwright storage state 格式，
# 且包含 httpOnly cookies（document.cookie 拿不到的）。
COOKIE_EXPORT_CODE = "async (page) => page.context().storageState()"


def parse_state(text: str) -> dict:
    """MCP tool 输出是 markdown 分段：`### Result` 后跟 JSON，之后是 `### Ran Playwright code` 等。"""
    text = text.strip()
    if text.startswith("### Error"):
        raise ValueError(text.splitlines()[0])
    segment = text
    marker = text.find("### Result")
    if marker != -1:
        segment = text[marker + len("### Result"):]
        # Result 段到下一个 ### 段（Ran Playwright code / Page）为止
        next_section = segment.find("\n###")
        if next_section != -1:
            segment = segment[:next_section]
    try:
        value = json.loads(segment)
    except json.JSONDecodeError:
        start, end = segment.find("{"), segment.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("cannot locate storage state JSON in MCP output")
        value = json.loads(segment[start : end + 1])
    if not isinstance(value, dict) or not isinstance(value.get("cookies"), list):
        raise ValueError(f"unexpected storage state payload: {type(value).__name__}")
    return value


def merge_state(base: dict, new_state: dict) -> dict:
    """cookies 和 origins 都按唯一键合并，新的覆盖旧的（与 taobao_login.merge_auth_state 一致）。"""
    cookie_map = {f"{c.get('domain')}:{c.get('name')}": c for c in base.get("cookies", [])}
    for cookie in new_state.get("cookies", []):
        cookie_map[f"{cookie.get('domain')}:{cookie.get('name')}"] = cookie
    origin_map = {o.get("origin"): o for o in base.get("origins", [])}
    for origin in new_state.get("origins", []):
        origin_map[origin.get("origin")] = origin
    return {"cookies": list(cookie_map.values()), "origins": list(origin_map.values())}


def atomic_write_json(path: Path, value: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f"{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main() -> int:
    load_env()
    client = PlaywrightMCPClient(timeout=60, client_name="dunhill-auth-sync")
    try:
        client.start()
        output = client.run_code(COOKIE_EXPORT_CODE, timeout=60)
    finally:
        client.close()

    try:
        new_state = parse_state(output)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"[WARN] storage state 解析失败，跳过 auth.json 同步: {exc}")
        return 1
    cookies = new_state.get("cookies", [])
    if not cookies:
        print("[WARN] Chrome context 无 cookies，跳过 auth.json 同步")
        return 1

    try:
        existing = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        existing = {"cookies": [], "origins": []}

    merged = merge_state(existing, new_state)
    atomic_write_json(AUTH_FILE, merged)
    domains = sorted({c["domain"] for c in cookies})
    print(f"[OK] auth.json 已同步: 合并 {len(cookies)} 条 Chrome cookies（域: {', '.join(domains)}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
