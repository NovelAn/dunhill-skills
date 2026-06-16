#!/bin/zsh

set -u

ROOT_DIR="${0:A:h:h}"
RUNS_DIR="$ROOT_DIR/runs"
LOCK_DIR="$RUNS_DIR/.launchagent.lock"
RUNNER_LOG="$RUNS_DIR/launchagent.runner.log"
PYTHON_BIN="/Users/novel/Projects/data-import/.venv/bin/python"
LARK_CLI_BIN="/Users/novel/.nvm/versions/node/v20.19.6/bin/lark-cli"

mkdir -p "$RUNS_DIR"

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "Run already active; skipping duplicate trigger." >> "$RUNNER_LOG"
  exit 0
fi

cleanup() {
  rmdir "$LOCK_DIR" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

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
"$PYTHON_BIN" -u scripts/daily_orchestrator.py
exit_code=$?
printf '%s %s %d\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "LaunchAgent run exited with code" "$exit_code" >> "$RUNNER_LOG"
exit "$exit_code"
