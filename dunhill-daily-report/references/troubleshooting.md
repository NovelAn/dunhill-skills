# Dunhill Daily Report Troubleshooting

## Excel Automation Issues

### Mac Excel cannot refresh Power Query reports

**Symptoms**:
- Steps 3 or 4 cannot refresh PFS/DTC workbooks on macOS
- Excel does not expose the expected Power Query / MySQL connection refresh behavior
- Screenshots or email drafts for Step 5 are missing because Step 3/4 outputs were never generated

**Cause**: The PFS and DTC daily report workbooks depend on Windows Excel Power Query / MySQL data connections. Mac Excel does not support this workflow.

**Solution**:
- Run Step 1 and Step 2 on Mac.
- Run Step 3 and Step 4 on Windows Excel or a remote Windows host.
- Run Step 5 only after Step 3/4 screenshots and snapshot workbooks exist.
- Do not debug this as a Python-only issue; the blocking layer is Excel feature support.

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

## 千牛退款导出问题 (Step 1)

### Codex Extension / browser-use 操作千牛太慢

**症状**: Codex Extension 已经打开千牛退款页，但点击、弹窗确认、下载等操作非常慢或卡住。

**原因**: 当前 Codex computer-use/browser-use 对千牛这类复杂页面的模拟点击不够稳定。

**解决方案**: Step 1 不使用 Codex Extension。统一运行：
```bash
python -u scripts/step1_collect_data.py
```

该入口通过 Playwright Chrome Extension + MCP bridge 复用本机 Chrome 登录态并运行高速脚本。

### Step 1 仍然打开旧 persistent profile

**症状**: 执行 Step 1 时打开了新的 Playwright profile、要求扫码，或调用了旧的 `export_refund.py`。

**原因**: 入口脚本或文档仍在使用旧流程。

**解决方案**: 使用统一 bridge 入口：
```bash
python -u scripts/step1_collect_data.py
```

该入口会调用 `step1_chrome_bridge.py`，由 Playwright MCP Extension 复用本机 Chrome 登录态并自行导航到退款/直播页面。

### 售后状态筛选后数据量没变化

**症状**: 选择"全部"并点击"搜索售后单"后，数据量仍然是 ~120 条

**原因**: 只打开了 `next-select` 下拉菜单并点击了"全部"，但没有取消默认选中的"进行中的订单"。Next.js 多选组件中两个选项同时选中时，默认选项优先级更高。

**正确操作**:
1. 打开下拉菜单
2. **先点击"进行中的订单"取消勾选**
3. 再点击"全部"
4. 确认显示"已选择 1/14 项 全部"（而非"已选择 2/14 项"）
5. 点击"搜索售后单"

**验证**: 搜索后"已选 (0/N)"中的 N 应该从 ~120 变为 ~1200

### 隐私弹窗反复出现

**症状**: 每次点击"查看已生成报表"或"下载退款单报表"都会弹出隐私确认对话框

**这是正常行为** — 千牛对每一次数据下载操作都要求确认隐私条款。每次点击"确认"即可。

### 点击"查看已生成报表"后看不到报表列表

**症状**: 确认隐私弹窗后页面仍在退款管理页，没有看到报表列表

**原因**: "查看已生成报表"会在**新标签页**中打开报表列表（URL: `/trade-platform/refund-list/export-list`），不是在当前页面弹窗。Playwright MCP 可能不会自动切换到新标签页。

**解决方案**:
1. 检查浏览器标签页列表：`browser_tabs(action="list")`
2. 如果新标签页存在，切换过去：`browser_tabs(action="select", index=N)`
3. 如果新标签页未被捕获（常见），直接导航到报表列表 URL：
   ```
   browser_navigate(url="https://myseller.taobao.com/home.htm/trade-platform/refund-list/export-list")
   ```

### 下载按钮找不到 / 点击无反应

**症状**: 在 export-list 页面点击"下载退款单报表"无反应

**排查步骤**:
1. 确认"进度"显示"已完成"（不是"生成中"）
2. 确认报表未失效（"已失效，请重新导出"的报表无下载按钮）
3. 检查页面是否有新隐私弹窗需要确认
4. 用 `browser_evaluate` 查找所有可见按钮：`document.querySelectorAll('button')` 中匹配 "下载退款单报表"
5. 同一页面可能有多条历史记录，确保点击的是第一条（最新一条）

### 下载文件无法识别

**症状**: 下载完成后 Downloads 目录中出现数字 ID 文件名，不知道哪个是最新下载的

**解决方案**:
```bash
# 按修改时间排序列出最近下载的 xlsx 文件
ls -lt ~/Downloads/*.xlsx | head -3

# 验证文件内容
python3 -c "
import openpyxl
wb = openpyxl.load_workbook('文件路径', read_only=True)
ws = wb[wb.sheetnames[0]]
print(f'Rows: {ws.max_row}, Cols: {ws.max_column}')
print(f'Headers: {next(ws.iter_rows(min_row=1, max_row=1, values_only=True))}')
wb.close()
"
```

### "5分钟内只能导出一次" 限制

**症状**: "生成报表"按钮变为灰色，显示"5分钟内只能导出一次"

这是千牛的限制。如果之前的导出操作有问题需要重试，必须等待 5 分钟。建议在更改筛选条件前确认设置正确，避免浪费时间。

### Next.js 组件交互注意事项

千牛新版 UI 使用 Next.js 的 `next-select`、`next-dialog` 等组件，与原生 HTML 元素不同：

- **`next-select-multiple`**: 多选下拉框，不支持原生 `<select>` 的 `select_option` 操作
  - 需要通过 `browser_evaluate` + JavaScript 操作 DOM
  - 点击选项通过 `.next-menu-item` 的 click 事件
  - 选中状态通过 `.next-selected` class 判断

- **Ref 时效性**: Playwright snapshot 中的 ref 值在每次页面重新渲染后会变化，不能跨操作缓存

- **推荐交互方式**: 优先使用 `browser_evaluate` 执行 JavaScript 直接操作 DOM，而非依赖 snapshot ref

## Browser Automation Issues

### Scheduled Step 1 cannot open Chrome

**Symptoms**:
- `com.apple.hiservices-xpcservice Connection Invalid`
- AppleScript error `-1728`
- `listen EPERM: operation not permitted ::1`
- `sysmond service not found`

**Cause**: The orchestrator was started from a sandboxed Codex Automation
process. This environment cannot reliably reach the logged-in macOS GUI session
or create the Playwright MCP local listener. Repeatedly changing Chrome launch
logic does not fix this execution-boundary problem.

**Solution**: Run Step 1-2 from the installed user LaunchAgent and use Codex only
for read-only reporting:

```bash
python -u scripts/manage_launchagent.py status
python -u scripts/manage_launchagent.py trigger
python -u scripts/report_daily_status.py
```

Do not configure Codex Automation to run `daily_orchestrator.py` directly.

### Login fails

**Symptoms**:
```
Login failed: ...
```

**Solutions**:

1. **Verify local Chrome login**: Open QianNiu/Taobao and Taobao Live Platform in normal Chrome.
2. **Verify Playwright Extension token**: Copy a fresh `PLAYWRIGHT_MCP_EXTENSION_TOKEN` from the Chrome extension status page.
3. **Manual login fallback**:
   - Log in manually in normal Chrome.
   - Re-run `python -u scripts/step1_collect_data.py`.

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

2. **For live export, check Playwright Extension**: `export_live.py` should connect through Chrome Playwright Extension. If it opens a new browser or reaches login, set `PLAYWRIGHT_MCP_EXTENSION_TOKEN` from the extension status page and retry.

3. **Page layout changed**: The Taobao interface may have changed. The script uses multiple selector strategies to find download buttons, but if all fail, manual download is required as fallback.

### Live export opens login page

**Symptoms**:
```
Playwright Extension 没有复用到已登录 Chrome
```

**Cause**: The live export is not connected to the local Chrome extension session. This usually happens when the extension token is missing, stale, or from another Chrome profile.

**Solutions**:

1. Open the Playwright Extension status page in the Chrome profile that is already logged in to Taobao.
2. Copy the full `PLAYWRIGHT_MCP_EXTENSION_TOKEN=...` value.
3. Set only the token value in the current shell:
   ```bash
   export PLAYWRIGHT_MCP_EXTENSION_TOKEN="your_token"
   ```
4. Re-run:
   ```bash
   python -u scripts/export_live.py
   ```
5. If Chrome shows a connection confirmation page, confirm it once and let the script continue.

### Chrome bridge connection times out

**Symptoms**:
```
Timed out waiting for Playwright MCP Extension
```

**Solutions**:

1. Confirm the Playwright Extension is installed in the same Chrome profile that is logged in to Taobao.
2. Open the extension status page and copy a fresh token.
3. Set `PLAYWRIGHT_MCP_EXTENSION_TOKEN` in the current shell.
4. Run the bridge again:
   ```bash
   python -u scripts/step1_collect_data.py
   ```
5. If the status page says no clients are connected, keep the page open and rerun the command.

### Live export slider verification

**Symptoms**: `export_live.py` prints that a slider/captcha was detected.

**Solution**: Complete the slider manually in Chrome. The script waits for the slider to disappear and then continues the download flow.

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

**Symptoms**: Step 1 reports that refund/live pages are still on login, or Chrome opens a login page.

**Solutions**:

1. Re-login in normal Chrome using Taobao/QianNiu.
2. Confirm the Playwright Extension is installed in the same Chrome profile.
3. Copy a fresh `PLAYWRIGHT_MCP_EXTENSION_TOKEN` from the extension status page and re-run Step 1.

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

1. **Run the Step 1 QuickBI supplement**:
   ```bash
   python -u scripts/export_quickbi_chrome.py --sources all
   ```
   The script checks `查询结果共XX条`, creates a fresh self-service export when `XX > 50`, waits for the backend task, and downloads only the task created after the current run started.

2. **Run** upload script when prompted:
   ```bash
   python manage.py upload
   ```

Or input `y` when Step 2 script asks if you've manually downloaded the files.

Manual fallback:
1. Visit the QuickBI URL provided in warning message.
2. Click "任务列表" (Task List) on right sidebar.
3. Click "创建取数任务" (Create Export Task), confirm `纯数据 Excel`.
4. Wait 3-5 minutes for task to complete.
5. Download the newest row whose `创建于` time is after your manual task start time.

### Taobao cookies expire during Step 2

**Symptoms**:
- Step 2 reports `.taobao.com` cookies expired
- QianNiu requests redirect to login
- Nick/fq crawlers fail because Taobao auth is stale

**Expected recovery**:
1. Step 2 first runs `/Users/novel/projects/data-import/scripts/login/taobao_login_mcp.py`.
2. The script connects to normal Chrome through Playwright MCP Extension.
3. It opens QianNiu/Taobao in the existing Chrome login state and syncs fresh Taobao cookies into `~/auth.json`.
4. Step 2 re-checks cookies and continues.

**Fallback**: If MCP cookie sync fails, Step 2 falls back to the legacy interactive login script and auto-selects option `1` for 千牛/淘宝.

**Scope**: This automatic refresh is mainly for high-frequency QianNiu/Taobao auth. QuickBI, SYCM, and JYCM cookies usually expire less often and are preserved during the merge.

### Alimama CSRF expires during Step 2

**Symptoms**:
- Alimama crawler reports `bizLogin csrf检查未通过`
- `https://one.alimama.com/report/query.json` returns 403
- Manual browser login works, but the requests-based crawler cannot run

**Expected recovery**:
1. Daily command should use `python -u scripts/step2_run_import.py --refresh-alimama-auth-first`.
2. Step 2 runs `python manage.py alimama --refresh-auth`.
3. The auth script connects to normal Chrome through Playwright MCP Extension, scans Alimama page requests/resources for `csrfId`, and saves matching cookies.
4. Step 2 then runs `python manage.py alimama`.

**Fallback**: If the first request still fails CSRF validation, the Alimama crawler automatically refreshes auth once and retries the current request.

**Emergency skip**: Use `python -u scripts/step2_run_import.py --skip-alimama` only when Alimama is unavailable and the rest of Step 2 must finish.

## Email and Outlook Issues

## Feishu/Lark Notification Issues

### Success notification is not sent

**Symptoms**:
- Step 1 and Step 2 succeed, but the group `数据更新提醒` does not receive a message.
- `state.json` contains `notification.lark_success: false`.

**Checks**:
1. Verify `lark-cli` is available on the Mac.
2. Verify `config/dunhill-config.yaml` has `notifications.lark.enabled: true`.
3. Verify the configured bot is in the group:
   ```bash
   lark-cli im chat.members bots --params '{"chat_id":"oc_2713a524be31fe0092cbfe94533407ac"}'
   ```
4. Dry-run the notification:
   ```bash
   python -u scripts/daily_orchestrator.py --only step2 --dry-run --notify-dry-run --force
   ```

**Note**: The orchestrator returns success when Step 1 and Step 2 complete even if the Lark notification fails. Notification failure is recorded in `runs/YYYY-MM-DD/state.json`.

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
  script_check_interval: 5  # Step 2 output polling interval
  script_max_wait: 3600     # Increase Step 2 maximum wait to 60 minutes
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
