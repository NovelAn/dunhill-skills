---
name: dunhill-daily-report
description: "Automated Dunhill daily report workflow for e-commerce operations. Use this skill when: (1) Collecting data from Taobao seller platform and Live Platform, (2) Running data import Python scripts, (3) Generating PFS and DTC Excel daily reports with automatic refresh and screenshots, (4) Creating Outlook email drafts with report attachments. Supports both full end-to-end workflow execution and individual step execution for testing."
---

# Dunhill Daily Report Automation

Automated workflow for generating Dunhill daily reports from Taobao e-commerce data.

## ⚠️ CRITICAL EXECUTION REQUIREMENTS

**MUST EXECUTE STEPS SEQUENTIALLY WITH STRICT DEPENDENCY CHECKING:**

1. **Step 2 MUST complete successfully BEFORE Steps 3, 4, or 5**
   - Step 2 runs `run.py` which downloads all data sources and uploads them to the database
   - You MUST wait for Step 2 to return exit code 0 (success) before proceeding
   - Do NOT start Steps 3 or 4 until Step 2 shows: `[OK] 步骤2执行成功！可以继续执行后续步骤。`
   - Steps 3 and 4 depend on this data being completely loaded into the database
   - If Steps 3 or 4 run before Step 2 completes, the Excel refresh will fail or show incomplete data

2. **Execution Order (ENFORCED):**
   ```
   Step 1 (optional) → Step 2 → Step 3 → Step 4 → Step 5
                         ↑
                    MUST WAIT HERE
                    Until run.py exits
                    with code 0
   ```

3. **How to Verify Step 2 Completion:**
   - Look for: `[OK] 步骤2执行成功！可以继续执行后续步骤。`
   - Check exit code is 0 (not 1)
   - Verify all tasks show as completed in summary
   - Only then proceed to Step 3

4. **If Step 2 Fails:**
   - DO NOT proceed to Steps 3, 4, or 5
   - Report the failure to the user
   - Show the error messages from Step 2
   - Ask user if they want to retry Step 2

## Quick Start

**For first-time setup**, see [Setup Guide](references/setup.md) for installation and configuration.

**For troubleshooting issues**, see [Troubleshooting Guide](references/troubleshooting.md).

## Workflow Steps

Execute all steps sequentially for complete daily report generation, or run individual steps for testing.

### Step 1: Collect Data from Web Platforms

Automates data collection from Taobao platforms:
- Login to Taobao seller platform (session persists for 7-30 days after first login)
- Export refund list as Excel
- Download live streaming core indicators
- Download transaction order details (payment & confirmation time)

**Script**: `scripts/step1_collect_data.py`

**Alternative** (Chrome CDP): `scripts/step1_collect_data_cdp.py`

### Step 2: Run Data Import Scripts ⚠️ CRITICAL STEP

**PREREQUISITE**: None
**CRITICAL**: This step MUST complete successfully before Steps 3, 4, or 5 can execute.

Executes internal data import Python scripts:
- **Cookie health check**: Pre-checks `.taobao.com` cookies before launching `run.py`. If expired, prompts user to run `python scripts/login/taobao_login.py` and stops.
- Runs `${ETL_PIPELINES_DIR}/run.py`
- Downloads all data sources (QuickBI, SYCM, JYCM, etc.)
- Uploads all data to database
- Runs stored procedure `UpdateMaskedBuyerNicknames` to auto-decrypt historical buyer nicknames via SQL (reduces crawler request volume and avoids Alibaba anti-bot warnings)
- Runs order crawlers (nick + fq) for remaining undecrypted orders
- Runs buyer type updates (PFS + DTC)
- Monitors output for QuickBI table warnings (>50 rows)
- Prompts for manual download if needed
- Re-runs upload script if manual downloads occurred

**Script**: `scripts/step2_run_import.py`

**SUCCESS INDICATORS**:
- Exit code: 0
- Message: `[OK] 步骤2执行成功！可以继续执行后续步骤。`
- All data sources uploaded to database

**DO NOT PROCEED TO STEP 3 UNTIL**:
- Step 2 script has exited (process terminated)
- Exit code is 0 (success)
- Success message is displayed

**When QuickBI exceeds 50 rows**: Script will prompt you to download manually from QuickBI URL, then automatically run upload when ready.

### Step 3: Generate PFS Report ⚠️ DEPENDS ON STEP 2

**PREREQUISITE**: Step 2 MUST complete successfully first
**DEPENDENCY**: Requires all data from Step 2 to be loaded into database

Automates PFS Excel report generation:
- Opens `dunhill pfs daily report.xlsx`
- Refreshes all data connections (2-3 minutes)
- Copies "Daily" sheet as values to new workbook
- Saves snapshot to snapfile directory
- Takes screenshots of key ranges (B8:A37, Daily Highlights if data exists)
- Saves JPEGs with yesterday's date (YYYY-MM-DD format)

**Script**: `scripts/step3_pfs_report.py`

**Output**:
- `daily_report_snapfile/dunhill pfs daily report_YYYY-MM-DD.xlsx`
- `daily_report_snapshot/dunhill pfs daily report_YYYY-MM-DD.jpeg`
- `daily_report_snapshot/pfs_daily_highlights_YYYY-MM-DD.jpeg` (if data exists)

### Step 4: Generate DTC Report ⚠️ DEPENDS ON STEPS 2 & 3

**PREREQUISITE**: Steps 2 AND 3 MUST complete successfully first
**DEPENDENCY**: Requires all data from Step 2, and MUST wait for Step 3 to complete
**EXECUTION ORDER**: Step 3 → Step 4 (SEQUENTIAL, NOT PARALLEL)

Automates DTC Excel report generation:
- Opens `dunhill OFS&WBTQ daily sales report.xlsx`
- Refreshes all data connections (2-3 minutes)
- Copies "Daily Sales Trend" sheet as values
- Saves snapshot to snapfile directory
- Takes screenshot of "Daily" sheet (A4:T49)
- Saves JPEG with yesterday's date

**Script**: `scripts/step4_dtc_report.py`

**Output**:
- `daily_report_snapfile/dunhill OFS&WBTQ daily sales report_YYYY-MM-DD.xlsx`
- `daily_report_snapshot/dunhill OFS&WBTQ daily sales report_YYYY-MM-DD.jpeg`

### Step 5: Create Email Drafts ⚠️ DEPENDS ON STEPS 3 & 4

**PREREQUISITE**: Steps 3 and 4 MUST complete successfully first
**DEPENDENCY**: Requires screenshot files from Steps 3 and 4

Creates Outlook email drafts with report attachments:
- Reads email template `.msg` files (if provided in `assets/email_templates/`)
- Replaces `{date}` placeholder with yesterday's date (YYYY-MM-DD)
- Attaches screenshot files
- Saves to Outlook drafts folder (does NOT send)

**Script**: `scripts/step5_email_drafts.py`

**Note**: Emails are saved as drafts for manual review before sending.

**If no templates provided**: Creates basic email drafts with standard format.

## Usage

> **IMPORTANT**: 所有 Python 脚本必须使用 `python -u`（无缓冲模式）运行，否则通过子进程管道执行时 stdout 全缓冲会导致输出不实时显示。步骤2等长时间运行的脚本尤其需要。

### Running Individual Steps

```bash
# Step 1: Collect data from web platforms
python -u scripts/step1_collect_data.py

# Step 2: Run data import scripts
python -u scripts/step2_run_import.py

# Step 3: Generate PFS report
python -u scripts/step3_pfs_report.py

# Step 4: Generate DTC report
python -u scripts/step4_dtc_report.py

# Step 5: Create email drafts
python -u scripts/step5_email_drafts.py
```

### Running Full Workflow

**CRITICAL EXECUTION FLOW - MUST FOLLOW STRICTLY:**

1. **Start**: Ask Claude: "Generate today's Dunhill daily report" (or "执行今天的日报生成")

2. **Step 1** (optional): Collect data from web platforms
   - Wait for completion if executed

3. **Step 2** (CRITICAL): Run data import scripts
   - ⚠️ **MUST WAIT FOR COMPLETE EXECUTION**
   - Monitor for real-time progress updates
   - Look for success indicators:
     * Exit code 0
     * `[OK] 步骤2执行成功！可以继续执行后续步骤。`
     * Summary showing all tasks completed
   - ⚠️ **DO NOT PROCEED UNTIL STEP 2 EXITS**

4. **Step 3**: Generate PFS report
   - Only execute AFTER Step 2 has completed successfully
   - Requires database to be fully populated

5. **Step 4**: Generate DTC report
   - Only execute AFTER Step 3 has completed successfully (SEQUENTIAL)
   - Requires database to be fully populated

6. **Step 5**: Create email drafts
   - Only execute AFTER Steps 3 and 4 have completed
   - Requires screenshot files from Steps 3 and 4

7. **End**: Review and send email drafts manually

**FAILURE HANDLING:**
- If any step fails, stop and report to user
- Do not skip failed steps
- Ask user if they want to retry the failed step

## Key Configuration

Edit `config/dunhill-config.yaml` to customize:

**Credentials**:
- `taobao_username`: Taobao seller platform username
- `taobao_password`: Use `${TAOBAO_PASSWORD}` environment variable

**File Paths** (update these to match your environment):
- `pfs_excel`: PFS report template path
- `dtc_excel`: DTC report template path
- Output directories for snapshots and screenshots
- Download directory

**Settings**:
- `excel_wait_timeout`: Excel refresh timeout (default: 300 seconds)
- `excel_visible`: Show Excel window during automation (useful for debugging)
- `browser_headless`: Show browser window (default: false for debugging)

See [Setup Guide](references/setup.md) for complete configuration details.

## Date Handling

All operations use **yesterday's date** for:
- Report file naming
- Email subject lines
- Screenshot filenames

This ensures reports are always for the previous complete business day.

## Safety Features

1. **Email drafts saved, NOT sent**: Manual review before sending
2. **Progress tracking**: Clear status updates for long operations
3. **Error handling**: Informative error messages and recovery guidance
4. **Session persistence**: Login sessions saved for 7-30 days

## Recent Fixes (2026-01-26)

**PFS Report**:
- Fixed Excel sheet copy method
- Fixed blank screenshots by activating sheets before capture
- Implemented formula-to-values conversion in-workbook
- Skip highlights screenshot when no data in range

**DTC Report**:
- Using correct sheet "Daily Sales Trend"
- Fixed screenshot range to A4:T49
- Implemented retry logic for sheet activation after refresh
- Save original workbook after refresh

## Common Issues

**Excel doesn't close**: `taskkill /F /IM Excel.exe`

**Login fails**: See [Setup Guide - Login Solutions](references/setup.md#login-solutions)

**Session expired**: Re-login with Taobao mobile app; session persists 7-30 days

**Cookie health check failed (cookies 已过期)**: Step 2 会自动检测 `.taobao.com` cookies 有效性，约每 2-3 天过期一次。按提示运行 `python scripts/login/taobao_login.py` 扫码更新后重新执行即可。

**Nick/fq 爬虫大量失败**: 可能是 cookies 过期，也可能是请求量过大触发风控。系统已通过 `UpdateMaskedBuyerNicknames` 存储过程预先解密历史老客昵称以减少爬虫请求量。

**QuickBI exceeds 50 rows**: Script will prompt for manual download from QuickBI URL

**Download button not found**: Script will pause and prompt for manual operation

For complete troubleshooting guide, see [Troubleshooting](references/troubleshooting.md).
