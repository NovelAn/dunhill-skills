# QuickBI Failure Propagation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make missing DTC QuickBI order data fail Step 2 instead of being reported as a successful daily import.

**Architecture:** Add bounded per-report retries in the QuickBI crawler, propagate exhausted failures through the multiprocessing worker, and add a final required-file gate in Step 2. Keep browser fetching, Excel processing, and database import behavior otherwise unchanged.

**Tech Stack:** Python 3, Playwright, multiprocessing, unittest/pytest.

## Global Constraints

- Do not run the full ingestion workflow during implementation.
- Do not write to the database.
- Preserve macOS exclusion of Steps 3-5.
- Do not modify authentication or credential files.

---

### Task 1: QuickBI report retries and failure propagation

**Files:**
- Modify: `/Users/novel/Projects/data-import/src/data_pipeline/crawler/tasks/qbi.py`
- Modify: `/Users/novel/Projects/data-import/run.py`
- Create: `/Users/novel/Projects/data-import/tests/test_qbi.py`

**Interfaces:**
- Produces: `fetch_report_with_retries(context, url, key, max_attempts=2) -> dict`
- Produces: `main() -> bool`, raising `RuntimeError` when required reports remain missing.

- [ ] Write tests for retry success and exhausted failure.
- [ ] Run the tests and verify they fail because the retry helper is absent.
- [ ] Implement the minimal retry helper and failure return.
- [ ] Re-raise QuickBI worker errors so the child process exits non-zero.
- [ ] Run the tests and verify they pass.

### Task 2: Step 2 required-file completion gate

**Files:**
- Modify: `/Users/novel/.claude/skills/dunhill-skills/dunhill-daily-report/scripts/step2_run_import.py`
- Create: `/Users/novel/.claude/skills/dunhill-skills/dunhill-daily-report/tests/test_step2_quickbi_gate.py`
- Modify: `/Users/novel/.claude/skills/dunhill-skills/dunhill-daily-report/scripts/daily_orchestrator.py`

**Interfaces:**
- Produces: `required_quickbi_files_present(download_path, today_str) -> tuple[bool, list[str]]` through the existing checker.
- Produces: a non-zero Step 2 result when required QuickBI files are missing.

- [ ] Write a test showing a zero subprocess return code cannot override a missing required QuickBI file.
- [ ] Run the test and verify it fails under current behavior.
- [ ] Add the unconditional final file gate.
- [ ] Extend failure classification with a DTC QuickBI-specific action.
- [ ] Run the test and verify it passes.

### Task 3: Verification

**Files:**
- Verify all files modified above.

- [ ] Run the new targeted tests.
- [ ] Run existing status and LaunchAgent tests.
- [ ] Compile modified Python files.
- [ ] Review the diff for accidental workflow execution or unrelated edits.

### Task 4: DTC MCP threshold routing

**Files:**
- Modify: `/Users/novel/.claude/skills/dunhill-skills/dunhill-daily-report/scripts/export_quickbi_chrome.py`
- Create: `/Users/novel/.claude/skills/dunhill-skills/dunhill-daily-report/tests/test_export_quickbi_chrome.py`

**Interfaces:**
- Extends: `QUICKBI_SOURCES` with `dtc_order` and `dtc_refund`.
- Preserves: `rows <= 50` skips MCP export; `rows > 50` creates and downloads a full offline export.

- [ ] Write tests requiring DTC order and refund threshold-routed sources.
- [ ] Run the tests and verify they fail because the DTC sources are absent.
- [ ] Add both DTC source definitions without `force_export`.
- [ ] Run the targeted and full test suites.
