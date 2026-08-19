# Dunhill Step 1-2 Resumable DAG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Step 1-2 step-level retry with durable task receipts, dependency-aware resume, targeted retry, and explicit parallel scheduling without running macOS Steps 3-5.

**Architecture:** Keep the existing scripts as task implementations during migration. Add one standard-library DAG runner that owns `runs/YYYY-MM-DD/state.json`, then register Step 1 exports and Step 2 download/verify/upload/reconcile/enrichment branches as graph tasks. The runner is deterministic; agent or sub-agent diagnosis remains outside the unattended data path.

**Tech Stack:** Python 3, standard library `dataclasses`, `json`, `hashlib`, `threading`, `concurrent.futures`, existing unittest suite, existing LaunchAgent shell wrapper.

**Spec:** `docs/superpowers/specs/2026-08-19-step1-2-resumable-dag-design.md`

## Global Constraints

- macOS executes Step 1-2 only; Steps 3-5 remain excluded.
- Existing `state.json`, `summary.md`, status reporter, LaunchAgent lock, and Lark notification interfaces remain usable.
- State writes are atomic and owned by the runner; task workers return structured results.
- A successful task is reused only when its input fingerprint matches the current graph inputs.
- `pfs_buyer_type` and `dtc_buyer_type` have the same reconciliation prerequisites and no dependency on each other.
- No new third-party dependency or workflow framework is added.
- The existing monolithic `data-import/run.py` remains a manual fallback until task-level parity is verified.

---

### Task 1: Add the durable task-result and atomic-state contract

**Files:**
- Create: `scripts/workflow_dag.py`
- Test: `tests/test_workflow_dag.py`

**Interfaces:**
- Produces `TaskResult`, `TaskSpec`, `WorkflowState`, `atomic_write_json`, and `fingerprint_inputs` for the scheduler and adapters.

- [ ] **Step 1: Write the failing test**

```python
def test_atomic_write_replaces_complete_json(tmp_path):
    path = tmp_path / "state.json"
    atomic_write_json(path, {"tasks": {"a": {"status": "success"}}})
    assert json.loads(path.read_text()) == {"tasks": {"a": {"status": "success"}}}
    assert not list(tmp_path.glob("state.json.*.tmp"))

def test_fingerprint_changes_when_upstream_output_changes():
    first = fingerprint_inputs("2026-08-19", "v1", {"source": "sha256:a"})
    second = fingerprint_inputs("2026-08-19", "v1", {"source": "sha256:b"})
    assert first != second
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_workflow_dag -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.workflow_dag'`.

- [ ] **Step 3: Write minimal implementation**

Implement JSON-serializable dataclasses with terminal statuses `success`, `no_data`, `failed`, `blocked`, and `skipped`; write through a same-directory temporary file and `os.replace`; hash a canonical JSON payload containing run date, contract version, and upstream digests.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_workflow_dag -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/workflow_dag.py tests/test_workflow_dag.py
git commit -m "feat: add durable workflow task contract"
```

### Task 2: Implement dependency scheduling, resource locks, and reuse

**Files:**
- Modify: `scripts/workflow_dag.py`
- Test: `tests/test_workflow_dag.py`

**Interfaces:**
- Consumes `TaskSpec(task_id, deps, resources, runner, contract_version)` and `TaskResult`.
- Produces `DagRunner.run(state, selected=None, force=False)` and `DagRunner.retry(task_id)`.

- [ ] **Step 1: Write the failing test**

```python
def test_failed_only_retry_skips_current_success_and_descendant(tmp_path):
    calls = []
    specs = {
        "a": TaskSpec("a", (), (), lambda _: calls.append("a") or TaskResult.success("a")),
        "b": TaskSpec("b", ("a",), (), lambda _: calls.append("b") or TaskResult.failed("b", "file_error")),
        "c": TaskSpec("c", ("b",), (), lambda _: calls.append("c") or TaskResult.success("c")),
    }
    runner = DagRunner(specs, tmp_path / "state.json")
    runner.run()
    runner.retry("b")
    assert calls == ["a", "b", "b"]

def test_pfs_and_dtc_share_prerequisite_but_run_in_parallel():
    specs = build_test_enrichment_specs()
    assert specs["pfs_buyer_type"].deps == ("database_reconcile",)
    assert specs["dtc_buyer_type"].deps == ("database_reconcile",)
    assert "pfs_buyer_type" not in specs["dtc_buyer_type"].deps
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_workflow_dag.TestDagRunner -v`
Expected: FAIL because `DagRunner` and `build_test_enrichment_specs` do not exist.

- [ ] **Step 3: Write minimal implementation**

Use `ThreadPoolExecutor` for ready tasks, a process-local `threading.Lock` per named resource, and one coordinator thread to persist results. Mark dependents `blocked` when a prerequisite is terminal failure/blocked. Reuse only current successful receipts; invalidate descendants when a selected task gets a new result or fingerprint.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_workflow_dag -v`
Expected: PASS, including a lock test proving two tasks sharing `mysql_upload` do not overlap.

- [ ] **Step 5: Commit**

```bash
git add scripts/workflow_dag.py tests/test_workflow_dag.py
git commit -m "feat: schedule resumable tasks with resource locks"
```

### Task 3: Add the deterministic workflow CLI and task graph

**Files:**
- Create: `scripts/daily_workflow.py`
- Create: `tests/test_daily_workflow.py`
- Modify: `scripts/report_daily_status.py`

**Interfaces:**
- Produces `python -u scripts/daily_workflow.py run|resume|retry <task_id>|retry-failed|status`.
- Produces stable task IDs for Step 1 exports, Step 2 source branches, reconciliation, enrichment, and Alimama.

- [ ] **Step 1: Write the failing test**

```python
def test_graph_contains_independent_buyer_type_branches():
    specs = build_task_specs(test_mode=True)
    assert specs["pfs_buyer_type"].deps == ("database_reconcile",)
    assert specs["dtc_buyer_type"].deps == ("database_reconcile",)

def test_status_command_reads_existing_state_without_running_tasks(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    atomic_write_json(state, {"status": "partial", "tasks": {"pfs_buyer_type": {"status": "failed"}}})
    monkeypatch.setenv("DUNHILL_RUN_DIR", str(tmp_path))
    assert main(["status"]) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_daily_workflow -v`
Expected: FAIL because `scripts.daily_workflow` is not present.

- [ ] **Step 3: Write minimal implementation**

Build the graph from explicit `TaskSpec` values. Keep task runners as adapters, with Step 1 Chrome tasks using `chrome_mcp` and `browser_downloads`, source uploads using `mysql_upload`, and auxiliary tasks depending only on their actual prerequisites. `status` is read-only. `resume` selects stale/pending tasks. `retry-failed` selects failed tasks and their stale descendants.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_daily_workflow -v`
Expected: PASS and no subprocess is started by `status`.

- [ ] **Step 5: Commit**

```bash
git add scripts/daily_workflow.py tests/test_daily_workflow.py scripts/report_daily_status.py
git commit -m "feat: add daily workflow CLI and task graph"
```

### Task 4: Migrate Step 1 to one receipt per export

**Files:**
- Modify: `scripts/step1_chrome_bridge.py`
- Modify: `scripts/step1_collect_data.py`
- Modify: `scripts/daily_workflow.py`
- Test: `tests/test_daily_workflow.py`

**Interfaces:**
- Consumes existing export commands and `DUNHILL_STEP1_TASK_STATE` compatibility file.
- Produces task results for `refund_export`, `live_export`, and five `quickbi_browser.<source>` tasks with output paths and explicit zero-row evidence.

- [ ] **Step 1: Write the failing test**

```python
def test_step1_task_selection_does_not_rerun_current_success(monkeypatch):
    calls = []
    monkeypatch.setattr("scripts.daily_workflow.run_command", lambda command, **_: calls.append(command) or 0)
    state = {"refund_export": {"status": "success", "input_fingerprint": current_fingerprint("refund_export")}}
    run_step1_specs(state)
    assert not any("export_refund_chrome.py" in item[0] for item in calls)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_daily_workflow -k step1 -v`
Expected: FAIL because Step 1 adapters are not graph tasks.

- [ ] **Step 3: Write minimal implementation**

Call existing scripts one export at a time, write task receipts centrally, preserve the old task-state file for compatibility, and treat an empty source as `no_data` only when the exporter emits the existing zero-row marker. Keep Chrome operations serialized by the `chrome_mcp` lock.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_daily_workflow tests.test_chrome_mcp_bridge -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/step1_chrome_bridge.py scripts/step1_collect_data.py scripts/daily_workflow.py tests/test_daily_workflow.py
git commit -m "feat: checkpoint step1 exports independently"
```

### Task 5: Split Step 2 source evidence and targeted upload

**Files:**
- Modify: `scripts/step2_run_import.py`
- Modify: `/Users/novel/Projects/data-import/src/data_pipeline/processors/file_uploader.py`
- Create: `tests/test_step2_task_adapters.py`
- Modify: `tests/test_step2_quickbi_gate.py`

**Interfaces:**
- Produces adapters for `jycm_download.<report_id>`, `sycm_download`, `quickbi_api.<source>`, `source_verify.<source>`, `targeted_upload.<source>`, and `database_reconcile.<source>`.
- Targeted upload accepts an explicit source/task selection and never executes unrelated entries from the global queue.

- [ ] **Step 1: Write the failing test**

```python
def test_targeted_upload_only_selects_requested_source(monkeypatch):
    seen = []
    monkeypatch.setattr(file_uploader, "start", lambda task: seen.append(task.target))
    run_targeted_upload("BI_tm_t01_trade_order_line")
    assert seen == ["dunhill_BI订单源"]

def test_database_error_is_failed_not_success():
    result = reconcile_source("tm_order", execute=lambda: (_ for _ in ()).throw(RuntimeError("mysql down")))
    assert result.status == "failed"
    assert result.error_type == "database_error"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_step2_task_adapters -v`
Expected: FAIL because targeted upload and structured reconciliation adapters are not present.

- [ ] **Step 3: Write minimal implementation**

Filter the configured mission list by the source receipt before calling `Excel.save()`. Return file/Backup evidence from verification and database row/key evidence from reconciliation. Map exceptions to the stable error taxonomy; do not convert upload, schema, or database errors into `no_data`.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=/Users/novel/Projects/data-import/src /Users/novel/Projects/data-import/.venv/bin/python -m unittest discover -s /Users/novel/Projects/data-import/tests -v` and `python -m unittest tests.test_step2_task_adapters tests.test_step2_quickbi_gate -v`
Expected: both suites PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/step2_run_import.py tests/test_step2_task_adapters.py tests/test_step2_quickbi_gate.py
git -C /Users/novel/Projects/data-import add src/data_pipeline/processors/file_uploader.py
git commit -m "feat: isolate step2 source uploads and reconciliation"
```

### Task 6: Checkpoint enrichment and preserve PFS/DTC parallelism

**Files:**
- Modify: `scripts/step2_run_import.py`
- Modify: `scripts/daily_workflow.py`
- Create: `tests/test_enrichment_dependencies.py`

**Interfaces:**
- Produces `unmask_buyer_nicknames`, `fq_crawler`, `nickname_crawler`, `pfs_buyer_type`, and `dtc_buyer_type` task runners.

- [ ] **Step 1: Write the failing test**

```python
def test_pfs_and_dtc_are_parallel_after_reconcile():
    specs = build_task_specs(test_mode=True)
    assert specs["pfs_buyer_type"].deps == ("database_reconcile",)
    assert specs["dtc_buyer_type"].deps == ("database_reconcile",)
    assert specs["fq_crawler"].deps == ("unmask_buyer_nicknames", "taobao_auth_check")
    assert specs["nickname_crawler"].deps == ("unmask_buyer_nicknames", "taobao_auth_check")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_enrichment_dependencies -v`
Expected: FAIL until the graph exposes these exact dependencies.

- [ ] **Step 3: Write minimal implementation**

Keep nickname crawlers behind the Taobao auth check. Run PFS and DTC updates as independent futures after reconciliation, preserving each result separately; a failure in either task must not rerun the other task or the completed core ingestion.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_enrichment_dependencies tests.test_step2_quickbi_gate -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/step2_run_import.py scripts/daily_workflow.py tests/test_enrichment_dependencies.py
git commit -m "feat: checkpoint independent enrichment tasks"
```

### Task 7: Integrate status, summary, notification, LaunchAgent, and Skill

**Files:**
- Modify: `scripts/daily_orchestrator.py`
- Modify: `scripts/launchagent_runner.sh`
- Modify: `scripts/report_daily_status.py`
- Create: `/Users/novel/.codex/skills/dunhill-daily-workflow/SKILL.md`
- Test: `tests/test_daily_orchestrator.py`, `tests/test_report_daily_status.py`, `tests/test_manage_launchagent.py`

**Interfaces:**
- LaunchAgent invokes `python -u scripts/daily_workflow.py run` while preserving the existing lock and environment setup.
- `failed`, `blocked`, and `partial` runs never send a success notification.
- The Skill documents only the stable CLI, task IDs, evidence rules, and recovery commands; it does not contain orchestration logic.

- [ ] **Step 1: Write the failing test**

```python
def test_partial_state_does_not_report_full_success():
    assert workflow_ready_for_notification({"status": "partial", "tasks": {}}) is False

def test_launchagent_keeps_mac_step_boundary():
    text = Path("scripts/launchagent_runner.sh").read_text()
    assert "daily_workflow.py run" in text
    assert "step3" not in text.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_daily_orchestrator tests.test_report_daily_status tests.test_manage_launchagent -v`
Expected: FAIL until the new CLI is wired into the existing status and LaunchAgent contract.

- [ ] **Step 3: Write minimal implementation**

Map task receipts to the existing summary/status fields, retain absolute state and summary paths, keep LaunchAgent Step 1-2 only, and add the Skill after the CLI behavior is stable.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest discover -s tests -v` and `PYTHONPATH=/Users/novel/Projects/data-import/src /Users/novel/Projects/data-import/.venv/bin/python -m unittest discover -s /Users/novel/Projects/data-import/tests -v`
Expected: all existing and new tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/daily_orchestrator.py scripts/launchagent_runner.sh scripts/report_daily_status.py tests
git commit -m "feat: route daily step1-2 through resumable workflow"
```

## Final Verification

- [ ] Run the read-only status command and confirm `state_path`, `summary_path`, notification state, LaunchAgent logs, and `needs_action` are coherent.
- [ ] Run a temporary-directory interruption/resume integration test; do not run Steps 3-5 on macOS.
- [ ] Confirm today’s existing successful run is not re-executed solely because the workflow implementation changed; reuse requires current fingerprints and evidence validation.
