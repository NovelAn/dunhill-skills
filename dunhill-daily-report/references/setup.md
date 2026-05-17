# Dunhill Daily Report Setup and Configuration

## Installation

### Prerequisites

- **Windows OS** with Excel 2016+ and Outlook 2016+ installed
- **Python 3.8+**

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
  browser_headless: false  # Show browser window
```

## Login Solutions

### Option 1: Browser Session Persistence (Recommended)

**Advantages**:
- Scan QR code once, login lasts 7-30 days
- Fully automated after first login
- Uses official Taobao QR code login
- Stable and reliable

**Setup** (First time only):

1. Run the script:
   ```bash
   python scripts/step1_collect_data.py
   ```

2. Browser opens automatically

3. Use Taobao/QianNiu mobile app to scan QR code

4. Login session saved to `.browser_profile/` directory

**Subsequent runs**:
- Session automatically restored
- No login required for 7-30 days
- When session expires, repeat the setup process

**Configuration** (in `dunhill-config.yaml`):
```yaml
settings:
  browser_user_data_dir: "${PLAYWRIGHT_PROFILES_DIR}/dunhill-daily-report"
```

**Security Note**: The `.browser_profile` directory contains login credentials. Never commit it to version control or share it. It's already in `.gitignore`.

### Option 2: Chrome Remote Debugging (CDP)

**Advantages**:
- Use your normal Chrome browser
- Login persists as long as Chrome is open
- Easy to debug and manually assist when needed

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
| Session Persistence | High | High | Easy | **Daily automated use** |
| Chrome CDP | Very High | Very High | Medium | **Users comfortable with tech** |
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
# Test Step 1 (Data collection)
python scripts/step1_collect_data.py

# Test Step 2 (Import script)
python scripts/step2_run_import.py

# Test Step 3 (PFS report)
python scripts/step3_pfs_report.py

# Test Step 4 (DTC report)
python scripts/step4_dtc_report.py

# Test Step 5 (Email drafts)
python scripts/step5_email_drafts.py
```

Verify outputs in configured directories before running the full workflow.
