# Dunhill Step 1-2 Resumable DAG Design

## Objective

Reduce recurring Step 1-2 failures by replacing duplicate monolithic orchestration with a deterministic, resumable task graph. Every task must have explicit dependencies, durable completion evidence, bounded retries, and an independent recovery path.

The daily data path must not depend on an LLM or Sub-agent. Agents remain available as a control plane for diagnosis and authorized recovery.

## Scope

This design covers macOS Step 1 and Step 2 only.

It does not run or implement Step 3-5. Those steps remain Windows-only because they require Excel Power Query and MySQL refresh support.

## Problems To Remove

1. `data-import/run.py` combines downloads, global upload, order crawlers, and buyer-type updates in one process.
2. `scripts/step2_run_import.py` parses `run.py` text logs, then may repeat upload and follow-up tasks after a failure.
3. Task status is mostly in memory, so a late failure causes successful upstream work to run again.
4. Optional and daily sources share one upload queue, allowing an unrelated missing source to fail the daily pipeline.
5. Exit codes, file presence, Backup presence, and database freshness can disagree.
6. Broad retries repeat deterministic failures and waste browser, network, and database work.

## Architecture

Use a hybrid control-plane/data-plane design.

- The data plane is a deterministic Python DAG executed by LaunchAgent.
- Existing scripts remain task implementations during migration.
- A single workflow state file stores atomic task receipts.
- A Skill exposes stable run, resume, retry, status, and diagnosis commands.
- Agents and Sub-agents read task receipts and logs after failures; they are not part of unattended execution or success validation.
- No new orchestration framework or dependency is added.

## Task Contract

Each task returns a structured `TaskResult` instead of requiring its caller to parse log text.

```json
{
  "task": "quickbi_api.tm_order",
  "status": "success",
  "attempt": 1,
  "input_fingerprint": "sha256:...",
  "outputs": ["/absolute/path/to/source.xlsx"],
  "evidence": {
    "rows": 50,
    "backup_path": "/absolute/path/to/backup.xlsx",
    "database_rows_verified": 50
  },
  "error_type": null,
  "retryable": false,
  "started_at": "2026-08-19T09:42:25",
  "ended_at": "2026-08-19T09:45:49"
}
```

Valid terminal task statuses are:

- `success`: required output and completion evidence are valid.
- `no_data`: the source explicitly returned zero rows; a missing file alone never proves `no_data`.
- `failed`: execution or validation failed.
- `blocked`: a dependency failed or a required human login is unavailable.
- `skipped`: the task was not selected by an explicit command option.

`pending` and `running` are non-terminal statuses.

## Durable State

The existing `runs/YYYY-MM-DD/state.json` remains the canonical workflow state. It gains a `tasks` object keyed by stable task ID.

State writes use a temporary file followed by `os.replace` so interruption cannot leave partial JSON. The central runner owns state writes; parallel workers return results to the runner instead of editing the file themselves.

Each input fingerprint includes:

- run date;
- task validation-contract version;
- relevant configuration values;
- selected upstream output digests.

A successful task is reused only when its fingerprint still matches. If an upstream output changes, only dependent descendants become stale.

## Task Graph

### Step 1 Collection

Step 1 keeps separate receipts for:

- `refund_export`
- `live_export`
- `quickbi_browser.tm_order`
- `quickbi_browser.tm_refund_success`
- `quickbi_browser.tm_refund_pending`
- `quickbi_browser.dtc_order`
- `quickbi_browser.dtc_refund`

These tasks are logically independent but use the same `chrome_mcp` resource lock, so they run one at a time in the user's local Chrome session. A failure reruns only the failed export.

### Step 2 Core Ingestion

Independent collection branches:

- `jycm_download.<report_id>`
- `sycm_download`
- `quickbi_api.<source>`

`taobao_auth_check` is a prerequisite for `sycm_download`, `fq_crawler`, and `nickname_crawler`. It is not a prerequisite for JYCM HTTP downloads, QuickBI API downloads, or buyer-type updates.

Each collected source then follows its own evidence chain:

```text
source_download
      -> source_verify
      -> targeted_upload
      -> database_reconcile
```

The upload task processes only the source identified by its receipt. It does not scan and execute every mission in the global upload queue.

Core ingestion is complete only when every required source reaches `success` or a verified `no_data` state and every non-empty source passes database reconciliation.

### Step 2 Enrichment

After relevant order tables pass database reconciliation:

```text
database_reconcile -> unmask_buyer_nicknames -> fq_crawler
                  |                          -> nickname_crawler
                  |-> pfs_buyer_type
                  `-> dtc_buyer_type

taobao_auth_check ---------------------------> fq_crawler
                  ---------------------------> nickname_crawler
```

`fq_crawler`, `nickname_crawler`, `pfs_buyer_type`, and `dtc_buyer_type` are independently checkpointed. PFS and DTC buyer-type updates run in parallel because they read and update separate tables and do not depend on nickname-crawler output.

### Alimama Branch

```text
alimama_auth_check -> alimama_auth_refresh_if_needed -> alimama_import
```

This branch is independent of core source upload and buyer enrichment. Chrome-based auth refresh uses the `chrome_mcp` lock; API import does not.

## Resource Locks

Logical independence does not imply unrestricted parallel execution.

- `chrome_mcp`: capacity 1 for all local-Chrome MCP operations.
- `browser_downloads`: capacity 1 for browser tasks writing into Downloads.
- `mysql_upload`: capacity 1 for source uploads that may touch overlapping tables or move source files.
- HTTP downloads write to task-specific temporary files and atomically rename on completion.
- Enrichment tasks may run concurrently only when they update separate tables.

Locks are process-local because LaunchAgent already enforces one workflow process. The existing LaunchAgent lock remains the cross-process guard.

## Retry And Recovery Rules

Errors use a stable taxonomy:

- `auth_required`
- `transient_network`
- `source_not_ready`
- `no_data`
- `schema_drift`
- `database_error`
- `file_error`
- `code_error`

Automatic retries are bounded and error-specific:

- `transient_network`: retry with bounded backoff.
- `source_not_ready`: retry only within the configured readiness window.
- `auth_required`: run the approved local-Chrome refresh once, then block for human action.
- `schema_drift`, `database_error`, `file_error`, and `code_error`: do not blindly retry.
- `no_data`: terminal success only when the source explicitly confirms zero rows.

Supported recovery commands:

```bash
python -u scripts/daily_workflow.py run
python -u scripts/daily_workflow.py resume
python -u scripts/daily_workflow.py retry <task_id>
python -u scripts/daily_workflow.py retry-failed
python -u scripts/daily_workflow.py status
```

`retry <task_id>` reruns that task and invalidates only descendants whose input fingerprint changes. `retry-failed` never reruns a successful task with a current fingerprint. `--force` remains available only as an explicit operator action.

## Workflow Status

- `failed`: one or more core ingestion tasks failed or are blocked.
- `partial`: core ingestion succeeded, but one or more enrichment or Alimama tasks failed or are blocked.
- `success`: all selected core and auxiliary tasks succeeded or returned verified `no_data`.
- `running`: at least one runnable task is active.

The Lark success notification is sent only for `success`. A `partial` run records precise failed task IDs and `needs_action` without claiming full completion.

## Agent And Skill Boundary

One shared `dunhill-daily-workflow` Skill exposes the deterministic CLI and references for task IDs, evidence, error types, and recovery rules. Step 1 and Step 2 are views over the same graph, not separate monolithic Skills.

Sub-agents may be used after deterministic execution reports failures:

- diagnostic Sub-agent: reads one failed task receipt and its log;
- browser-recovery Sub-agent: handles an explicitly authorized local-Chrome login recovery;
- code-repair Sub-agent: reproduces and fixes a confirmed software defect with tests.

Sub-agents do not concurrently control Chrome, move shared files, decide database success from logs, modify credentials, or force-kill another workflow process.

## Migration

1. Add the task-result model, DAG scheduler, atomic state writer, dependency invalidation, and resource locks behind tests.
2. Wrap existing Step 1 export commands as graph tasks without rewriting browser logic.
3. Split Step 2 into explicit download, verification, targeted upload, reconciliation, enrichment, and Alimama task adapters.
4. Stop calling monolithic `data-import/run.py` from the daily workflow after task-level parity tests pass. Keep it temporarily available as a manual legacy entrypoint.
5. Preserve the existing `state.json`, `summary.md`, status reporter, LaunchAgent schedule, and Lark notification interface.
6. Switch LaunchAgent to `daily_workflow.py run` only after resume, failure, and current-success migration tests pass.
7. Add the shared Skill after the CLI contract is stable; the Skill wraps commands and does not duplicate orchestration logic.

Existing successful Step 1/2 state can be imported as legacy evidence only after current file, Backup, and database validation. Legacy success text alone is never trusted.

## Testing And Acceptance

Unit coverage must prove:

- dependency ordering and parallel readiness;
- resource-lock serialization;
- atomic state replacement;
- successful-task reuse;
- failed-only retry;
- downstream invalidation after changed upstream output;
- verified `no_data` handling;
- core failure versus auxiliary partial status;
- notification suppression for `failed` and `partial`;
- PFS and DTC buyer-type parallel scheduling;
- real upload/database errors remain visible.

Integration tests use temporary directories and fake task commands to verify interruption and resume without browser or production database access.

Acceptance criteria:

1. A late auxiliary failure does not repeat downloads, uploads, or database reconciliation.
2. Retrying one failed task runs only that task and stale descendants.
3. No task is successful based only on subprocess exit code or log text.
4. Every non-empty required source has file/Backup and database evidence.
5. A missing optional source cannot fail unrelated daily tasks.
6. LaunchAgent still runs only macOS Step 1-2.
7. Existing project and data-import test suites remain green.

## Deliberate Simplifications

- Use the Python standard library instead of a workflow framework.
- Keep one workflow process and process-local resource locks.
- Keep state in JSON rather than adding a database.
- Reuse existing task scripts before considering deeper crawler rewrites.

These choices are sufficient for one daily workflow on one Mac. A distributed scheduler is warranted only if execution moves to multiple machines or overlapping runs become a real requirement.
