# Dunhill Daily LaunchAgent Runner Design

## Goal

Run Dunhill Step 1-2 from the logged-in macOS user GUI session so Chrome,
AppleScript, Playwright MCP loopback networking, Downloads, and Lark access are
available. Keep Codex Automation as a read-only monitor and inbox reporter.

## Architecture

`launchd` owns execution. A user LaunchAgent starts a repository wrapper at
09:10 Asia/Shanghai. The wrapper acquires a non-blocking lock, changes to the
workspace, and executes `python -u scripts/daily_orchestrator.py`. The existing
orchestrator remains the single owner of Step 1-2 ordering, Alimama auth refresh,
run state, summaries, retry behavior, and Lark success notifications.

Codex Automation must not execute the orchestrator. It runs a report command
that reads today's state, summary, and LaunchAgent logs. This avoids all Chrome,
AppleScript, and local-listener operations inside the Codex seatbelt sandbox.

## Components

- `scripts/launchagent_runner.sh`: GUI-session entrypoint with lock and durable
  stdout/stderr logs.
- `scripts/manage_launchagent.py`: renders, installs, checks, manually triggers,
  and uninstalls the user LaunchAgent.
- `scripts/report_daily_status.py`: emits a concise machine-readable status for
  Codex Automation without starting any workflow step.
- `launchd/com.dunhill.daily-report.plist.template`: reviewed LaunchAgent
  definition with explicit paths and calendar schedule.

## Data Flow

At 09:10, launchd invokes the wrapper. The wrapper runs the orchestrator, which
writes `runs/YYYY-MM-DD/state.json`, `summary.md`, and step logs, then sends Lark
only after both steps succeed. A later Codex Automation invocation reads those
artifacts and reports final status. It never mutates the run.

## Failure Handling

The wrapper uses `mkdir` as an atomic lock and removes the lock on exit. A second
trigger exits successfully after logging that a run is already active. The
status reporter distinguishes missing, running, success, failed, and stale
states and exposes `state.notification` unchanged. LaunchAgent stdout/stderr are
kept outside per-run logs so failures before Python startup remain diagnosable.

## Testing

Unit tests verify plist rendering, schedule, GUI session type, paths, lock-aware
wrapper structure, and status reporting. Installation is verified with
`launchctl print gui/$UID/com.dunhill.daily-report`. A manual `launchctl kickstart`
is the final end-to-end test because only the real GUI launchd domain proves the
sandbox problem is removed.

## Operational Boundary

The LaunchAgent runs only Step 1-2. Steps 3-5 remain excluded on macOS. The
existing Codex Automation is retained but its prompt must be changed to run only
`python -u scripts/report_daily_status.py` after the LaunchAgent schedule.
