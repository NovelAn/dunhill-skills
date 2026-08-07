"""
Refund export through the user's local Chrome login state.

Architecture:
1. The user is logged in to QianNiu/Taobao in local Chrome.
2. This script connects to that Chrome profile via Playwright MCP Extension
   and runs the fast export actions.

Use --attach-current only when the Playwright Extension-controlled current page
is already the refund page; otherwise the script navigates to the refund URL
itself.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from chrome_mcp_bridge import load_env, run_in_local_chrome


REFUND_LIST_URL = "https://myseller.taobao.com/home.htm/trade-platform/refund-list"
EXPORT_LIST_URL = "https://myseller.taobao.com/home.htm/trade-platform/refund-list/export-list"
DOWNLOAD_DIR = os.path.expanduser("~/Downloads")
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "dunhill-config.yaml"


def latest_download_after(start_ts: float) -> str | None:
    downloads = Path(DOWNLOAD_DIR).expanduser()
    pattern = re.compile(r"^\d+_\d+_\d+\.xlsx$")
    candidates = sorted(
        downloads.glob("*.xlsx"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in candidates:
        if path.stat().st_mtime >= start_ts and pattern.match(path.name):
            return str(path)
    return None


def wait_for_download_after(start_ts: float, timeout: int = 90) -> str | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        downloaded = latest_download_after(start_ts)
        if downloaded:
            return downloaded
        time.sleep(1)
    return None


def sanitize_mcp_output(text: str, password: str) -> str:
    sanitized = re.sub(r'const taobaoPassword = ".*?";', 'const taobaoPassword = "[REDACTED]";', text)
    sanitized = re.sub(r"const taobaoPassword = '.*?';", "const taobaoPassword = '[REDACTED]';", sanitized)
    if password:
        sanitized = sanitized.replace(password, "[REDACTED]")
    return sanitized


def load_taobao_credentials() -> tuple[str, str]:
    load_env()
    username = os.environ.get("TAOBAO_USERNAME", "").strip()
    if not username and CONFIG_PATH.exists():
        text = CONFIG_PATH.read_text(encoding="utf-8")
        match = re.search(r'^\s*taobao_username:\s*["\']?(.+?)["\']?\s*$', text, re.MULTILINE)
        if match:
            username = match.group(1).strip()
    password = os.environ.get("TAOBAO_PASSWORD", "").strip()
    return username, password


def refund_export_code(attach_current: bool, username: str, password: str) -> str:
    refund_url = json.dumps(REFUND_LIST_URL)
    export_url = json.dumps(EXPORT_LIST_URL)
    download_dir = json.dumps(DOWNLOAD_DIR)
    taobao_username = json.dumps(username)
    taobao_password = json.dumps(password)
    attach = "true" if attach_current else "false"
    return f"""
async (page) => {{
  const refundUrl = {refund_url};
  const exportUrl = {export_url};
  const downloadDir = {download_dir};
  const taobaoUsername = {taobao_username};
  const taobaoPassword = {taobao_password};
  const attachCurrent = {attach};
  const today = new Date().toISOString().slice(0, 10);
  const sleep = ms => page.waitForTimeout(ms);

  function normalize(text) {{
    return String(text || '').replace(/\\s+/g, '').trim();
  }}

  async function clickByText(texts, selector = 'button, a, [role="button"], .next-menu-item') {{
    const result = await page.evaluate(({{ texts, selector }}) => {{
      const normalize = text => String(text || '').replace(/\\s+/g, '').trim();
      const targets = texts.map(normalize);
      const elements = [...document.querySelectorAll(selector)];
      for (const el of elements) {{
        if (el.offsetParent !== null && targets.includes(normalize(el.textContent))) {{
          el.click();
          return {{ ok: true, text: el.textContent.trim() }};
        }}
      }}
      return {{
        ok: false,
        visible: elements
          .filter(el => el.offsetParent !== null)
          .map(el => el.textContent?.trim())
          .filter(Boolean)
          .slice(0, 60),
      }};
    }}, {{ texts, selector }});
    if (!result.ok) {{
      throw new Error(`Cannot find clickable text ${{texts.join('/')}}. Visible: ${{JSON.stringify(result.visible)}}`);
    }}
    return result;
  }}

  function exactTextRegex(text) {{
    return new RegExp(`^\\\\s*${{String(text).replace(/[.*+?^${{}}()|[\\]\\\\]/g, '\\\\$&')}}\\\\s*$`);
  }}

  async function clickButtonExact(text, targetPage = page, timeout = 30000) {{
    const locator = targetPage.locator('button').filter({{ hasText: exactTextRegex(text) }}).first();
    await locator.waitFor({{ state: 'visible', timeout: Math.min(timeout, 30000) }});
    try {{
      await locator.click({{ timeout: Math.min(timeout, 15000) }});
      return {{ ok: true, text, via: 'locator' }};
    }} catch (err) {{
      // 回退：按钮可点击但被浮层遮挡时，Playwright actionability(receives-events) 会失败。
      // 直接在 DOM 上触发 click()，绕过鼠标坐标命中检测（refund 页搜索/选状态一直用这方式）。
      const diag = await targetPage.evaluate((needle) => {{
        const norm = t => String(t || '').replace(/\\s+/g, '').trim();
        const target = norm(needle);
        const btn = [...document.querySelectorAll('button')]
          .filter(b => b.offsetParent !== null)
          .find(b => norm(b.textContent) === target);
        if (!btn) return {{ clicked: false, reason: 'not-found' }};
        const disabled = btn.disabled
          || btn.classList.contains('disabled')
          || btn.classList.contains('next-btn-disabled')
          || btn.getAttribute('aria-disabled') === 'true';
        if (disabled) return {{ clicked: false, reason: 'disabled', classList: btn.className }};
        btn.click();
        return {{ clicked: true, classList: btn.className }};
      }}, text).catch(() => null);
      if (!diag || !diag.clicked) {{
        const errLine = err && err.message ? err.message.split('\\n')[0] : String(err);
        throw new Error(`clickButtonExact(${{JSON.stringify(text)}}) failed: ${{errLine}} | fallback diag: ${{JSON.stringify(diag)}}`);
      }}
      return {{ ok: true, text, via: 'dom-click-fallback' }};
    }}
  }}

  async function hasVisibleButton(text, targetPage = page, timeout = 10000) {{
    const locator = targetPage.locator('button').filter({{ hasText: exactTextRegex(text) }}).first();
    return await locator.isVisible({{ timeout }}).catch(() => false);
  }}

  async function confirmPrivacy(targetPage = page) {{
    await targetPage.evaluate(() => {{
      const containers = [
        ...document.querySelectorAll('[role="dialog"], .next-dialog, .next-overlay-wrapper'),
      ];
      for (const container of containers) {{
        if (container.offsetParent === null) continue;
        if (!container.textContent.includes('用户个人信息')) continue;
        for (const btn of container.querySelectorAll('button')) {{
          if (btn.textContent.trim() === '确认') {{
            btn.click();
            return true;
          }}
        }}
      }}
      for (const btn of document.querySelectorAll('button')) {{
        if (btn.offsetParent !== null && btn.textContent.trim() === '确认') {{
          btn.click();
          return true;
        }}
      }}
      return false;
    }}).catch(() => false);
    await sleep(1200);
  }}

  async function getVisibleButtons(targetPage = page) {{
    return await targetPage.evaluate(() => {{
      return [...document.querySelectorAll('button, a, [role="button"]')]
        .filter(el => el.offsetParent !== null)
        .map(el => el.textContent?.trim())
        .filter(Boolean)
        .slice(0, 80);
    }});
  }}

  async function hasExportReportList(targetPage = page) {{
    return await targetPage.evaluate(() => {{
      const text = document.body?.innerText || '';
      return text.includes('报表申请时间：') || text.includes('下载退款单报表');
    }}).catch(() => false);
  }}

  async function getLatestExportReportState(targetPage) {{
    return await targetPage.evaluate(() => {{
      const text = document.body.innerText || '';
      const sections = text.split('报表申请时间：').slice(1);
      const first = sections[0] || '';
      const reportTime = first.split('\\n')[0]?.trim() || null;
      const countMatch = first.match(/预计退款单数量：\\s*(\\d+)/);
      return {{
        onExportList: location.href.includes('/refund-list/export-list') || text.includes('报表申请时间：') || text.includes('下载退款单报表'),
        reportTime,
        reportDate: reportTime ? reportTime.slice(0, 10) : null,
        estimatedCount: countMatch ? Number(countMatch[1]) : null,
        completed: first.includes('进度：已完成') || first.includes('进度: 已完成') || first.includes('已完成'),
        preview: first.slice(0, 600),
      }};
    }});
  }}

  function parseReportTimeMs(text) {{
    const match = String(text || '').match(/报表申请时间：\\s*(\\d{{4}})[-/](\\d{{1,2}})[-/](\\d{{1,2}})\\s+(\\d{{1,2}}):(\\d{{2}})(?::(\\d{{2}}))?/);
    if (!match) return null;
    const [, year, month, day, hour, minute, second = '0'] = match;
    return new Date(
      Number(year),
      Number(month) - 1,
      Number(day),
      Number(hour),
      Number(minute),
      Number(second)
    ).getTime();
  }}

  async function waitForGeneratedDownloadButton(targetPage, minReportTimeMs, timeoutMs = 60000) {{
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {{
      const state = await clickGeneratedDownload(targetPage, minReportTimeMs, false);
      if (state.ok) return state;
      await sleep(1500);
    }}
    return await clickGeneratedDownload(targetPage, minReportTimeMs, false);
  }}

  async function clickGeneratedDownload(targetPage, minReportTimeMs, shouldClick = true) {{
    return await targetPage.evaluate(({{ minReportTimeMs, shouldClick }}) => {{
      const parseReportTimeMs = text => {{
        const match = String(text || '').match(/报表申请时间：\\s*(\\d{{4}})[-/](\\d{{1,2}})[-/](\\d{{1,2}})\\s+(\\d{{1,2}}):(\\d{{2}})(?::(\\d{{2}}))?/);
        if (!match) return null;
        const [, year, month, day, hour, minute, second = '0'] = match;
        return new Date(
          Number(year),
          Number(month) - 1,
          Number(day),
          Number(hour),
          Number(minute),
          Number(second)
        ).getTime();
      }};
      const reportContainer = button => {{
        const directRow = button.closest('tr, .next-table-row, .next-table-row-wrapper, .next-table-row-inner');
        if (directRow && directRow.textContent.includes('报表申请时间：')) return directRow;
        let fallback = null;
        let node = button;
        for (let depth = 0; node && depth < 10; depth += 1) {{
          const text = node.textContent || '';
          if (text.includes('报表申请时间：')) {{
            const downloadCount = [...node.querySelectorAll('button')]
              .filter(btn => btn.offsetParent !== null && btn.textContent.trim() === '下载退款单报表')
              .length;
            if (downloadCount === 1) return node;
            fallback = fallback || node;
          }}
          node = node.parentElement;
        }}
        return fallback;
      }};
      const buttons = [...document.querySelectorAll('button')].filter(btn => btn.offsetParent !== null);
      const candidates = [];
      for (let index = 0; index < buttons.length; index += 1) {{
        const btn = buttons[index];
        if (btn.textContent.trim() !== '下载退款单报表') continue;
        const container = reportContainer(btn);
        const text = container?.textContent || '';
        const reportTimeMs = parseReportTimeMs(text);
        candidates.push({{
          index,
          text: btn.textContent.trim(),
          reportTimeMs,
          preview: text.replace(/\\s+/g, ' ').trim().slice(0, 260),
        }});
      }}
      const matches = candidates
        .filter(candidate => candidate.reportTimeMs !== null && candidate.reportTimeMs >= minReportTimeMs)
        .sort((a, b) => b.reportTimeMs - a.reportTimeMs);
      if (matches.length > 0) {{
        const selected = matches[0];
        if (shouldClick) buttons[selected.index].click();
        return {{ ok: true, ...selected, matchedCount: matches.length }};
      }}
      return {{
        ok: false,
        minReportTimeMs,
        candidates,
        visibleButtons: buttons.map(btn => btn.textContent.trim()).filter(Boolean).slice(0, 50),
      }};
    }}, {{ minReportTimeMs, shouldClick }});
  }}

  async function openExportList(targetPage = page) {{
    if (targetPage.url().includes('/refund-list/export-list') || await hasExportReportList(targetPage)) {{
      return targetPage;
    }}

    const visibleButtons = await getVisibleButtons(targetPage);
    if (visibleButtons.includes('批量导出')) {{
      await clickButtonExact('批量导出', targetPage);
      await sleep(1500);
    }}

    const buttonsAfterExport = await getVisibleButtons(targetPage);
    if (buttonsAfterExport.includes('查看已生成报表')) {{
      await clickButtonExact('查看已生成报表', targetPage);
      await sleep(1000);
      await confirmPrivacy(targetPage);
      await sleep(2500);
      const existing = targetPage.context().pages().find(p => p.url().includes('/refund-list/export-list'));
      if (existing) {{
        await existing.bringToFront();
        await sleep(1500);
        return existing;
      }}
    }}

    await targetPage.goto(exportUrl, {{ waitUntil: 'domcontentloaded', timeout: 60000 }});
    await targetPage.bringToFront();
    await sleep(2500);
    await confirmPrivacy(targetPage);
    return targetPage;
  }}

  async function generateReportFromRefundList() {{
    if (!page.url().includes('/trade-platform/refund-list')) {{
      await page.goto(refundUrl, {{ waitUntil: 'domcontentloaded', timeout: 60000 }});
      await sleep(2500);
    }}
    await clickButtonExact('批量导出');
    await sleep(1000);

    if (!await hasVisibleButton('生成报表', page, 15000)) {{
      const buttonsBeforeGenerate = await getVisibleButtons(page);
      throw new Error(`导出弹窗未出现，无法点击生成报表。可见按钮: ${{JSON.stringify(buttonsBeforeGenerate)}}`);
    }}

    const generationStartedAtMs = Date.now() - 60000;
    await clickButtonExact('生成报表');
    await sleep(1200);
    await confirmPrivacy();
    await page.keyboard.press('Escape').catch(() => {{}});
    await sleep(1000);
    return generationStartedAtMs;
  }}

  async function findLoginFrame() {{
    for (let i = 0; i < 20; i++) {{
      for (const frame of page.frames()) {{
        const passwordInput = frame
          .locator('input[type="password"], input[name="fm-login-password"], #fm-login-password')
          .first();
        if (await passwordInput.isVisible({{ timeout: 300 }}).catch(() => false)) {{
          return frame;
        }}
      }}
      await sleep(500);
    }}
    return null;
  }}

  async function fillFirstVisible(frame, selectors, value, label) {{
    for (const selector of selectors) {{
      const locator = frame.locator(selector).first();
      if (await locator.isVisible({{ timeout: 1000 }}).catch(() => false)) {{
        await locator.fill(value, {{ timeout: 10000 }});
        return selector;
      }}
    }}
    throw new Error(`Cannot find ${{label}} input on Taobao login page.`);
  }}

  async function clickLoginSubmit(frame) {{
    const selectors = [
      'button[type="submit"]',
      '.fm-button',
      '#login-form button',
      'button:has-text("登录")',
      'a:has-text("登录")',
      '[role="button"]:has-text("登录")',
    ];
    for (const selector of selectors) {{
      const locator = frame.locator(selector).first();
      if (await locator.isVisible({{ timeout: 1000 }}).catch(() => false)) {{
        await locator.click({{ timeout: 10000 }});
        return selector;
      }}
    }}
    await frame.keyboard.press('Enter');
    return 'keyboard-enter';
  }}

  async function loginIfNeeded() {{
    if (!page.url().toLowerCase().includes('login')) return false;
    if (!taobaoUsername || !taobaoPassword) {{
      throw new Error('Refund page redirected to login, but Taobao username/password are not configured.');
    }}

    const frame = await findLoginFrame();
    if (!frame) {{
      throw new Error('Refund page redirected to login, but no password input was found.');
    }}

    await fillFirstVisible(
      frame,
      [
        'input[name="fm-login-id"]',
        '#fm-login-id',
        'input[name="loginId"]',
        'input[autocomplete="username"]',
        'input[type="text"]',
      ],
      taobaoUsername,
      'username'
    );
    await fillFirstVisible(
      frame,
      [
        'input[name="fm-login-password"]',
        '#fm-login-password',
        'input[name="password"]',
        'input[autocomplete="current-password"]',
        'input[type="password"]',
      ],
      taobaoPassword,
      'password'
    );
    const submitSelector = await clickLoginSubmit(frame);
    await page.waitForURL(url => !url.href.toLowerCase().includes('login'), {{ timeout: 90000 }}).catch(() => null);
    await sleep(3000);
    if (page.url().toLowerCase().includes('login')) {{
      const text = await page.evaluate(() => document.body?.innerText?.slice(0, 1200) || '').catch(() => '');
      throw new Error(`Taobao login did not complete after submitting credentials via ${{submitSelector}}. It may require slider or phone verification. Page text: ${{text}}`);
    }}
    return true;
  }}

  async function ensureRefundPage() {{
    if (!attachCurrent || !page.url().includes('/trade-platform/refund-list')) {{
      await page.goto(refundUrl, {{ waitUntil: 'domcontentloaded', timeout: 60000 }});
    }}
    await sleep(3000);
    if (page.url().toLowerCase().includes('login')) {{
      await loginIfNeeded();
      if (!page.url().includes('/trade-platform/refund-list')) {{
        await page.goto(refundUrl, {{ waitUntil: 'domcontentloaded', timeout: 60000 }});
      }}
      await sleep(3000);
    }}
    await page
      .locator('.next-select-trigger')
      .filter({{ hasText: '售后状态' }})
      .first()
      .waitFor({{ state: 'visible', timeout: 60000 }});
  }}

  async function selectAllRefundStatus() {{
    await page
      .locator('.next-select-trigger')
      .filter({{ hasText: '售后状态' }})
      .first()
      .click({{ timeout: 30000 }});
    await sleep(1500);

    const changed = await page.evaluate(() => {{
      const overlays = [...document.querySelectorAll('.next-overlay-wrapper')];
      let sawRunning = false;
      let sawAll = false;
      for (const overlay of overlays) {{
        if (overlay.offsetParent === null) continue;
        const items = [...overlay.querySelectorAll('.next-menu-item')];
        for (const item of items) {{
          if (item.textContent.trim() === '进行中的订单') sawRunning = true;
          if (item.textContent.trim() === '进行中的订单' && item.classList.contains('next-selected')) {{
            item.click();
          }}
        }}
        for (const item of items) {{
          if (item.textContent.trim() === '全部') sawAll = true;
          if (item.textContent.trim() === '全部' && !item.classList.contains('next-selected')) {{
            item.click();
          }}
        }}
      }}
      return {{ sawRunning, sawAll }};
    }});
    if (!changed.sawAll) {{
      const bodyText = await page.evaluate(() => document.body.innerText.slice(0, 1200));
      throw new Error(`Cannot find refund status option 全部. Page text: ${{bodyText}}`);
    }}
    await sleep(800);
    await page.keyboard.press('Escape').catch(() => {{}});
    await sleep(500);

    const statusText = await page.evaluate(() => {{
      const triggers = [...document.querySelectorAll('.next-select-trigger')];
      for (const trigger of triggers) {{
        if (trigger.textContent.includes('售后状态')) return trigger.textContent.trim();
      }}
      return '';
    }});
    if (!statusText.includes('全部')) throw new Error(`Refund status was not set to 全部: ${{statusText}}`);
    return statusText;
  }}

  await ensureRefundPage();
  const statusText = await selectAllRefundStatus();

  await clickByText(['搜索售后单']);
  await sleep(5000);
  const totalCount = await page.evaluate(() => {{
    const match = document.body.innerText.match(/已选\\s*\\(0\\/(\\d+)\\)/);
    return match ? Number(match[1]) : null;
  }});

  const generationStartedAtMs = await generateReportFromRefundList();
  let exportPage = await openExportList(page);
  await exportPage.bringToFront();
  await sleep(2000);

  let reportState = await getLatestExportReportState(exportPage);
  let downloadState = await waitForGeneratedDownloadButton(exportPage, generationStartedAtMs, 60000);

  if (!reportState.onExportList) {{
    throw new Error(`Refund export did not navigate to export-list. Current URL: ${{exportPage.url()}}`);
  }}
  if (!downloadState.ok) {{
    throw new Error(`No generated 下载退款单报表 button matched this run. State: ${{JSON.stringify(downloadState)}}`);
  }}
  downloadState = await clickGeneratedDownload(exportPage, generationStartedAtMs, true);
  await confirmPrivacy(exportPage);
  await sleep(3000);

  return {{
    ok: true,
    statusText,
    totalCount,
    generationStartedAt: new Date(generationStartedAtMs).toISOString(),
    reusedExistingReport: false,
    exportListUrl: exportPage.url(),
    reportTime: reportState.reportTime,
    estimatedCount: reportState.estimatedCount,
    latestReportCompleted: reportState.completed,
    reportPreview: reportState.preview.slice(0, 300),
    downloadSignal: 'clicked-download-button',
  }};
}}
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Export refund report through local Chrome login state")
    parser.add_argument(
        "--attach-current",
        action="store_true",
        help="Assume the Extension-controlled current page is already the refund page",
    )
    parser.add_argument("--timeout", type=int, default=420)
    args = parser.parse_args()
    start_ts = time.time()
    username, password = load_taobao_credentials()

    try:
        output = run_in_local_chrome(
            refund_export_code(args.attach_current, username, password),
            timeout=args.timeout,
            client_name="dunhill-refund-export",
        )
    except Exception as exc:
        print(f"[FAIL] {exc}")
        return 1

    print(sanitize_mcp_output(output, password))
    downloaded = wait_for_download_after(start_ts)
    if "### Error" in output:
        if downloaded:
            print(f"[OK] Export-list reached and a new refund file was found: {downloaded}")
            return 0
        print("[FAIL] Export page action failed and no new numeric refund xlsx was found in Downloads.")
        return 1
    if not downloaded:
        print("[FAIL] Latest report was completed on export-list, but no new numeric refund xlsx was found in Downloads.")
        return 1
    print(f"[OK] Refund export completed. New file: {downloaded}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
