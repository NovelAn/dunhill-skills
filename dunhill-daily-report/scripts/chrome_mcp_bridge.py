"""
Bridge for running fast Playwright actions in the user's local Chrome session.

The bridge connects to the user's local Chrome profile through Playwright MCP
Extension, so it can reuse logged-in sessions without launching a fresh
Playwright profile.
"""

from __future__ import annotations

import json
import os
import queue
import re
import select
import shlex
import signal
import shutil
import subprocess
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any


class MCPError(RuntimeError):
    pass


PLAYWRIGHT_EXTENSION_NAME = "Playwright Extension"
PLAYWRIGHT_EXTENSION_STATUS_PAGE = "status.html"
ENV_CANDIDATES = [
    Path(__file__).resolve().parents[1] / ".env",
    Path.home() / ".claude" / "skills" / ".env",
    Path.home() / ".claude" / "skills" / "dunhill-skills" / ".env",
]
PRIMARY_ENV_PATH = ENV_CANDIDATES[0]
NODE_VERSION_RE = re.compile(r"v(\d+)(?:\.(\d+))?(?:\.(\d+))?")


def load_env() -> None:
    for env_file in ENV_CANDIDATES:
        if not env_file.exists():
            continue
        with open(env_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value


def _parse_node_major(version_text: str) -> int | None:
    match = NODE_VERSION_RE.search(version_text.strip())
    if not match:
        return None
    return int(match.group(1))


def _node_major_version(node_path: str) -> int | None:
    try:
        result = subprocess.run(
            [node_path, "-v"],
            text=True,
            capture_output=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return _parse_node_major(result.stdout)


def resolve_node_binary(min_major: int = 18) -> str | None:
    candidates: list[str] = []
    seen: set[str] = set()

    def add(path: str | None) -> None:
        if not path:
            return
        path = os.path.realpath(path)
        if path in seen:
            return
        seen.add(path)
        candidates.append(path)

    add(shutil.which("node"))
    add("/Applications/Codex.app/Contents/Resources/node")
    add("/opt/homebrew/bin/node")
    add("/usr/local/bin/node")
    add("/usr/bin/node")

    nvm_nodes = list((Path.home() / ".nvm" / "versions" / "node").glob("v*/bin/node"))

    def nvm_priority(path: Path) -> tuple[int, int]:
        major = _parse_node_major(path.parents[1].name) or 0
        preferred_order = {20: 4, 22: 3, 24: 2, 18: 1}
        return preferred_order.get(major, 0), major

    for nvm_node in sorted(nvm_nodes, key=nvm_priority, reverse=True):
        add(str(nvm_node))

    for candidate in candidates:
        major = _node_major_version(candidate)
        if major is not None and major >= min_major:
            return candidate
    return None


def resolve_playwright_mcp_command() -> list[str]:
    override = os.environ.get("PLAYWRIGHT_MCP_COMMAND")
    if override:
        return shlex.split(override)

    package_root_candidates = []
    explicit_package = os.environ.get("PLAYWRIGHT_MCP_PACKAGE_DIR")
    if explicit_package:
        package_root_candidates.append(Path(explicit_package).expanduser())

    home = Path.home()
    package_root_candidates.extend(
        sorted(
            home.glob(".npm/_npx/*/node_modules/@playwright/mcp"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    )
    package_root_candidates.extend(
        [
            Path.cwd() / "node_modules" / "@playwright" / "mcp",
            PRIMARY_ENV_PATH.parent / "node_modules" / "@playwright" / "mcp",
        ]
    )

    seen_roots: set[str] = set()
    for package_root in package_root_candidates:
        package_root = package_root.expanduser()
        cli_path = package_root / "cli.js"
        if not cli_path.exists():
            continue
        root_key = os.path.realpath(str(package_root))
        if root_key in seen_roots:
            continue
        seen_roots.add(root_key)
        node_path = resolve_node_binary(min_major=18)
        if node_path:
            return [node_path, str(cli_path)]

    npx_path = shutil.which("npx")
    if npx_path:
        return [npx_path, "-y", "@playwright/mcp@latest"]

    raise MCPError(
        "Unable to locate Playwright MCP runtime. "
        "Install/cache @playwright/mcp locally or set PLAYWRIGHT_MCP_COMMAND."
    )


def upsert_env_value(path: Path, key: str, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    replacement = f'{key}="{value}"'
    replaced = False
    updated_lines = []
    for line in lines:
        if pattern.match(line):
            updated_lines.append(replacement)
            replaced = True
        else:
            updated_lines.append(line)
    if not replaced:
        updated_lines.append(replacement)
    path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")


def find_playwright_extension_id() -> str | None:
    chrome_root = Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
    if not chrome_root.exists():
        return None

    for manifest_path in chrome_root.glob("*/Extensions/*/*/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if manifest.get("name") == PLAYWRIGHT_EXTENSION_NAME:
            return manifest_path.parent.parent.name
    return None


def playwright_extension_status_url() -> str | None:
    extension_id = find_playwright_extension_id()
    if not extension_id:
        return None
    return f"chrome-extension://{extension_id}/{PLAYWRIGHT_EXTENSION_STATUS_PAGE}"


def ensure_chrome_running(timeout: float = 15) -> bool:
    """Start normal Google Chrome when needed and wait until AppleScript can reach it."""

    check_command = ["osascript", "-e", 'application "Google Chrome" is running']
    try:
        check = subprocess.run(
            check_command,
            text=True,
            capture_output=True,
            timeout=3,
            check=False,
        )
        if check.returncode == 0 and check.stdout.strip().lower() == "true":
            return True

        launch = subprocess.run(
            ["osascript", "-e", 'tell application "Google Chrome" to activate'],
            text=True,
            capture_output=True,
            timeout=8,
            check=False,
        )
        if launch.returncode != 0:
            return False

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            check = subprocess.run(
                check_command,
                text=True,
                capture_output=True,
                timeout=3,
                check=False,
            )
            if check.returncode == 0 and check.stdout.strip().lower() == "true":
                return True
            time.sleep(0.5)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return False


def ensure_playwright_extension_status_page() -> bool:
    """Open or focus the Playwright Extension status page to wake the extension."""

    if not ensure_chrome_running():
        return False
    status_url = playwright_extension_status_url()
    if not status_url:
        return False

    script = f'''
tell application "Google Chrome"
  if not running then
    activate
    delay 0.2
  end if
  repeat with w in windows
    set tabIndex to 0
    repeat with t in tabs of w
      set tabIndex to tabIndex + 1
      if URL of t is "{status_url}" then
        set active tab index of w to tabIndex
        set index of w to 1
        activate
        return "focused"
      end if
    end repeat
  end repeat
  if (count of windows) is 0 then
    make new window
  end if
  tell front window
    make new tab with properties {{URL:"{status_url}"}}
    set active tab index to (count of tabs)
  end tell
  activate
  return "opened"
end tell
'''
    try:
        result = subprocess.run(
            ["osascript"],
            input=script,
            text=True,
            capture_output=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def read_playwright_extension_token_from_chrome() -> str | None:
    """Read the Playwright Extension token from an open Chrome confirmation page."""

    if os.environ.get("SKIP_CHROME_EXTENSION_TOKEN_DISCOVERY"):
        return None

    script = r'''
tell application "Google Chrome"
  repeat with w in windows
    set tabIndex to 0
    repeat with t in tabs of w
      set tabIndex to tabIndex + 1
      set u to URL of t
      if u starts with "chrome-extension://" and (u contains "/connect.html" or u contains "/status.html") then
        set active tab index of w to tabIndex
        set index of w to 1
        activate
        delay 0.2
        tell application "System Events"
          keystroke "a" using command down
          delay 0.1
          keystroke "c" using command down
          delay 0.1
        end tell
        return the clipboard
      end if
    end repeat
  end repeat
end tell
return ""
'''
    try:
        old_clipboard = subprocess.run(
            ["pbpaste"],
            text=True,
            capture_output=True,
            timeout=2,
            check=False,
        ).stdout
        result = subprocess.run(
            ["osascript", "-e", script],
            text=True,
            capture_output=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    finally:
        if "old_clipboard" in locals():
            try:
                subprocess.run(
                    ["pbcopy"],
                    input=old_clipboard,
                    text=True,
                    timeout=2,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass

    if result.returncode != 0:
        return None

    match = re.search(
        r"PLAYWRIGHT_MCP_EXTENSION_TOKEN\s*=\s*([A-Za-z0-9_-]{20,})",
        result.stdout,
    )
    if not match:
        return None
    return match.group(1)


def refresh_playwright_extension_token(
    force: bool = False,
    timeout: float = 10,
    persist: bool = False,
    env_path: Path | None = None,
) -> str | None:
    """Read the latest token from the extension status page and overwrite stale env values."""

    if not force and os.environ.get("PLAYWRIGHT_MCP_EXTENSION_TOKEN"):
        return os.environ["PLAYWRIGHT_MCP_EXTENSION_TOKEN"]

    ensure_playwright_extension_status_page()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        token = read_playwright_extension_token_from_chrome()
        if token:
            os.environ["PLAYWRIGHT_MCP_EXTENSION_TOKEN"] = token
            if persist:
                upsert_env_value(env_path or PRIMARY_ENV_PATH, "PLAYWRIGHT_MCP_EXTENSION_TOKEN", token)
            return token
        time.sleep(0.5)
    return os.environ.get("PLAYWRIGHT_MCP_EXTENSION_TOKEN") or None


def bootstrap_playwright_extension_token(timeout: float = 10, env_path: Path | None = None) -> str | None:
    """Refresh the daily Playwright Extension token once and persist it for child sessions."""

    load_env()
    return refresh_playwright_extension_token(
        force=True,
        timeout=timeout,
        persist=True,
        env_path=env_path or PRIMARY_ENV_PATH,
    )


def authorize_playwright_extension_connect_pages(
    client_name: str,
    token: str,
    duration: float = 20,
) -> None:
    """Append the extension token to matching connect.html pages opened by MCP."""

    encoded_token = urllib.parse.quote(token, safe="")
    deadline = time.monotonic() + duration
    script = f'''
tell application "Google Chrome"
  repeat with w in windows
    repeat with t in tabs of w
      set u to URL of t
      if u starts with "chrome-extension://" and u contains "/connect.html" and u contains "{client_name}" and u does not contain "token=" then
        if u contains "?" then
          set URL of t to u & "&token={encoded_token}"
        else
          set URL of t to u & "?token={encoded_token}"
        end if
      end if
    end repeat
  end repeat
end tell
'''
    while time.monotonic() < deadline:
        try:
            subprocess.run(
                ["osascript"],
                input=script,
                text=True,
                capture_output=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
        time.sleep(0.5)


def discover_and_authorize_playwright_extension(client_name: str, duration: float = 25) -> None:
    deadline = time.monotonic() + duration
    token = os.environ.get("PLAYWRIGHT_MCP_EXTENSION_TOKEN")
    while time.monotonic() < deadline:
        if not token:
            token = read_playwright_extension_token_from_chrome()
            if token:
                os.environ["PLAYWRIGHT_MCP_EXTENSION_TOKEN"] = token
        if token:
            authorize_playwright_extension_connect_pages(client_name, token, duration=0.6)
        time.sleep(0.5)


class PlaywrightMCPClient:
    """Minimal stdio MCP client for @playwright/mcp --extension."""

    def __init__(self, timeout: int = 240, client_name: str = "dunhill-chrome-bridge") -> None:
        self.timeout = timeout
        self.client_name = client_name
        self.proc: subprocess.Popen[str] | None = None
        self.next_id = 1
        self.stderr_queue: queue.Queue[str] = queue.Queue()

    def start(self) -> None:
        latest_token = os.environ.get("PLAYWRIGHT_MCP_EXTENSION_TOKEN")
        if not latest_token:
            latest_token = refresh_playwright_extension_token(force=True, persist=True)
        env = os.environ.copy()
        env["PLAYWRIGHT_MCP_EXTENSION"] = "1"
        env.setdefault("PLAYWRIGHT_MCP_BROWSER", "chrome")
        if latest_token:
            env["PLAYWRIGHT_MCP_EXTENSION_TOKEN"] = latest_token

        cmd = resolve_playwright_mcp_command()
        cmd.extend(["--extension", "--browser", "chrome"])
        startup_timeout = int(os.environ.get("PLAYWRIGHT_MCP_START_TIMEOUT", "120"))

        print("[bridge] connecting to local Chrome via Playwright MCP Extension...")
        if not latest_token:
            print("[bridge][info] PLAYWRIGHT_MCP_EXTENSION_TOKEN is not set; trying to read it from the extension page.")
        else:
            print("[bridge] using Playwright Extension token from environment.")
        threading.Thread(
            target=discover_and_authorize_playwright_extension,
            args=(self.client_name,),
            daemon=True,
        ).start()

        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
            start_new_session=True,
        )

        assert self.proc.stderr is not None
        threading.Thread(target=self._read_stderr, args=(self.proc.stderr,), daemon=True).start()

        self._request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": self.client_name, "version": "1.0.0"},
            },
            timeout=startup_timeout,
        )
        self._notify("notifications/initialized", {})

    def close(self) -> None:
        if not self.proc:
            return
        if self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except (OSError, ProcessLookupError):
                self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    self.proc.kill()
        self.proc = None

    def run_code(self, code: str, timeout: int | None = None) -> str:
        result = self.call_tool("browser_run_code_unsafe", {"code": code}, timeout=timeout)
        return tool_text(result) or json.dumps(result, ensure_ascii=False, indent=2)

    def call_tool(self, name: str, arguments: dict[str, Any], timeout: int | None = None) -> dict[str, Any]:
        return self._request(
            "tools/call",
            {"name": name, "arguments": arguments},
            timeout=timeout or self.timeout,
        )

    def _read_stderr(self, stderr: Any) -> None:
        for line in stderr:
            line = line.strip()
            if line:
                self.stderr_queue.put(line)

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def _request(self, method: str, params: dict[str, Any], timeout: int) -> dict[str, Any]:
        request_id = self.next_id
        self.next_id += 1
        self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        return self._read_response(request_id, timeout)

    def _write(self, payload: dict[str, Any]) -> None:
        if not self.proc or not self.proc.stdin:
            raise MCPError("Playwright MCP server is not running")
        self.proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    def _read_response(self, request_id: int, timeout: int) -> dict[str, Any]:
        if not self.proc or not self.proc.stdout:
            raise MCPError("Playwright MCP server is not running")

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                stderr = self._drain_stderr()
                raise MCPError(f"Playwright MCP exited early. {stderr}")

            line = self._readline_with_timeout(max(0.2, min(1.0, deadline - time.monotonic())))
            if not line:
                continue

            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue

            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise MCPError(json.dumps(message["error"], ensure_ascii=False))
            return message.get("result", {})

        stderr = self._drain_stderr()
        raise MCPError(
            "Timed out waiting for Playwright MCP Extension. "
            "Confirm Chrome has the Playwright Extension installed and set "
            "PLAYWRIGHT_MCP_EXTENSION_TOKEN when possible."
            + (f"\nMCP stderr: {stderr}" if stderr else "")
        )

    def _readline_with_timeout(self, timeout: float) -> str | None:
        assert self.proc and self.proc.stdout
        ready, _, _ = select.select([self.proc.stdout], [], [], timeout)
        if not ready:
            return None
        return self.proc.stdout.readline()

    def _drain_stderr(self) -> str:
        lines: list[str] = []
        while True:
            try:
                lines.append(self.stderr_queue.get_nowait())
            except queue.Empty:
                break
        return "\n".join(lines[-20:])


def tool_text(result: dict[str, Any]) -> str:
    parts = []
    for item in result.get("content", []):
        if item.get("type") == "text":
            parts.append(item.get("text", ""))
    return "\n".join(parts)


def run_in_local_chrome(code: str, timeout: int = 240, client_name: str = "dunhill-chrome-bridge") -> str:
    load_env()
    client = PlaywrightMCPClient(timeout=timeout, client_name=client_name)
    try:
        client.start()
        return client.run_code(code, timeout=timeout)
    finally:
        client.close()
