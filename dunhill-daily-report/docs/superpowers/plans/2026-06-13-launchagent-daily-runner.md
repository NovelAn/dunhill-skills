# Dunhill Daily LaunchAgent Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Step 1-2 execution into the logged-in macOS GUI launchd domain while retaining Codex as a read-only status reporter.

**Architecture:** A user LaunchAgent invokes a lock-aware shell wrapper that runs the existing orchestrator. A Python management command renders and manages the plist, while a separate reporter reads run artifacts without invoking Chrome or workflow code.

**Tech Stack:** Python 3, unittest, zsh, macOS launchd/launchctl, plistlib

---

### Task 1: LaunchAgent rendering

**Files:**
- Create: `launchd/com.dunhill.daily-report.plist.template`
- Create: `scripts/manage_launchagent.py`
- Create: `tests/test_manage_launchagent.py`

- [x] Write tests asserting label, 09:10 calendar schedule, Aqua session, wrapper path, and log paths.
- [x] Run `python -m unittest tests/test_manage_launchagent.py` and verify missing implementation failures.
- [x] Implement template rendering and atomic user plist installation helpers with `plistlib` validation.
- [x] Re-run the focused tests and verify they pass.

### Task 2: Lock-aware GUI runner

**Files:**
- Create: `scripts/launchagent_runner.sh`
- Modify: `tests/test_manage_launchagent.py`

- [x] Add a failing structural test requiring workspace `cd`, non-blocking atomic lock, cleanup trap, and exact orchestrator command.
- [x] Run the focused test and verify it fails.
- [x] Implement the minimal wrapper with stable launchd logs and inherited GUI environment.
- [x] Re-run the focused tests and verify they pass.

### Task 3: Read-only Codex reporter

**Files:**
- Create: `scripts/report_daily_status.py`
- Create: `tests/test_report_daily_status.py`

- [x] Write failing tests for missing, failed, and successful state including notification and needs-action extraction.
- [x] Run `python -m unittest tests/test_report_daily_status.py` and verify missing implementation failures.
- [x] Implement a JSON report that only reads state, summary, and LaunchAgent logs.
- [x] Re-run the focused tests and verify they pass.

### Task 4: Operations and documentation

**Files:**
- Modify: `references/setup.md`
- Modify: `references/troubleshooting.md`
- Modify: `SKILL.md`

- [x] Document install, status, kickstart, uninstall, and the read-only Codex command.
- [x] Run the full unit suite and Python compile checks.
- [x] Render and validate the plist with `plutil -lint` without installing it.
- [ ] Install only after explicit approval for the user LaunchAgent change, then verify with `launchctl print gui/$UID/com.dunhill.daily-report`.
