# Dunhill Daily Report Setup and Configuration

## Installation

### Prerequisites

- **macOS or Windows** for Step 1 and Step 2 data collection/import
- **Windows OS** with Excel 2016+ and Outlook 2016+ for Step 3-5 report refresh and email draft automation
- **Python 3.8+**
- **Chrome Playwright Extension** for Step 1 and Taobao cookie refresh

> macOS can run the browser automation and database import steps, but Mac Excel cannot refresh the Power Query / MySQL-backed PFS and DTC workbooks. Run Steps 3-5 on Windows Excel, a remote Windows host, or a manual report-refresh workflow.

### Install Python Dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### Environment Variables

Set Taobao password as environment variable (recommended for security):

**PowerShell**:
```powershell
$env:TAOBAO_PASSWORD="your_actual_password"
```

**CMD**:
```cmd
set TAOBAO_PASSWORD=your_actual_password
```

**Permanent (PowerShell)**:
```powershell
[System.Environment]::SetEnvironmentVariable('TAOBAO_PASSWORD', 'your_actual_password', 'User')
```

**Permanent (CMD)**:
```cmd
setx TAOBAO_PASSWORD "your_actual_password"
```

## Configuration

Edit `config/dunhill-config.yaml` to customize paths and settings.

### Required Configuration

```yaml
credentials:
  taobao_username: "your_username"
  taobao_password: "${TAOBAO_PASSWORD}"  # Uses environment variable

paths:
  # Excel template files - paths resolved from .env
  pfs_excel: "${DUNHILL_DATA_DIR}/daily_report/pfs/dunhill pfs daily report.xlsx"
  dtc_excel: "${DUNHILL_DATA_DIR}/daily_report/dtc/dunhill OFS&WBTQ daily sales report.xlsx"

  # Output directories - paths resolved from .env
  pfs_snapfile_dir: "${DUNHILL_DATA_DIR}/daily_report/pfs/daily_report_snapfile"
  dtc_snapfile_dir: "${DUNHILL_DATA_DIR}/daily_report/dtc/daily_report_snapfile"
  pfs_snapshot_dir: "${DUNHILL_DATA_DIR}/daily_report/pfs/daily_report_snapshot"
  dtc_snapshot_dir: "${DUNHILL_DATA_DIR}/daily_report/dtc/daily_report_snapshot"

  # Download directory - resolved from .env
  download_dir: "${DOWNLOAD_DIR}"
```

### Optional Configuration

```yaml
settings:
  excel_wait_timeout: 300  # Excel refresh timeout (seconds)
  excel_visible: true      # Show Excel window (useful for debugging)
  screenshot_dpi: 96       # Screenshot resolution
  script_check_interval: 5 # Step 2 output polling interval
  script_max_wait: 1800    # Step 2 maximum wait time
```

## Login Solutions

### Option 1: Playwright MCP Extension + MCP Bridge (Recommended)

Use this path for all model runtimes, including GPT/OpenAI/Codex, MiniMax, DeepSeek, GLM, and Claude.

**Setup**:

1. Install Chrome Playwright Extension.
2. Log in to Taobao and Taobao Live Platform in your normal Chrome.
3. Open the extension status page and copy the token shown after `PLAYWRIGHT_MCP_EXTENSION_TOKEN=`.
4. Set it in the current shell:
   ```bash
   export PLAYWRIGHT_MCP_EXTENSION_TOKEN="your_token"
   ```
5. Run Step 1:
   ```bash
   python -u scripts/step1_collect_data.py
   ```

`step1_collect_data.py` runs `step1_chrome_bridge.py`. The bridge navigates to refund/live pages itself and executes `export_refund_chrome.py`, `export_live.py`, and the QuickBI complete-file supplement `export_quickbi_chrome.py` through the Playwright MCP Extension.

The QuickBI supplement checks the three TM QuickBI pages first. If a page shows `查询结果共XX条` with `XX > 50`, it creates a fresh self-service export task, waits for it to finish, then downloads only the task created after the current run started. If `XX <= 50`, it skips that source because Step 2 can capture it completely.

`export_refund.py` and the Codex Extension runner have been removed from the main skill. Do not use Codex Extension / browser-use computer-use clicks for Step 1 until that path is reliable on QianNiu/Taobao pages.

### Step 2 Taobao Cookie Refresh

Step 2 pre-checks `.taobao.com` cookies before running the import pipeline.

- If Taobao/QianNiu cookies are still valid, Step 2 runs normally.
- If they are expired, Step 2 first runs `/Users/novel/projects/data-import/scripts/login/taobao_login_mcp.py`.
- The MCP login script connects to normal Chrome through Playwright MCP Extension and syncs the latest Taobao/QianNiu cookies into `~/auth.json`.
- This uses the same Chrome login state established by Step 1, so it usually avoids QR-code login.
- QuickBI, SYCM, and JYCM cookies are lower-frequency auth files and are preserved during the merge.
- If MCP sync fails, Step 2 falls back to the legacy interactive login flow and auto-selects option `1` for 千牛/淘宝.

### Step 2 Alimama Auth Refresh

Alimama auth is short-lived and often needs a daily refresh.

Recommended daily Step 2 command:
```bash
python -u scripts/step2_run_import.py --refresh-alimama-auth-first
```

- The flag runs `python manage.py alimama --refresh-auth` before the Alimama crawler.
- The auth refresh connects to normal Chrome through Playwright MCP Extension.
- It captures the page/request `csrfId` and saves it to `~/alimama_config.json`.
- It saves matching `.alimama.com` cookies to `~/alimama_cookies.json`.
- Step 2 then runs `python manage.py alimama` as a daily data import task.
- If the flag is omitted, the Alimama crawler still refreshes auth once after detecting CSRF failure.
- Use `--skip-alimama` only when the Alimama platform is unavailable and the rest of Step 2 must continue.

## Daily Scheduling

On macOS, do not schedule the Step 1-2 orchestrator inside Codex Automation.
Codex runs commands in a seatbelt sandbox that cannot reliably access the GUI
session, AppleScript services, process inspection, or Playwright MCP loopback
listeners. Install the user LaunchAgent instead:

```bash
python -u scripts/manage_launchagent.py install
python -u scripts/manage_launchagent.py status
```

The install command also updates the existing
`dunhill-daily-step-1-2` Codex Automation to run at 09:35 and execute only
`scripts/report_daily_status.py`.

The LaunchAgent runs this command at 09:10 in the logged-in Aqua session:

```bash
python -u scripts/daily_orchestrator.py
```

The orchestrator:
- Runs Step 1 and Step 2 in order.
- Refreshes Alimama auth before Step 2 by default.
- Writes per-run state to `runs/YYYY-MM-DD/state.json`.
- Writes step logs to `runs/YYYY-MM-DD/logs/`.
- Uses `caffeinate -dimsu` on macOS while the run is active.
- Sends a Feishu/Lark success notification to `数据更新提醒` after Step 1 and Step 2 both succeed.
- Stops after Step 2 because Steps 3-5 require Windows Excel.

Keep Codex Automation as a later read-only monitor. Its only project command
must be:

```bash
python -u scripts/report_daily_status.py
```

Recommended timing is 09:35 Asia/Shanghai so the LaunchAgent normally has time
to finish. The reporter reads state and logs; it never starts Step 1 or Step 2.

LaunchAgent operations:

```bash
python -u scripts/manage_launchagent.py trigger
python -u scripts/manage_launchagent.py status
python -u scripts/manage_launchagent.py uninstall
```

### Lark Success Notification

Success notifications are configured in `config/dunhill-config.yaml` under `notifications.lark`.

Current behavior:
- Sends as bot identity.
- Sends to group `数据更新提醒`.
- Mentions 徐加琪 and 唐玉霞.
- Message says only `dunhill的日报和订单相关数据已经更新`, without script names, step numbers, state files, or logs.
- Uses an idempotency key per run date to avoid duplicate sends.

Debug options:
```bash
python -u scripts/daily_orchestrator.py --notify-dry-run
python -u scripts/daily_orchestrator.py --no-notify
```

### Option 2: Chrome Remote Debugging (Legacy CDP Fallback)

**Setup**:

1. **Start Chrome with remote debugging** (do this once per day):
   ```bash
   # Method A: Use the provided script
   start_chrome_debug.bat

   # Method B: Manual command
   chrome.exe --remote-debugging-port=9222
   ```

2. **Login to Taobao** (first time or when session expires):
   - In the Chrome browser, navigate to Taobao seller platform
   - Use Taobao mobile app to scan QR code
   - Confirm login

3. **Run CDP version of data collection script**:
   ```bash
   python scripts/step1_collect_data_cdp.py
   ```

4. **Keep Chrome open** for the day to avoid re-login

**Troubleshooting CDP**:

If connection fails:
- Verify Chrome is running with `--remote-debugging-port=9222`
- Check if port 9222 is available: `netstat -ano | findstr :9222`
- Make sure you're logged into Taobao in Chrome

### Option 3: Manual Download (Fallback)

If both automated methods fail, you can manually download files and proceed with the remaining steps.

**Manual Download Steps**:

1. Login to Taobao seller platform
2. Navigate to Refund List page
3. Export as Excel
4. Download Live Platform core indicators
5. Download transaction order details

Then continue with Step 2 and beyond.

### Choosing a Login Method

| Method | Automation | Stability | Setup Difficulty | Recommended For |
|--------|-----------|-----------|------------------|-----------------|
| Script + MCP Extension | High | Medium | Medium | **Daily Step 1 use** |
| Chrome CDP legacy fallback | Very High | Medium | Medium | **Fallback only** |
| Manual Download | Low | Very High | None | **Backup/fallback** |

## Email Templates

Place `.msg` template files in `assets/email_templates/`:

- `pfs_email_template.msg` - PFS daily report email template
- `dtc_email_template.msg` - DTC daily report email template

**Template placeholders**:
- Use `{date}` in subject or body
- Will be replaced with yesterday's date (YYYY-MM-DD format)

**Recipients configuration** (in `dunhill-config.yaml`):

```yaml
email:
  pfs_to:
    - "Recipient Name <email@example.com>"
  pfs_cc:
    - "CC Recipient <cc@example.com>"
```

If templates are not provided, the script will create basic email drafts with standard format.

## Testing Your Setup

After installation, test each step individually:

```bash
# Test Step 1 script flow
python -u scripts/step1_collect_data.py

# Test Step 2 (Import script)
python -u scripts/step2_run_import.py

# Test Step 3 (PFS report)
python -u scripts/step3_pfs_report.py

# Test Step 4 (DTC report)
python -u scripts/step4_dtc_report.py

# Test Step 5 (Email drafts)
python -u scripts/step5_email_drafts.py
```

Verify outputs in configured directories before running the full workflow.
