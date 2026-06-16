# Dunhill Daily Report - Execution Flow Guide

## Critical Execution Requirements

### ⚠️ MANDATORY SEQUENTIAL EXECUTION

This workflow MUST execute steps in strict order with dependency checking:

```
Step 1 (optional) → Step 2 → Step 3 → Step 4 → Step 5
                            ↑
                      CRITICAL CHECKPOINT
                      Wait here until completion
```

On macOS, the normal stopping point is Step 2. Steps 3-5 require Windows Excel because the PFS/DTC workbooks rely on Power Query / MySQL data connections that Mac Excel cannot refresh.

### Why Step 2 Must Complete First

**Step 2** (`run.py`) performs critical data operations:
1. Downloads data from multiple sources (QuickBI, SYCM, JYCM, etc.)
2. Processes and transforms the data
3. **Uploads ALL data to the database**
4. Runs the Alimama daily crawler after the main import pipeline

**Steps 3 and 4** depend on this data:
- They open Excel files with database connections
- They refresh these connections to pull latest data
- If Step 2 hasn't completed, the refresh will fail or show incomplete data
- They require Windows Excel with Power Query / MySQL connection support

### How to Verify Step 2 Completion

Before proceeding to Step 3 or 4, verify ALL of these:

**Exit Code Check:**
```bash
# Exit code must be 0 (success), not 1 (failure)
```

**Visual Indicators (look for these messages):**
```
[OK] 步骤2执行成功！可以继续执行后续步骤。

======================================================================
  步骤2执行完成 - 总耗时: XX:XX
======================================================================

  任务完成情况: X/Y
```

**Process Status:**
- The Python process must have terminated (exited)
- No longer running in background

**What NOT to Do:**
- ❌ Don't start Step 3 if Step 2 is still running
- ❌ Don't start Step 3 if you see `[FAIL]` messages
- ❌ Don't start Step 3 if exit code is 1
- ❌ Don't assume Step 2 is complete just because some tasks finished

## Execution Checklist

### Before Starting Any Step

**Scheduled Mac Execution:**
- [ ] Codex Automation is scheduled for 09:30 Asia/Shanghai
- [ ] Chrome is available with Playwright MCP Extension installed
- [ ] Mac is awake or can be kept awake during the run
- [ ] Use `python -u scripts/daily_orchestrator.py` for Step 1-2
- [ ] Check `runs/YYYY-MM-DD/summary.md` after completion

**Step 2 Execution:**
- [ ] Confirm Step 1 (if used) has completed
- [ ] Verify database is accessible
- [ ] Verify network connection to Taobao/QuickBI
- [ ] For daily runs, use `--refresh-alimama-auth-first`
- [ ] Check available disk space

**Step 3 Execution (AFTER Step 2 completes):**
- [ ] Step 2 has exited (process terminated)
- [ ] Step 2 exit code is 0
- [ ] See `[OK] 步骤2执行成功！` message
- [ ] All data sources show as completed
- [ ] PFS Excel file exists and is accessible
- [ ] Running on Windows Excel, not Mac Excel

**Step 4 Execution (AFTER Step 2 completes):**
- [ ] Step 2 has exited (process terminated)
- [ ] Step 2 exit code is 0
- [ ] See `[OK] 步骤2执行成功！` message
- [ ] All data sources show as completed
- [ ] DTC Excel file exists and is accessible
- [ ] Running on Windows Excel, not Mac Excel

**Step 5 Execution (AFTER Steps 3 & 4 complete):**
- [ ] Step 3 has completed
- [ ] Step 4 has completed
- [ ] Screenshot files exist in snapshot directories
- [ ] Email template files (if used) are accessible
- [ ] On Mac, Step 3/4 screenshot files were already generated elsewhere

## Troubleshooting Execution Issues

### Step 2 Appears to Hang

**Normal behavior:**
- Step 2 can take 5-10 minutes (sometimes longer)
- Multiple data sources are being downloaded
- Database uploads take time

**Signs of problems:**
- No progress updates for >15 minutes
- Error messages in output
- Process exits with code 1

**Action:**
- Check the output for error messages
- Verify network connectivity
- Check database server status
- May need to restart Step 2

### Step 3 or 4 Started Before Step 2 Completed

**Symptoms:**
- Excel refresh shows old data
- Excel refresh errors
- Missing data in reports

**Action:**
- STOP Step 3/4 immediately
- Wait for Step 2 to complete
- Re-run Steps 3 and 4 after Step 2 finishes

### Step 3 or 4 Started on Mac

**Symptoms:**
- Excel opens but database refresh does not work
- Power Query / MySQL connection refresh is unavailable
- Report screenshots are missing or stale

**Action:**
- Stop Steps 3/4 on Mac.
- Keep the successful Step 1/2 data import.
- Refresh PFS/DTC workbooks on Windows Excel or a remote Windows host, then run Step 5 only after screenshots exist.

### Step 2 Fails

**Common causes:**
- Network connectivity issues
- Database server down
- QuickBI session expired
- Insufficient permissions

**Action:**
- Review error messages from Step 2 output
- Fix the underlying issue
- Re-run Step 2
- Only proceed to Steps 3-5 after successful retry

## Example Successful Execution Flow

```
User: "Generate today's Dunhill daily report"

Claude: Starting Step 2: Data Import
Command: python -u scripts/step2_run_import.py --refresh-alimama-auth-first
[Output showing real-time progress...]
[OK] QuickBI订单源下载完成
[OK] 生意参谋数据爬取完成
[OK] 经营参谋数据下载完成
  - 正在下载报告: dunhill_traffic_d_recent_1d_2026
  - 正在下载报告: dunhill_client_d_recent_30d_2026
  ...

[WAIT - Claude monitors Step 2...]

Step 2 Process: Exited with code 0

Claude: ✓ Step 2 completed successfully
Claude: macOS environment detected; stopping after Step 2 because Steps 3-5 require Windows Excel / Power Query.

Alternative on Windows:
Claude: Starting Step 3: PFS Report Generation
[Step 3 executes...]

Claude: ✓ Step 3 completed
Claude: Starting Step 4: DTC Report Generation
[Step 4 executes...]

Claude: ✓ Step 4 completed
Claude: Starting Step 5: Email Draft Creation
[Step 5 executes...]

Claude: ✓ All steps completed successfully!
```

## Summary

**RULE #1**: Step 2 MUST complete before Steps 3, 4, or 5
**RULE #2**: Verify success indicators, don't assume completion
**RULE #3**: If Step 2 fails, stop and fix before continuing
**RULE #4**: Never skip steps in the sequence
**RULE #5**: On Mac, stop after Step 2 unless refreshed Step 3/4 outputs already exist
