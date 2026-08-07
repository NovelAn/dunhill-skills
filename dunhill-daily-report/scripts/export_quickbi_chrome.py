"""
QuickBI full export supplement through the user's local Chrome login state.

This script complements Step 2's table scraping path. Step 2 can only capture
the rows rendered in the web table preview, while this script simulates the
manual QuickBI "self-service export" flow through Playwright MCP Extension.
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


DOWNLOAD_DIR = os.path.expanduser("~/Downloads")

QUICKBI_SOURCES = {
    "tm_order": {
        "label": "quickbi天猫t01订单源",
        "prefix": "BI_tm_t01_trade_order_line",
        "url": "https://bi.aliyuncs.com/token3rd/offline/view/pc.htm?pageId=1065de5c-5f49-4086-9f3c-3451cb6d8444&accessTicket=b2b373ed-5eed-4aab-accf-2b9b3852994f",
        "wait_seconds": "360",
        "page_load_timeout_ms": 120000,
        "main_content_timeout_ms": 180000,
    },
    "tm_refund_success": {
        "label": "quickbi天猫退款成功退款源",
        "prefix": "BI_tm_trade_refund_info_allsuc_filter",
        "url": "https://bi.aliyuncs.com/token3rd/offline/view/pc.htm?pageId=757770c2-eea6-47c3-831b-5884c64abcf4&accessTicket=1598078c-e313-4d06-a2eb-d1a8b80a6f28",
        "wait_seconds": "180",
    },
    "tm_refund_pending": {
        "label": "quickbi天猫待退款中退款源",
        "prefix": "BI_tm_trade_refund_info_paydate_filter",
        "url": "https://bi.aliyuncs.com/token3rd/offline/view/pc.htm?pageId=3524b197-ccbb-4b51-a6e6-bb8848571ade&accessTicket=38c30a99-5303-44b2-9272-54a1af4dac10",
        "wait_seconds": "180",
    },
    "dtc_order": {
        "label": "quickbi DTC订单源",
        "prefix": "BI_dtc_t01_trade_order_line",
        "url": "https://bi.aliyuncs.com/token3rd/offline/view/pc.htm?pageId=04bdfcf3-c547-42a5-8a43-3a80264ff3d1&accessTicket=f9f48bad-12fa-4cbb-a663-d7d42c450c0a",
        "wait_seconds": "240",
        "page_load_timeout_ms": 120000,
        "main_content_timeout_ms": 180000,
    },
    "dtc_refund": {
        "label": "quickbi DTC退款成功退款源",
        "prefix": "BI_dtc_t01_trade_refund_info_allsuc_filter",
        "url": "https://bi.aliyuncs.com/token3rd/offline/view/pc.htm?pageId=b08a2190-66d7-4004-8ca0-9a6a92857dff&accessTicket=a3db8cff-4532-4f9b-a608-a0269d559bf6",
        "wait_seconds": "180",
    },
}


def find_download_after(prefix: str, start_ts: float) -> Path | None:
    downloads = Path(DOWNLOAD_DIR).expanduser()
    if not downloads.exists():
        return None
    candidates = sorted(
        [
            path
            for path in downloads.glob(f"{prefix}*.xlsx")
            if path.stat().st_mtime >= start_ts
        ],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def wait_for_download(prefix: str, start_ts: float, timeout: int = 180) -> Path | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        path = find_download_after(prefix, start_ts)
        if path:
            return path
        time.sleep(1)
    return find_download_after(prefix, start_ts)


def extract_result_json(output: str) -> dict[str, object] | None:
    match = re.search(r"### Result\s*\n(\{.*?\})\s*\n###", output, re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


QUICKBI_BROWSER_HELPERS = r"""
  const sleep = ms => page.waitForTimeout(ms);

  function normalize(text) {
    return String(text || '').replace(/\s+/g, '').trim();
  }

  async function waitForMainContent(source) {
    const pageLoadTimeout = Number(source.page_load_timeout_ms || 60000);
    const mainContentTimeout = Number(source.main_content_timeout_ms || 90000);
    await page.waitForLoadState('domcontentloaded', { timeout: pageLoadTimeout }).catch(() => null);
    const deadline = Date.now() + mainContentTimeout;
    let last = '';
    while (Date.now() < deadline) {
      const state = await page.evaluate(() => {
        const text = document.body?.innerText || '';
        return {
          url: location.href,
          text: text.slice(0, 1200),
          compact: text.replace(/\s+/g, ''),
        };
      });
      last = state.text;
      const lowerUrl = String(state.url).toLowerCase();
      if (lowerUrl.includes('login')) {
        throw new Error(`${source.label} opened a login page. Please refresh QuickBI login state in Chrome.`);
      }
      if (
        state.compact.includes('查询')
        || state.compact.includes('任务列表')
        || state.compact.includes('取数')
        || state.compact.includes('导出')
      ) {
        return state;
      }
      await sleep(1000);
    }
    throw new Error(`${source.label} main content timeout. Last text: ${last}`);
  }

  async function clickQueryIfPresent() {
    const clicked = await page.evaluate(() => {
      const normalize = text => String(text || '').replace(/\s+/g, '').trim();
      const visible = el => {
        const style = window.getComputedStyle(el);
        return style.visibility !== 'hidden'
          && style.display !== 'none'
          && (el.offsetWidth > 0 || el.offsetHeight > 0 || el.getClientRects().length > 0);
      };
      const candidates = [...document.querySelectorAll('button, a, [role="button"], div, span')]
        .filter(visible)
        .filter(el => {
          const text = normalize(el.textContent);
          const rect = el.getBoundingClientRect();
          return ['查询', '查 询'].includes(text) && rect.width > 20 && rect.height > 16;
        })
        .sort((a, b) => {
          const ar = a.getBoundingClientRect();
          const br = b.getBoundingClientRect();
          return (ar.width * ar.height) - (br.width * br.height);
        });
      if (!candidates[0]) return false;
      candidates[0].click();
      return true;
    }).catch(() => false);
    if (clicked) await sleep(5000);
  }

  async function getPreviewRowCount(source) {
    const rowInfo = await page.evaluate(() => {
      const text = document.body?.innerText || '';
      const compact = text.replace(/\s+/g, '');
      const match = compact.match(/查询结果共(\d+)条/);
      return {
        rows: match ? Number(match[1]) : null,
        previewLimited: compact.includes('最多展示前50条数据') || compact.includes('预览状态'),
        sample: text.slice(-1200),
      };
    });
    if (rowInfo.rows === null) {
      throw new Error(`${source.label} 未读到底部“查询结果共XX条”文本: ${rowInfo.sample}`);
    }
    return rowInfo;
  }

  async function openTaskList(source) {
    const alreadyOpen = await page.evaluate((filePrefix) => {
      const text = document.body?.innerText || '';
      return text.includes(`${filePrefix}_自助取数`) && text.includes('创建于');
    }, source.prefix).catch(() => false);
    if (alreadyOpen) return;

    const clicked = await page.evaluate(() => {
      const normalize = text => String(text || '').replace(/\s+/g, '').trim();
      const visible = el => {
        const style = window.getComputedStyle(el);
        return style.visibility !== 'hidden'
          && style.display !== 'none'
          && (el.offsetWidth > 0 || el.offsetHeight > 0 || el.getClientRects().length > 0);
      };
      const text = document.body?.innerText || '';
      if (text.includes('任务列表') && text.includes('创建取数任务')) return true;
      const panelLeft = window.innerWidth - 520;
      const candidates = [...document.querySelectorAll('button, a, [role="button"], div, span, svg')]
        .filter(visible)
        .map(el => {
          const rect = el.getBoundingClientRect();
          return {
            el,
            text: normalize(el.textContent),
            title: normalize(el.getAttribute('title') || ''),
            aria: normalize(el.getAttribute('aria-label') || ''),
            x: rect.x,
            y: rect.y,
            width: rect.width,
            height: rect.height,
            area: rect.width * rect.height,
          };
        })
        .filter(item => item.width > 8 && item.height > 8)
        .filter(item =>
          item.x > panelLeft
          || item.text.includes('任务列表')
          || item.title.includes('任务列表')
          || item.aria.includes('任务列表')
        );
      let target = candidates.find(item =>
        item.text === '任务列表' || item.title === '任务列表' || item.aria === '任务列表'
      );
      if (!target) {
        target = candidates
          .filter(item => item.text.includes('任务') || item.title.includes('任务') || item.aria.includes('任务'))
          .sort((a, b) => a.area - b.area)[0];
      }
      if (!target) {
        target = candidates
          .filter(item => item.x > window.innerWidth * 0.80 && item.y > 80)
          .sort((a, b) => a.area - b.area)[0];
      }
      if (!target) return false;
      target.el.click();
      return true;
    });
    if (clicked) {
      await sleep(1200);
    }

    const opened = await page.evaluate((filePrefix) => {
      const text = document.body?.innerText || '';
      return text.includes(`${filePrefix}_自助取数`) && text.includes('创建于');
    }, source.prefix).catch(() => false);
    if (opened) return;

    const size = await page.evaluate(() => ({ width: window.innerWidth, height: window.innerHeight }));
    const attempts = [
      { x: size.width - 24, y: 203 },
      { x: size.width - 24, y: 104 },
      { x: size.width - 24, y: 180 },
    ];
    for (const point of attempts) {
      await page.mouse.click(point.x, point.y);
      await sleep(1500);
      const ok = await page.evaluate((filePrefix) => {
        const text = document.body?.innerText || '';
        return text.includes(`${filePrefix}_自助取数`) && text.includes('创建于');
      }, source.prefix).catch(() => false);
      if (ok) return;
    }
    throw new Error('未打开右侧任务列表面板');
  }

  async function clickTaskListPlus(source) {
    const alreadyCreating = await page.evaluate(() => {
      const text = document.body?.innerText || '';
      return text.includes('纯数据 Excel') && text.includes('取消') && text.includes('确定');
    }).catch(() => false);
    if (alreadyCreating) {
      return { text: 'existing-create-panel' };
    }

    const hit = await page.evaluate(() => {
      const normalize = text => String(text || '').replace(/\s+/g, '').trim();
      const visible = el => {
        const style = window.getComputedStyle(el);
        return style.visibility !== 'hidden'
          && style.display !== 'none'
          && (el.offsetWidth > 0 || el.offsetHeight > 0 || el.getClientRects().length > 0);
      };
      const panelLeft = window.innerWidth - 520;
      const candidates = [...document.querySelectorAll('button, a, [role="button"], div, span, svg')]
        .filter(visible)
        .map(el => {
          const rect = el.getBoundingClientRect();
          return {
            text: normalize(el.textContent),
            title: normalize(el.getAttribute('title') || ''),
            aria: normalize(el.getAttribute('aria-label') || ''),
            x: rect.x,
            y: rect.y,
            width: rect.width,
            height: rect.height,
            area: rect.width * rect.height,
          };
        })
        .filter(item => item.x > panelLeft && item.width > 8 && item.height > 8);
      const target = candidates
        .filter(item =>
          ['+', '＋'].includes(item.text)
          || item.text.includes('创建取数任务')
          || item.title.includes('创建')
          || item.title.includes('新建')
          || item.aria.includes('创建')
          || item.aria.includes('新建')
        )
        .sort((a, b) => a.y - b.y || a.area - b.area)[0];
      if (!target) return null;
      return { x: target.x + target.width / 2, y: target.y + target.height / 2, text: target.text || target.title || target.aria };
    });
    if (!hit) throw new Error(`${source.label} 已打开任务列表，但没有找到 + 创建取数任务按钮`);
    await page.mouse.click(hit.x, hit.y);
    await sleep(3000);
    return hit;
  }

  async function clickConfirmCreate(source) {
    const result = await page.evaluate(() => {
      const normalize = text => String(text || '').replace(/\s+/g, '').trim();
      const visible = el => {
        const style = window.getComputedStyle(el);
        return style.visibility !== 'hidden'
          && style.display !== 'none'
          && (el.offsetWidth > 0 || el.offsetHeight > 0 || el.getClientRects().length > 0);
      };
      const candidates = [...document.querySelectorAll('button, a, [role="button"], div, span')]
        .filter(visible)
        .map(el => {
          const rect = el.getBoundingClientRect();
          return {
            el,
            text: normalize(el.textContent),
            x: rect.x,
            y: rect.y,
            width: rect.width,
            height: rect.height,
            area: rect.width * rect.height,
          };
        })
        .filter(item => item.width > 20 && item.height > 16);
      const target = candidates
        .filter(item => ['确定', '确认', '提交', '创建', '开始取数'].includes(item.text))
        .sort((a, b) => b.y - a.y || a.area - b.area)[0];
      if (!target) {
        return {
          ok: false,
          visible: candidates.map(item => item.text).filter(Boolean).slice(0, 80),
        };
      }
      target.el.click();
      return { ok: true, text: target.text };
    }).catch(error => ({ ok: false, error: String(error.message || error) }));
    if (!result.ok) throw new Error(`${source.label} 创建取数任务弹层未找到“确定”: ${JSON.stringify(result)}`);
    await sleep(3000);
    return result;
  }

  async function inspectReadyDownload(source, clickIt = false) {
    const result = await page.evaluate(({ filePrefix, minCreatedEpochMs }) => {
      const normalize = text => String(text || '').replace(/\s+/g, '').trim();
      const parseTaskCreatedAt = text => {
        const compact = normalize(text);
        const match = compact.match(/创建于(\d{4})\/(\d{2})\/(\d{2})(\d{2}):(\d{2}):(\d{2})/);
        if (!match) return null;
        const [, year, month, day, hour, minute, second] = match;
        return new Date(
          Number(year),
          Number(month) - 1,
          Number(day),
          Number(hour),
          Number(minute),
          Number(second)
        ).getTime();
      };
      const visible = el => {
        const style = window.getComputedStyle(el);
        return style.visibility !== 'hidden'
          && style.display !== 'none'
          && (el.offsetWidth > 0 || el.offsetHeight > 0 || el.getClientRects().length > 0);
      };
      const parseRgb = value => {
        const match = String(value || '').match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
        if (!match) return null;
        return [Number(match[1]), Number(match[2]), Number(match[3])];
      };
      const isGreenValue = value => {
        const rgb = parseRgb(value);
        if (!rgb) return false;
        const [r, g, b] = rgb;
        return g >= 120 && r <= 120 && b <= 160 && g > r + 30 && g > b + 20;
      };
      const panelLeft = window.innerWidth - 540;
      const elements = [...document.querySelectorAll('button, a, [role="button"], div, span, svg, path, i')]
        .filter(visible)
        .map(el => {
          const rect = el.getBoundingClientRect();
          const style = window.getComputedStyle(el);
          const combinedText = normalize(
            `${el.textContent || ''} ${el.getAttribute('title') || ''} ${el.getAttribute('aria-label') || ''} ${el.className || ''}`
          );
          return {
            tag: String(el.tagName || ''),
            cls: normalize(el.className || ''),
            text: normalize(el.textContent),
            title: normalize(el.getAttribute('title') || ''),
            aria: normalize(el.getAttribute('aria-label') || ''),
            combinedText,
            x: rect.x,
            y: rect.y,
            width: rect.width,
            height: rect.height,
            area: rect.width * rect.height,
            green: [style.color, style.backgroundColor, style.borderColor, style.fill, style.stroke].some(isGreenValue),
            clickable: ['BUTTON', 'A'].includes(String(el.tagName || ''))
              || el.getAttribute('role') === 'button'
              || style.cursor === 'pointer'
              || el.onclick !== null,
          };
        })
        .filter(item => item.x > panelLeft && item.width > 4 && item.height > 4);
      const today = new Date();
      const todayText = `${today.getFullYear()}/${String(today.getMonth() + 1).padStart(2, '0')}/${String(today.getDate()).padStart(2, '0')}`;
      const rows = elements
        .filter(item =>
          item.text.includes(filePrefix)
          && item.text.includes('创建于')
          && item.width > 220
          && item.height >= 40
          && item.height <= 180
        )
        .map(row => {
          const createdAt = parseTaskCreatedAt(row.text);
          const rowElements = elements.filter(item =>
            item.x >= row.x - 6
            && item.x <= row.x + row.width + 6
            && item.y >= row.y - 8
            && item.y <= row.y + row.height + 8
          );
          const hasGreen = rowElements.some(item =>
            item.green
            && item.width <= 36
            && item.height <= 36
          );
          const controls = rowElements
            .filter(item =>
              item.x > row.x + row.width * 0.80
              && item.width <= 56
              && item.height <= 56
              && item.clickable
              && !item.green
              && !/^\d+$/.test(item.text)
              && (
                item.combinedText.includes('下载')
                || item.combinedText.includes('download')
                || item.cls.includes('download')
                || item.x > row.x + row.width * 0.92
              )
            )
            .sort((a, b) => {
              const aDownload = (a.combinedText.includes('下载') || a.combinedText.includes('download') || a.cls.includes('download')) ? 0 : 1;
              const bDownload = (b.combinedText.includes('下载') || b.combinedText.includes('download') || b.cls.includes('download')) ? 0 : 1;
              return aDownload - bDownload || b.x - a.x || a.area - b.area;
            });
          return { ...row, createdAt, hasGreen, controls };
        })
        .filter(row => row.createdAt !== null)
        .filter(row => !minCreatedEpochMs || row.createdAt >= minCreatedEpochMs)
        .sort((a, b) => a.y - b.y || a.area - b.area);
      const todayRows = rows.filter(row => row.text.includes(todayText));
      const row = todayRows.find(item => item.hasGreen && item.controls.length) || rows.find(item => item.hasGreen && item.controls.length);
      if (!row) {
        return {
          ok: false,
          reason: todayRows.length ? 'current-run-task-not-ready' : 'current-run-task-not-found',
          minCreatedEpochMs,
          visible: elements.map(item => item.text || item.title || item.aria).filter(Boolean).slice(0, 80),
        };
      }
      const control = row.controls[0];
      return {
        ok: true,
        x: control.x + control.width / 2,
        y: control.y + control.height / 2,
        row: row.text.slice(0, 160),
        createdAt: row.createdAt,
        control: control.text || control.title || control.aria || control.cls || 'right-side-icon',
      };
    }, {
      filePrefix: source.prefix,
      minCreatedEpochMs: Number(source.min_task_created_epoch_ms || 0),
    });
    if (result.ok && clickIt) {
      await page.mouse.click(result.x, result.y);
      await sleep(5000);
    }
    return result;
  }

  async function createTaskFlow(source) {
    await page.goto(source.url, { waitUntil: 'domcontentloaded', timeout: Number(source.page_load_timeout_ms || 60000) });
    await waitForMainContent(source);
    await clickQueryIfPresent();
    const rowInfo = await getPreviewRowCount(source);
    if (!source.force_export && rowInfo.rows <= 50) {
      return {
        ok: true,
        source: source.label,
        prefix: source.prefix,
        skipped: true,
        rows: rowInfo.rows,
        reason: 'preview row count <= 50; Step 2 crawler can capture it completely',
      };
    }
    await openTaskList(source);
    const ready = await inspectReadyDownload(source, false);
    if (ready.ok) {
      return {
        ok: true,
        source: source.label,
        prefix: source.prefix,
        skipped: false,
        rows: rowInfo.rows,
        reusedExisting: true,
        ready: ready.row,
        minTaskCreatedEpochMs: Number(source.min_task_created_epoch_ms || 0),
      };
    }
    await clickTaskListPlus(source);
    const confirmed = await clickConfirmCreate(source);
    return {
      ok: true,
      source: source.label,
      prefix: source.prefix,
      skipped: false,
      rows: rowInfo.rows,
      reusedExisting: false,
      taskCreated: true,
      confirmed,
      minTaskCreatedEpochMs: Number(source.min_task_created_epoch_ms || 0),
    };
  }

  async function downloadLatestTaskFlow(source) {
    await page.goto(source.url, { waitUntil: 'domcontentloaded', timeout: Number(source.page_load_timeout_ms || 60000) });
    await waitForMainContent(source);
    await page.reload({ waitUntil: 'domcontentloaded', timeout: Number(source.page_load_timeout_ms || 60000) }).catch(() => null);
    await waitForMainContent(source);
    await openTaskList(source);
    const clicked = await inspectReadyDownload(source, true);
    if (!clicked.ok) {
      throw new Error(`${source.label} 最新任务还没有出现绿色成功状态和下载按钮: ${JSON.stringify(clicked)}`);
    }
    return {
      ok: true,
      source: source.label,
      prefix: source.prefix,
      clicked: true,
      row: clicked.row,
      control: clicked.control,
    };
  }
"""


def quickbi_action_code(source: dict[str, object], action: str) -> str:
    source_json = json.dumps(source, ensure_ascii=False)
    flow = "createTaskFlow" if action == "create" else "downloadLatestTaskFlow"
    return (
        "async (page) => {\n"
        f"  const source = {source_json};\n"
        f"{QUICKBI_BROWSER_HELPERS}\n"
        f"  return await {flow}(source);\n"
        "}\n"
    )


def run_chrome_action(
    key: str,
    action: str,
    timeout: int,
    source_overrides: dict[str, object] | None = None,
) -> dict[str, object] | None:
    source: dict[str, object] = {**QUICKBI_SOURCES[key], **(source_overrides or {})}
    try:
        output = run_in_local_chrome(
            quickbi_action_code(source, action),
            timeout=timeout,
            client_name=f"dunhill-quickbi-{action}-{key}",
        )
    except Exception as exc:
        print(f"[FAIL] {source['label']} {action} 阶段 MCP 执行失败: {exc}")
        return None

    result = extract_result_json(output)
    if result:
        print(f"[OK] {source['label']} {action}: {json.dumps(result, ensure_ascii=False)}")
        return result
    if "### Error" in output:
        error = output.split("### Error", 1)[-1].split("###", 1)[0].strip()
        print(f"[FAIL] {source['label']} {action} 页面动作失败: {error}")
        return None
    print(f"[INFO] {source['label']} {action} 已返回，但未解析到结构化结果。")
    return None


def wait_until(target_ts: float, label: str) -> None:
    remaining = max(0, int(target_ts - time.time()))
    if remaining <= 0:
        return
    print(f"[WAIT] {label} 后台取数运行中，等待 {remaining}s 后刷新任务列表下载...")
    while remaining > 0:
        step = min(30, remaining)
        time.sleep(step)
        remaining = max(0, int(target_ts - time.time()))


def run_batch(source_keys: list[str], timeout: int) -> bool:
    print("\n[PHASE 1] 先发起所有需要补充的 QuickBI 取数任务", flush=True)
    created: dict[str, dict[str, object]] = {}
    ready_at: dict[str, float] = {}
    task_started_at: dict[str, float] = {}
    failed: list[str] = []

    for key in source_keys:
        source = QUICKBI_SOURCES[key]
        print("\n" + "-" * 60)
        print(f"QuickBI 补充源: {source['label']}")
        print(f"文件前缀: {source['prefix']}")
        print("-" * 60)
        start = time.time()
        task_started_at[key] = start
        result = run_chrome_action(
            key,
            "create",
            timeout=timeout,
            source_overrides={"min_task_created_epoch_ms": int(start * 1000)},
        )
        if not result or not result.get("ok"):
            failed.append(key)
            continue
        if result.get("skipped"):
            print(f"[SKIP] {source['label']} 行数 {result.get('rows')} <= 50，步骤2爬虫可完整获取。")
            continue
        created[key] = result
        if result.get("reusedExisting"):
            ready_at[key] = time.time()
        else:
            ready_at[key] = start + int(source.get("wait_seconds", "240"))

    if failed:
        print(f"\n[FAIL] 创建取数任务失败: {', '.join(failed)}")

    if not created:
        return not failed

    print("\n[PHASE 2] 按任务预计完成时间刷新侧栏，点击最新绿色任务的下载按钮", flush=True)
    download_failed: list[str] = []
    for key in sorted(created, key=lambda item: ready_at[item]):
        source = QUICKBI_SOURCES[key]
        wait_until(ready_at[key], source["label"])

        downloaded: Path | None = None
        last_result: dict[str, object] | None = None
        for attempt in range(1, 7):
            click_started_at = time.time()
            last_result = run_chrome_action(
                key,
                "download",
                timeout=timeout,
                source_overrides={
                    "min_task_created_epoch_ms": int(task_started_at[key] * 1000),
                },
            )
            if last_result and last_result.get("ok"):
                downloaded = wait_for_download(source["prefix"], click_started_at, timeout=180)
                if downloaded:
                    break
                print(f"[WAIT] {source['label']} 已点击下载，但还没看到新增文件，继续等待/重试。")
            else:
                print(f"[WAIT] {source['label']} 暂未就绪，30s 后刷新侧栏重试 ({attempt}/6)。")
            time.sleep(30)

        if not downloaded:
            print(f"[FAIL] {source['label']} 未发现本轮新增文件: {source['prefix']}*.xlsx")
            if last_result:
                print(f"[INFO] 最后一次页面结果: {json.dumps(last_result, ensure_ascii=False)}")
            download_failed.append(key)
            continue

        stat = downloaded.stat()
        print(f"[OK] {source['label']} 下载完成: {downloaded} ({stat.st_size} bytes)")

    failed.extend(download_failed)
    if failed:
        print(f"\n[FAIL] QuickBI 补充下载失败: {', '.join(failed)}")
        return False
    print("\n[OK] QuickBI 补充下载全部完成")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="QuickBI full export supplement via Playwright MCP Extension")
    parser.add_argument(
        "--sources",
        nargs="+",
        choices=["all", *QUICKBI_SOURCES.keys()],
        default=["all"],
        help="要下载的 QuickBI 补充源",
    )
    parser.add_argument("--timeout", type=int, default=720)
    args = parser.parse_args()
    load_env()

    source_keys = list(QUICKBI_SOURCES) if "all" in args.sources else args.sources
    print("QuickBI 补充源导出 (Playwright MCP Extension)", flush=True)
    print(f"下载目录: {DOWNLOAD_DIR}", flush=True)
    print(f"源数量: {len(source_keys)}", flush=True)

    return 0 if run_batch(source_keys, timeout=args.timeout) else 1


if __name__ == "__main__":
    sys.exit(main())
