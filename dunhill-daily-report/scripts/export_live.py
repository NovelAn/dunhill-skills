"""
直播数据源导出

默认通过 Playwright MCP Extension 连接本机 Chrome 登录态，避免新开
Playwright profile 后跳转登录页。首次使用前请在 Chrome 的 Playwright
Extension 状态页复制 token，并在当前 shell 中设置：

    export PLAYWRIGHT_MCP_EXTENSION_TOKEN="..."

用法:
    python -u scripts/export_live.py
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys
import time
from pathlib import Path

from chrome_mcp_bridge import load_env, run_in_local_chrome


OVERVIEW_URL = "https://liveplatform.taobao.com/restful/index/live/overview?forceShowLegacyVersion=true"
SESSION_URL = "https://liveplatform.taobao.com/restful/index/data/live"
TRANSACTION_URL = "https://liveplatform.taobao.com/restful/index/data/transaction?page=OrderDetail"
DOWNLOAD_DIR = os.path.expanduser("~/Downloads")


LIVE_FILE_PATTERNS = {
    "直播间大盘数据": ["直播间大盘数据-*.xlsx"],
    "直播分场次效果": ["直播分场次效果*.xlsx", "*分场次效果*.xlsx"],
    "直播间成交订单明细_支付时间": [
        "直播间成交订单明细*.xlsx",
        "直播订单明细*.xlsx",
        "*订单明细*.xlsx",
        "*成交订单明细*.xlsx",
    ],
    "直播间成交订单明细_确认收货时间": [
        "直播间成交订单明细*.xlsx",
        "直播订单明细*.xlsx",
        "*订单明细*.xlsx",
        "*成交订单明细*.xlsx",
    ],
}

MODE_EXPECTED_LABELS = {
    "overview": ["直播间大盘数据"],
    "session": ["直播分场次效果"],
    "transaction": ["直播间成交订单明细_支付时间", "直播间成交订单明细_确认收货时间"],
    "all": [
        "直播间大盘数据",
        "直播分场次效果",
        "直播间成交订单明细_支付时间",
        "直播间成交订单明细_确认收货时间",
    ],
}

STAGE_ORDER = ["overview", "session", "transaction"]


def find_downloads_after(start_ts: float) -> list[Path]:
    downloads = Path(DOWNLOAD_DIR).expanduser()
    if not downloads.exists():
        return []
    return sorted(
        [
            path
            for path in downloads.glob("*.xlsx")
            if path.stat().st_mtime >= start_ts
        ],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def verify_live_downloads(start_ts: float, mode: str = "all") -> dict[str, list[str]]:
    files = find_downloads_after(start_ts)
    matched: dict[str, list[str]] = {}
    used: set[Path] = set()
    expected_labels = MODE_EXPECTED_LABELS.get(mode, MODE_EXPECTED_LABELS["all"])
    for label in expected_labels:
        patterns = LIVE_FILE_PATTERNS[label]
        label_matches = []
        candidate_files = (
            list(reversed(files))
            if label.startswith("直播间成交订单明细")
            else files
        )
        for path in candidate_files:
            if path in used:
                continue
            if any(fnmatch.fnmatch(path.name, pattern) for pattern in patterns):
                label_matches.append(str(path))
        if label_matches:
            matched[label] = label_matches
            used.add(Path(label_matches[0]))
    return matched


def expected_file_count(mode: str) -> int:
    return len(MODE_EXPECTED_LABELS.get(mode, MODE_EXPECTED_LABELS["all"]))


def wait_for_live_downloads(start_ts: float, mode: str, timeout: int = 90) -> dict[str, list[str]]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        matched = verify_live_downloads(start_ts, mode=mode)
        if len(matched) >= expected_file_count(mode):
            return matched
        time.sleep(1)
    return verify_live_downloads(start_ts, mode=mode)


def live_export_code(mode: str = "all", attach_current: bool = False) -> str:
    download_dir = json.dumps(DOWNLOAD_DIR)
    overview_url = json.dumps(OVERVIEW_URL)
    session_url = json.dumps(SESSION_URL)
    transaction_url = json.dumps(TRANSACTION_URL)
    mode_json = json.dumps(mode)
    attach_json = "true" if attach_current else "false"
    return f"""
async (page) => {{
  const downloadDir = {download_dir};
  const overviewUrl = {overview_url};
  const sessionUrl = {session_url};
  const transactionUrl = {transaction_url};
  const mode = {mode_json};
  const attachCurrent = {attach_json};
  const sleep = ms => page.waitForTimeout(ms);
  const sliderSelectors = [
    '#nc_1_wrapper',
    '#nc_1__scale_text',
    '.nc_wrapper',
    '.nc_scale',
    '[id*="nocaptcha"]',
    '[class*="nocaptcha"]',
    '[id*="captcha"]',
    '.baxia-dialog',
  ];
  const files = [];

  function safeName(name) {{
    return String(name || `download-${{Date.now()}}.xlsx`).replace(/[\\\\/:*?"<>|]/g, '_');
  }}

  async function retryEvaluate(fn, arg, label = 'page.evaluate') {{
    for (let i = 0; i < 5; i++) {{
      try {{
        return await page.evaluate(fn, arg);
      }} catch (error) {{
        const message = String(error.message || error);
        const transient = message.includes('Execution context was destroyed')
          || message.includes('Cannot find context')
          || message.includes('Navigation');
        if (!transient || i === 4) throw error;
        console.log(`[INFO] ${{label}} 遇到页面跳转，等待后重试 ${{i + 1}}/5`);
        await page.waitForLoadState('domcontentloaded', {{ timeout: 15000 }}).catch(() => null);
        await sleep(1200);
      }}
    }}
  }}

  async function assertLoggedIn(label) {{
    if (page.url().toLowerCase().includes('login')) {{
      throw new Error(`${{label}} 跳转到登录页：Playwright Extension 没有复用到已登录 Chrome。请先在本机 Chrome 登录淘宝直播平台，再重试。`);
    }}
  }}

  async function waitForSlider(label) {{
    for (let i = 0; i < 8; i++) {{
      const found = await retryEvaluate(selectors => {{
        for (const sel of selectors) {{
          const el = document.querySelector(sel);
          if (el && el.offsetParent !== null) return sel;
        }}
        const middleware = document.querySelector('.J_MIDDLEWARE_FRAME_WIDGET');
        if (middleware && middleware.offsetParent !== null) return '.J_MIDDLEWARE_FRAME_WIDGET';
        return null;
      }}, sliderSelectors);
      if (!found) {{
        await sleep(1000);
        continue;
      }}
      console.log(`[WARN] ${{label}} 检测到滑块验证码(${{found}})，请在 Chrome 中手动完成。`);
      for (let j = 0; j < 180; j++) {{
        await sleep(1000);
        const stillThere = await retryEvaluate(sel => {{
          const el = document.querySelector(sel);
          return !!(el && el.offsetParent !== null);
        }}, found, `${{label}} slider check`);
        if (!stillThere) {{
          await sleep(2000);
          return;
        }}
      }}
      throw new Error(`${{label}} 滑块验证等待超时`);
    }}
  }}

  async function dismissPopup() {{
    await retryEvaluate(() => {{
      const candidates = [...document.querySelectorAll('button')];
      for (const btn of candidates) {{
        const text = btn.textContent?.trim();
        if (btn.offsetParent !== null && ['关闭', '我知道了', '知道了'].includes(text)) {{
          btn.click();
          return true;
        }}
      }}
      return false;
    }}).catch(() => false);
  }}

  async function clickQueryIfPresent() {{
    await retryEvaluate(() => {{
      const texts = ['查询', '查 询'];
      for (const btn of document.querySelectorAll('button')) {{
        if (btn.offsetParent !== null && texts.includes(btn.textContent.trim())) {{
          btn.click();
          return true;
        }}
      }}
      return false;
    }});
  }}

  async function logCurrentPage(label) {{
    const title = await page.title().catch(() => '');
    console.log(`[INFO] ${{label}} 当前页面: ${{title}} | ${{page.url()}}`);
  }}

  async function waitForMainContent(label, expectedTexts = [], timeout = 90000) {{
    const deadline = Date.now() + timeout;
    let lastState = null;
    while (Date.now() < deadline) {{
      lastState = await retryEvaluate(texts => {{
        const text = document.body?.innerText || '';
        const compact = text.replace(/\\s+/g, '');
        return {{
          length: text.length,
          loading: compact.includes('正在加载'),
          hasDownload: compact.includes('下载'),
          hasExpected: texts.some(item => compact.includes(String(item).replace(/\\s+/g, ''))),
          sample: text.slice(0, 300),
        }};
      }}, expectedTexts, `${{label}} main content`);
      if (
        lastState.hasDownload
        || (lastState.length > 800 && !lastState.loading && (expectedTexts.length === 0 || lastState.hasExpected))
      ) {{
        return lastState;
      }}
      await sleep(1000);
    }}
    throw new Error(`${{label}} 主内容加载超时: ${{JSON.stringify(lastState)}}`);
  }}

  async function clickSidebarNav(label, navTexts, expectedUrlPart) {{
    const clicked = await retryEvaluate(texts => {{
      const isVisible = el => {{
        const style = window.getComputedStyle(el);
        return style.visibility !== 'hidden'
          && style.display !== 'none'
          && (el.offsetWidth > 0 || el.offsetHeight > 0 || el.getClientRects().length > 0);
      }};
      const candidates = [...document.querySelectorAll(
        'li[role="menuitem"], [role="menuitem"], .tbd-menu-item'
      )];
      for (const text of texts) {{
        for (const el of candidates) {{
          if (!isVisible(el)) continue;
          const content = (el.textContent || '').replace(/\\s+/g, '');
          if (!content.includes(text)) continue;
          el.click();
          return text;
        }}
      }}
      return null;
    }}, navTexts, `${{label}} sidebar nav`);
    if (clicked) {{
      console.log(`[INFO] ${{label}} 通过左侧导航点击: ${{clicked}}`);
      await page.waitForURL(url => url.href.includes(expectedUrlPart), {{ timeout: 20000 }}).catch(() => null);
      if (!page.url().includes(expectedUrlPart)) {{
        throw new Error(`${{label}} 已点击左侧导航 ${{clicked}}，但页面没有切换到目标地址，当前 URL: ${{page.url()}}`);
      }}
      await sleep(8000);
      await waitForMainContent(label, ['下载']);
      await waitForSlider(label);
      return true;
    }}
    return false;
  }}

  async function gotoLivePage(label, expectedUrlPart, targetUrl, navTexts) {{
    if (page.url().includes(expectedUrlPart)) return;
    await logCurrentPage(label);
    if (page.url().includes('liveplatform.taobao.com')) {{
      const clicked = await clickSidebarNav(label, navTexts, expectedUrlPart);
      if (clicked) return;
    }}
    if (attachCurrent && !page.url().includes('liveplatform.taobao.com')) {{
      throw new Error(`${{label}} 当前页不是目标页，且 --attach-current 模式不会主动 URL 跳转。请先把 Chrome 切到直播平台页。`);
    }}
    console.log(`[INFO] ${{label}} 左侧导航不可用，使用 URL 打开目标页。`);
    await page.goto(targetUrl, {{ waitUntil: 'domcontentloaded', timeout: 60000 }});
    await waitForMainContent(label, ['下载']);
  }}

  async function clickDownload(label, buttonTexts) {{
    await waitForMainContent(label, ['下载']);
    await waitForSlider(label);
    await dismissPopup();
    let clicked = null;
    for (const selector of ['button[iconid="liveDownload"]', 'button[data-tblalog-t="下载"]']) {{
      const locator = page.locator(selector).first();
      if (await locator.isVisible({{ timeout: 5000 }}).catch(() => false)) {{
        await locator.click({{ timeout: 30000 }});
        clicked = selector;
        break;
      }}
    }}
    for (const text of buttonTexts) {{
      if (clicked) break;
      const locator = page.locator('button, a, [role="button"]').filter({{ hasText: text }}).first();
      if (await locator.isVisible({{ timeout: 3000 }}).catch(() => false)) {{
        try {{
          await locator.click({{ timeout: 30000 }});
        }} catch (error) {{
          if (String(error.message || error).includes('J_MIDDLEWARE_FRAME_WIDGET')) {{
            console.log(`[WARN] ${{label}} 页面有风控遮罩，请在 Chrome 中完成滑块/验证后等待脚本继续。`);
            await waitForSlider(label);
            await locator.click({{ timeout: 30000 }});
          }} else {{
            throw error;
          }}
        }}
        clicked = text;
        break;
      }}
    }}
    if (!clicked) {{
      const buttons = await retryEvaluate(() => {{
        return [...document.querySelectorAll('button, a, [role="button"]')]
          .filter(e => e.offsetParent !== null)
          .map(e => e.textContent?.trim())
          .filter(Boolean)
          .slice(0, 40);
      }}, undefined, `${{label}} visible buttons`);
      throw new Error(`${{label}} 未找到下载按钮，可见按钮：${{JSON.stringify(buttons)}}`);
    }}
    const file = {{
      label,
      source: 'chrome-download-folder-verified-by-python',
      clicked,
    }};
    files.push(file);
    await sleep(8000);
    return file.path || file.source;
  }}

  async function switchTimeType(timeType) {{
    const section = page.locator('.tta-order-details').first();
    await section.waitFor({{ state: 'visible', timeout: 30000 }});

    const triggerInfo = await retryEvaluate(() => {{
      const normalize = text => String(text || '').replace(/\\s+/g, '').trim();
      const visible = el => {{
        if (!el) return false;
        const style = window.getComputedStyle(el);
        return style.visibility !== 'hidden'
          && style.display !== 'none'
          && (el.offsetWidth > 0 || el.offsetHeight > 0 || el.getClientRects().length > 0);
      }};
      const root = document.querySelector('.tta-order-details') || document;
      const candidates = [...root.querySelectorAll('*')]
        .filter(visible)
        .map(el => {{
          const rect = el.getBoundingClientRect();
          return {{
            text: normalize(el.textContent),
            x: rect.x,
            y: rect.y,
            width: rect.width,
            height: rect.height,
          }};
        }})
        .filter(item =>
          item.width >= 120
          && item.width <= 520
          && item.height >= 24
          && item.height <= 80
          && item.text.includes('时间类型')
          && (item.text.includes('支付时间') || item.text.includes('下单时间') || item.text.includes('确认收货时间'))
        )
        .sort((a, b) => a.y - b.y || (a.width * a.height) - (b.width * b.height));
      return candidates[0] || null;
    }}, undefined, 'find time type trigger');
    if (!triggerInfo) {{
      throw new Error('交易订单明细未找到“时间类型”下拉控件');
    }}

    await page.mouse.click(
      triggerInfo.x + Math.max(40, triggerInfo.width - 28),
      triggerInfo.y + triggerInfo.height / 2
    );
    await sleep(900);

    const optionInfo = await retryEvaluate(target => {{
      const normalize = text => String(text || '').replace(/\\s+/g, '').trim();
      const visible = el => {{
        if (!el) return false;
        const style = window.getComputedStyle(el);
        return style.visibility !== 'hidden'
          && style.display !== 'none'
          && (el.offsetWidth > 0 || el.offsetHeight > 0 || el.getClientRects().length > 0);
      }};
      const options = [...document.querySelectorAll(
        '.tbd-select-option, .ant-select-item-option, [class*="select-option"], [role="option"], li, div'
      )]
        .filter(visible)
        .map(el => {{
          const rect = el.getBoundingClientRect();
          return {{
            text: normalize(el.textContent),
            x: rect.x,
            y: rect.y,
            width: rect.width,
            height: rect.height,
          }};
        }})
        .filter(item =>
          item.text === normalize(target)
          && item.width >= 80
          && item.width <= 520
          && item.height >= 24
          && item.height <= 80
        )
        .sort((a, b) => a.y - b.y || (a.width * a.height) - (b.width * b.height));
      return options[0] || null;
    }}, timeType, `find time type option ${{timeType}}`);
    if (!optionInfo) {{
      throw new Error(`交易订单明细时间类型下拉已打开，但未找到 ${{timeType}} 选项`);
    }}
    await page.mouse.click(optionInfo.x + optionInfo.width / 2, optionInfo.y + optionInfo.height / 2);
    await sleep(1200);

    const verified = await retryEvaluate(target => {{
      const normalize = text => String(text || '').replace(/\\s+/g, '').trim();
      const root = document.querySelector('.tta-order-details') || document;
      const visible = el => {{
        if (!el) return false;
        const style = window.getComputedStyle(el);
        return style.visibility !== 'hidden'
          && style.display !== 'none'
          && (el.offsetWidth > 0 || el.offsetHeight > 0 || el.getClientRects().length > 0);
      }};
      return [...root.querySelectorAll('*')]
        .filter(visible)
        .some(el => {{
          const rect = el.getBoundingClientRect();
          const text = normalize(el.textContent);
          return rect.width >= 120
            && rect.width <= 520
            && rect.height >= 24
            && rect.height <= 80
            && text.includes('时间类型')
            && text.includes(normalize(target));
        }});
    }}, timeType, `verify time type ${{timeType}}`);
    if (!verified) {{
      throw new Error(`交易订单明细时间类型切换后未显示 ${{timeType}}`);
    }}
    return true;
  }}

  async function queryAndDownloadOrderDetails(timeType) {{
    await switchTimeType(timeType);
    await sleep(1200);
    await clickQueryIfPresent();
    await sleep(12000);
    await waitForSlider(`交易订单明细_${{timeType}}`);
    await clickOrderDetailsDownload(`直播间成交订单明细_${{timeType}}`);
    await sleep(3000);
  }}

  async function ensureOrderDetailsTab() {{
    await waitForSlider('交易分析-订单明细');
    const tab = page.locator('[role="tab"]').filter({{ hasText: '订单明细' }}).first();
    if (await tab.isVisible({{ timeout: 5000 }}).catch(() => false)) {{
      await tab.click({{ timeout: 20000 }});
      await page.waitForURL(url => url.href.includes('page=OrderDetail'), {{ timeout: 20000 }}).catch(() => null);
    }}
    await sleep(6000);
    const section = page.locator('.tta-order-details').first();
    if (!await section.isVisible({{ timeout: 20000 }}).catch(() => false)) {{
      throw new Error(`交易分析已打开，但未进入“订单明细”页，当前 URL: ${{page.url()}}`);
    }}
  }}

  async function clickOrderDetailsDownload(label) {{
    await waitForSlider(label);
    await dismissPopup();
    const section = page.locator('.tta-order-details').first();
    await section.waitFor({{ state: 'visible', timeout: 30000 }});
    const locator = section.locator('button, a, [role="button"]').filter({{ hasText: /下\\s*载|下载/ }}).first();
    if (!await locator.isVisible({{ timeout: 10000 }}).catch(() => false)) {{
      const buttons = await section.locator('button, a, [role="button"]').allTextContents({{ timeout: 5000 }}).catch(() => []);
      throw new Error(`${{label}} 未在“直播订单明细”模块找到下载按钮，可见按钮：${{JSON.stringify(buttons)}}`);
    }}
    await locator.click({{ timeout: 30000 }});
    files.push({{
      label,
      source: 'chrome-download-folder-verified-by-python',
      clicked: '直播订单明细模块下载',
    }});
    await sleep(8000);
  }}

  if (mode === 'all' || mode === 'overview') {{
    await gotoLivePage('直播概览', '/restful/index/live/overview', overviewUrl, ['直播概览', '大盘']);
    await sleep(6000);
    await assertLoggedIn('直播概览');
    await clickDownload('直播间大盘数据', ['下载']);
  }}

  if (mode === 'all' || mode === 'session') {{
    await gotoLivePage('场次分析', '/restful/index/data/live', sessionUrl, ['场次分析']);
    await sleep(8000);
    await assertLoggedIn('场次分析');
    await clickDownload('直播分场次效果', ['下载', '下 载']);
  }}

  if (mode === 'all' || mode === 'transaction') {{
    await gotoLivePage('交易分析', '/restful/index/data/transaction', transactionUrl, ['交易分析', '成交订单', '订单明细']);
    await sleep(8000);
    await assertLoggedIn('交易分析');
    await ensureOrderDetailsTab();

    await queryAndDownloadOrderDetails('支付时间');
    await queryAndDownloadOrderDetails('确认收货时间');
  }}

  return {{ ok: true, count: files.length, files }};
}}
"""


def run_single_extension_stage(timeout: int, run_start_ts: float, mode: str, attach_current: bool) -> bool:
    existing = verify_live_downloads(run_start_ts, mode=mode)
    if len(existing) >= expected_file_count(mode):
        print(f"[SKIP] {mode} 本次运行已发现新增文件，跳过重复下载。")
        for label, paths in existing.items():
            print(f"  - {label}: {paths[0]}")
        return True

    stage_start_ts = time.time()
    token_set = bool(os.environ.get("PLAYWRIGHT_MCP_EXTENSION_TOKEN"))
    if not token_set:
        print("[WARN] 未检测到 PLAYWRIGHT_MCP_EXTENSION_TOKEN。")
        print("       可打开 Chrome 的 Playwright Extension 状态页，复制 token 后设置环境变量。")
        print("       未设置 token 时，Chrome 可能会弹出连接确认页，需要手动确认。")

    try:
        print(f"[2/4] 已连接 MCP，准备运行 {mode} 下载流程...")
        text = run_in_local_chrome(
            live_export_code(mode=mode, attach_current=attach_current),
            timeout=timeout,
            client_name=f"dunhill-live-{mode}-export",
        )
        print("[3/4] 下载流程返回:")
        print(text)
        matched = wait_for_live_downloads(stage_start_ts, mode=mode)
        if "### Error" in text:
            if len(matched) >= expected_file_count(mode):
                print(f"[OK] {mode} 页面流程报错，但 Downloads 中发现本阶段新增文件:")
                for label, paths in matched.items():
                    print(f"  - {label}: {paths[0]}")
                return True
            if matched:
                print(f"[WARN] {mode} 只发现部分本阶段新增文件:")
                for label, paths in matched.items():
                    print(f"  - {label}: {paths[0]}")
            return False
        if matched:
            print(f"[OK] {mode} Downloads 文件校验:")
            for label, paths in matched.items():
                print(f"  - {label}: {paths[0]}")
        if len(matched) < expected_file_count(mode):
            print(f"[FAIL] Downloads 中未发现 {mode} 所需的全部本阶段新增文件。")
            print(f"       期望 {expected_file_count(mode)} 类，实际发现 {len(matched)} 类。")
            return False
        print(f"[4/4] {mode} 导出流程结束。")
        return True
    except Exception as exc:
        matched = wait_for_live_downloads(stage_start_ts, mode=mode, timeout=15)
        if len(matched) >= expected_file_count(mode):
            print(f"\n[OK] {mode} MCP 异常退出，但 Downloads 中发现本阶段新增文件:")
            for label, paths in matched.items():
                print(f"  - {label}: {paths[0]}")
            return True
        print(f"\n[FAIL] {mode} 直播数据导出失败: {exc}")
        print("\n排查建议:")
        print("  1. 确认本机 Chrome 已安装 Playwright Extension。")
        print("  2. 打开扩展状态页，复制 PLAYWRIGHT_MCP_EXTENSION_TOKEN 并设置到当前 shell。")
        print("  3. 确认本机 Chrome 已登录淘宝/淘宝直播平台。")
        print("  4. 如果页面出现滑块，请在 Chrome 中手动完成后等待脚本继续。")
        return False


def run_extension_export(timeout: int, run_start_ts: float, mode: str, attach_current: bool) -> bool:
    modes = STAGE_ORDER if mode == "all" else [mode]
    success = True
    for stage in modes:
        print()
        print("-" * 60)
        print(f"直播数据源阶段: {stage}")
        print("-" * 60)
        if not run_single_extension_stage(
            timeout=timeout,
            run_start_ts=run_start_ts,
            mode=stage,
            attach_current=attach_current,
        ):
            success = False
            break
    return success


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser(description="导出淘宝直播数据源")
    parser.add_argument("--timeout", type=int, default=420, help="整体等待超时时间（秒）")
    parser.add_argument(
        "--mode",
        choices=["all", "overview", "session", "transaction"],
        default="all",
        help="导出范围：all=全部，overview=大盘，session=场次，transaction=订单明细",
    )
    parser.add_argument(
        "--attach-current",
        action="store_true",
        help="复用 Playwright Extension 当前选中的页面，不主动导航到目标页",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("直播数据源导出 (Playwright MCP Extension)")
    print("=" * 60)
    print(f"下载目录: {DOWNLOAD_DIR}")
    print()

    start_ts = time.time()
    success = run_extension_export(
        timeout=args.timeout,
        run_start_ts=start_ts,
        mode=args.mode,
        attach_current=args.attach_current,
    )
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
