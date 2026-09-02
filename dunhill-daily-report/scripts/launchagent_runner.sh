#!/bin/zsh

set -u

ROOT_DIR="${0:A:h:h}"
RUNS_DIR="$ROOT_DIR/runs"
LOCK_FILE="$RUNS_DIR/.launchagent.lock"
RUNNER_LOG="$RUNS_DIR/launchagent.runner.log"
PYTHON_BIN="/Users/novel/Projects/data-import/.venv/bin/python"
LARK_CLI_BIN="/Users/novel/.nvm/versions/node/v20.19.6/bin/lark-cli"

mkdir -p "$RUNS_DIR"

if [[ "${DUNHILL_LAUNCHAGENT_LOCKED:-0}" != "1" ]]; then
  DUNHILL_LAUNCHAGENT_LOCKED=1 /usr/bin/lockf -t 0 "$LOCK_FILE" "$0"
  lock_exit=$?
  if [[ $lock_exit -eq 75 ]]; then
    printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "Run already active; skipping duplicate trigger." >> "$RUNNER_LOG"
    exit 0
  fi
  exit "$lock_exit"
fi

export LARK_CLI_BIN
export PATH="${LARK_CLI_BIN:h}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export LANG="zh_CN.UTF-8"
export LC_ALL="zh_CN.UTF-8"

cd "$ROOT_DIR"
printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "LaunchAgent run started." >> "$RUNNER_LOG"
if [[ ! -x "$PYTHON_BIN" ]]; then
  printf '%s %s %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "Python runtime is unavailable:" "$PYTHON_BIN" >> "$RUNNER_LOG"
  exit 127
fi

# 90 分钟 wall-clock 上限：macOS 没 GNU timeout，zsh 内嵌 watchdog。
# daily_workflow.py run 内部用 Popen(start_new_session=True) 启动 manage.py quickbi
# 等子进程（commit 2 已修）。watchdog 通过 PGID（start_new_session 让主进程独占 PG）
# 一次 kill 整组；macOS shell `/bin/kill -TERM -PGID` 走 BSD 路径，可用。
RUN_TIMEOUT_SEC=${DUNHILL_RUN_TIMEOUT_SEC:-5400}  # 90 min
"$PYTHON_BIN" -u scripts/daily_workflow.py run &
RUN_PID=$!
RUN_PGID=$(ps -o pgid= -p "$RUN_PID" | tr -d ' ')
(
  sleep "$RUN_TIMEOUT_SEC"
  if kill -0 "$RUN_PID" 2>/dev/null; then
    printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "LaunchAgent timeout: killing PGID $RUN_PGID after ${RUN_TIMEOUT_SEC}s" >> "$RUNNER_LOG"
    # 先 SIGTERM 让子进程树优雅退出（依赖 commit 2 的 start_new_session）
    /bin/kill -TERM -"$RUN_PGID" 2>/dev/null
    sleep 5
    /bin/kill -KILL -"$RUN_PGID" 2>/dev/null
  fi
) &
WATCH_PID=$!

wait "$RUN_PID"
exit_code=$?
kill -KILL "$WATCH_PID" 2>/dev/null
printf '%s %s %d\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "LaunchAgent run exited with code" "$exit_code" >> "$RUNNER_LOG"
exit "$exit_code"
