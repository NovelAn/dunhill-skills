# Dunhill Daily Report Agent Notes

## Automation Memory

- For `Automation ID: dunhill-daily-step-1-2`, always read this file first:
  `/Users/novel/.codex/automations/dunhill-daily-step-1-2/memory.md`
- Do not rely only on `$CODEX_HOME`; in this desktop environment it may be unset in shell commands.
- If the automation memory file is missing, create it at the absolute path above and record the current run.
- Before final response for this automation, append a concise run summary and timestamp to that memory file.

## Dunhill Daily Step 1-2 Boundaries

- When asked to check status, run only `python -u scripts/report_daily_status.py` from this workspace unless the user explicitly asks for another command.
- Do not run `scripts/daily_orchestrator.py` unless the user explicitly asks.
- Do not run workflow Steps 3-5 on macOS. They remain excluded because they require Windows Excel Power Query / MySQL refresh support.
- If a LaunchAgent-started process is already running, observe and report it; do not interrupt it unless the user explicitly asks.

## Playwright Chrome Login Rule

- For QianNiu/Taobao login, use the existing Playwright MCP Chrome Extension path used by the scripts.
- Do not use the Codex Chrome plugin for this automation unless the user explicitly asks.
- If redirected to the QianNiu login page at `loginmyseller.taobao.com` / `havanalogin.taobao.com`, locate `input#fm-login-id[name="fm-login-id"]`.
- Click the account input once to open Chrome's saved account/password popup.
- Select the first saved credential item. Its account label is `dunhill登喜路官方旗舰店:安娜`.
