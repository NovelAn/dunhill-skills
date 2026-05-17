# Dunhill Daily Report Troubleshooting

## Excel Automation Issues

### Excel doesn't close properly

**Symptoms**:
- Multiple Excel.exe processes in Task Manager
- "Permission denied" errors when accessing files
- Excel windows remaining open after script completes

**Solutions**:

1. **Manual cleanup**:
   ```bash
   taskkill /F /IM Excel.exe
   ```

2. **Prevention**: Set `excel_visible: true` in config to monitor Excel state
   ```yaml
   settings:
     excel_visible: true
   ```

3. **Avoid manual intervention**: Don't interact with Excel windows while script is running

### Data refresh timeout

**Symptoms**:
```
Warning: Refresh timeout reached, proceeding anyway
```

**Solutions**:

Increase timeout in config:
```yaml
settings:
  excel_wait_timeout: 600  # Increase to 10 minutes
```

**Common causes**:
- Slow network connection to data sources
- Large datasets being refreshed
- Excel processing other workbooks

### File already in use

**Symptoms**:
```
PermissionError: [Errno 13] Permission denied
```

**Solutions**:

1. Check if file is open in another Excel instance
2. Close all Excel instances:
   ```bash
   taskkill /F /IM Excel.exe
   ```
3. Verify file permissions - ensure current user has read/write access

### Screenshots are blank or incorrect

**Symptoms**: Generated JPEG files are blank or show wrong content

**Recent fixes (2026-01-26)**:
- ✅ Sheet activation before screenshot
- ✅ Added 0.5s delay for Excel to switch sheets
- ✅ Fixed PFS highlights screenshot to skip when no data

**If issues persist**:
1. Set `excel_visible: true` to watch the automation
2. Verify screenshot ranges in scripts are correct
3. Check if sheet names match Excel template

## Browser Automation Issues

### Login fails

**Symptoms**:
```
Login failed: ...
```

**Solutions**:

1. **Verify credentials**: Check `taobao_username` and `taobao_password` in config
2. **Use session persistence**: Set up `.browser_profile` (see setup.md)
3. **Manual login fallback**:
   - Let browser open
   - Manually login using Taobao mobile app
   - Script will continue with saved session

4. **Check password**: Ensure `TAOBAO_PASSWORD` environment variable is set:
   ```bash
   # PowerShell
   echo $env:TAOBAO_PASSWORD

   # CMD
   echo %TAOBAO_PASSWORD%
   ```

### Download button not found

**Symptoms**:
```
Export failed: ...
[WARN] Automatic download failed
[MANUAL ACTION REQUIRED]
```

**Solutions**:

1. **Manual download** (when prompted):
   - In the browser window, manually click the download/export button
   - Wait for download to complete
   - Press Enter in terminal to continue

2. **Try CDP version**: Use `step1_collect_data_cdp.py` with Chrome remote debugging

3. **Page layout changed**: The Taobao interface may have changed. The script uses multiple selector strategies to find download buttons, but if all fail, manual download is required as fallback.

### Playwright browser not installed

**Symptoms**:
```
Executable doesn't exist at ...
```

**Solution**:
```bash
playwright install chromium
```

### Connection to Chrome CDP fails

**Symptoms** (when using CDP version):
```
[ERROR] Failed to connect to Chrome
Error: connect ECONNREFUSED 127.0.0.1:9222
```

**Solutions**:

1. **Verify Chrome is running** with remote debugging:
   ```bash
   # Check for port 9222
   netstat -ano | findstr :9222
   ```

2. **Start Chrome correctly**:
   ```bash
   chrome.exe --remote-debugging-port=9222
   ```

3. **Kill conflicting processes**:
   ```bash
   taskkill /F /IM chrome.exe
   # Then restart with correct flags
   ```

4. **Check firewall/antivirus**: Ensure port 9222 is not blocked

### Session expired

**Symptoms**: Browser opens and shows login page again

**Solutions**:

1. **Re-login** using Taobao mobile app
2. **Check session persistence**: Ensure `browser_user_data_dir` is correctly set in config
3. **Backup browser profile**: Periodically backup `.browser_profile` directory
   ```bash
   xcopy .browser_profile .browser_profile_backup /E /I /H /Y
   ```

## Python Script Execution Issues

### Module not found

**Symptoms**:
```
ModuleNotFoundError: No module named 'xxx'
```

**Solution**:
```bash
# Reinstall all dependencies
pip install -r requirements.txt

# Or install specific module
pip install playwright pywin32 pyyaml
```

### Permission denied

**Symptoms**:
```
PermissionError: [Errno 13] Permission denied
```

**Solutions**:

1. Run command prompt as Administrator
2. Check file/directory permissions
3. Ensure current user has write access to output directories

### Script execution timeout

**Symptoms** (Step 2):
```
Timeout waiting for run.py to complete
```

**Solutions**:

1. **Increase timeout** in config:
   ```yaml
   settings:
     script_max_wait: 3600  # Increase to 60 minutes
   ```

2. **Check data import script**: Ensure `run.py` is working correctly
3. **Monitor output**: The script checks output every 5 seconds by default

### QuickBI table exceeds 50 rows

**Symptoms** (Step 2):
```
WARNING: Table BI_tm_t01_trade_order_line has 120 rows (>50 threshold)
Manual download required
```

**Solutions**:

1. **Visit the QuickBI URL** provided in warning message
2. **Select time range**: "最近3天" (Last 3 days)
3. **Click** "查询" (Query)
4. **Click** "任务列表" (Task List) on right sidebar
5. **Click** "创建取数任务" (Create Export Task)
6. **Wait** 3-5 minutes for task to complete
7. **Download** the file (usually first in list)
8. **Run** upload script when prompted:
   ```bash
   python manage.py upload
   ```

Or input `y` when Step 2 script asks if you've manually downloaded the files.

## Email and Outlook Issues

### Outlook not running

**Symptoms** (Step 5):
```
Error creating email drafts
```

**Solution**:
- Start Outlook and log in to your account
- Ensure Outlook profile is configured correctly

### Email template not found

**Symptoms**:
```
Warning: PFS template not found at ...
```

**Solutions**:

1. **Place template files** in correct location:
   ```
   assets/email_templates/pfs_email_template.msg
   assets/email_templates/dtc_email_template.msg
   ```

2. **Or skip templates**: Script will create basic email drafts without templates

### Date replacement doesn't work

**Symptoms**: Date placeholder `{date}` not replaced in email

**Solution**:
- Use `{date}` placeholder in template subject and body
- Format will be YYYY-MM-DD (e.g., 2026-01-22)

## Date and Time Issues

### Wrong date in reports

**Symptoms**: Generated files use today's date instead of yesterday's

**Cause**: Scripts use `datetime.now() - timedelta(days=1)` to calculate yesterday's date

**Verification**: Check the date in:
- File names
- Email subjects
- Screenshot filenames

**Temporary fix** (for testing): Edit `get_yesterday_date()` function in scripts:
```python
def get_yesterday_date():
    # Use fixed date for testing
    return "2026-01-22"
```

## General Debugging Tips

### Enable debug mode

Set these in `dunhill-config.yaml`:
```yaml
settings:
  excel_visible: true       # Show Excel windows
  browser_headless: false   # Show browser windows
  browser_slow_mo: 2000     # Slow down actions (milliseconds)
```

### Check log output

All scripts print detailed progress information:
- `[INFO]` - Informational messages
- `[OK]` - Success confirmations
- `[WARN]` - Warnings (doesn't stop execution)
- `[ERROR]` - Errors (may require manual intervention)

### Isolate the problem

Test each step independently:
```bash
python scripts/step1_collect_data.py
python scripts/step2_run_import.py
python scripts/step3_pfs_report.py
python scripts/step4_dtc_report.py
python scripts/step5_email_drafts.py
```

This helps identify which step is failing.

### Verify file paths

Check all paths in `dunhill-config.yaml`:
- Excel template files must exist
- Output directories will be created automatically
- Download directory must be correct
- Use double backslashes `\\` or forward slashes `/` in Windows paths

### Network issues

**Symptoms**: Timeouts, connection errors

**Solutions**:
1. Check internet connection
2. Verify VPN/proxy settings if used
3. Try accessing URLs manually in browser first
4. Increase timeout values in config

## Getting Help

If issues persist:

1. **Check error messages** carefully - they usually indicate the problem
2. **Review relevant sections** in this troubleshooting guide
3. **Test individual steps** to isolate the issue
4. **Verify configuration** in `dunhill-config.yaml`
5. **Check dependencies** are correctly installed

For issues not covered here, please provide:
- Full error message
- Which step failed
- Configuration file (with sensitive info removed)
- Python and library versions
