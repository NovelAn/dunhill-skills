"""Small, durable task DAG runner for the Dunhill daily workflow."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


TERMINAL_STATUSES = {"success", "no_data", "failed", "blocked", "skipped"}
FAILED_STATUSES = {"failed", "blocked"}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def fingerprint_inputs(run_date: str, contract_version: str, upstream: dict[str, Any]) -> str:
    payload = {
        "run_date": run_date,
        "contract_version": contract_version,
        "upstream": upstream,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass
class TaskResult:
    task: str
    status: str
    attempt: int = 1
    input_fingerprint: str | None = None
    outputs: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    error_type: str | None = None
    retryable: bool = False
    started_at: str | None = None
    ended_at: str | None = None

    def __post_init__(self) -> None:
        if self.status not in TERMINAL_STATUSES:
            raise ValueError(f"Unsupported terminal task status: {self.status}")

    @classmethod
    def success(cls, task: str, **kwargs: Any) -> "TaskResult":
        return cls(task, "success", **kwargs)

    @classmethod
    def no_data(cls, task: str, **kwargs: Any) -> "TaskResult":
        return cls(task, "no_data", **kwargs)

    @classmethod
    def failed(cls, task: str, error_type: str, retryable: bool = False, **kwargs: Any) -> "TaskResult":
        return cls(task, "failed", error_type=error_type, retryable=retryable, **kwargs)


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    deps: tuple[str, ...] = ()
    resources: tuple[str, ...] = ()
    runner: Callable[["TaskContext"], TaskResult] | None = None
    contract_version: str = "v1"
    inputs: Callable[[dict[str, Any]], dict[str, Any]] | None = None


@dataclass(frozen=True)
class TaskContext:
    task_id: str
    attempt: int
    state: dict[str, Any]


class DagRunner:
    def __init__(self, specs: dict[str, TaskSpec], state_path: Path, max_workers: int = 4):
        self.specs = specs
        self.state_path = state_path
        self.max_workers = max_workers
        self._state_lock = threading.Lock()
        self._resource_locks: dict[str, threading.Lock] = {}

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"status": "pending", "tasks": {}}
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"status": "pending", "tasks": {}}
        state.setdefault("tasks", {})
        return state

    def _save_state(self, state: dict[str, Any]) -> None:
        state["updated_at"] = now_iso()
        atomic_write_json(self.state_path, state)

    def _fingerprint(self, spec: TaskSpec, state: dict[str, Any]) -> str:
        upstream = {
            dependency: state.get("tasks", {}).get(dependency, {}).get("outputs", [])
            for dependency in spec.deps
        }
        if spec.inputs is not None:
            upstream["inputs"] = spec.inputs(state)
        return fingerprint_inputs(
            state.get("run_date", datetime.now().strftime("%Y-%m-%d")),
            spec.contract_version,
            upstream,
        )

    def _descendants(self, task_id: str) -> set[str]:
        descendants = set()
        frontier = [task_id]
        while frontier:
            current = frontier.pop()
            for candidate, spec in self.specs.items():
                if current in spec.deps and candidate not in descendants:
                    descendants.add(candidate)
                    frontier.append(candidate)
        return descendants

    def _ready(self, task_id: str, state: dict[str, Any], selected: set[str]) -> bool:
        spec = self.specs[task_id]
        if any(dependency not in state["tasks"] for dependency in spec.deps):
            return False
        if any(state["tasks"][dependency].get("status") in FAILED_STATUSES for dependency in spec.deps):
            return False
        return all(
            state["tasks"][dependency].get("status") in {"success", "no_data", "skipped"}
            for dependency in spec.deps
        ) and task_id in selected

    def _run_one(self, spec: TaskSpec, state: dict[str, Any], attempt: int) -> TaskResult:
        if spec.runner is None:
            return TaskResult.failed(spec.task_id, "code_error")
        locks = [self._resource_locks.setdefault(name, threading.Lock()) for name in sorted(spec.resources)]
        for lock in locks:
            lock.acquire()
        started_at = now_iso()
        try:
            result = spec.runner(TaskContext(spec.task_id, attempt, state))
            if result.task != spec.task_id:
                result.task = spec.task_id
            result.attempt = attempt
            result.started_at = result.started_at or started_at
            result.ended_at = result.ended_at or now_iso()
            return result
        except Exception as error:  # task boundaries must become durable receipts
            return TaskResult.failed(
                spec.task_id,
                "code_error",
                evidence={"message": str(error)},
                started_at=started_at,
                ended_at=now_iso(),
            )
        finally:
            for lock in reversed(locks):
                lock.release()

    def run(self, selected: set[str] | None = None, force: bool = False) -> dict[str, Any]:
        state = self._load_state()
        selected = set(self.specs) if selected is None else set(selected)
        unknown = selected - set(self.specs)
        if unknown:
            raise ValueError(f"Unknown task(s): {', '.join(sorted(unknown))}")

        state["status"] = "running"
        for task_id in selected:
            receipt = state["tasks"].get(task_id, {})
            current_fingerprint = self._fingerprint(self.specs[task_id], state)
            if (
                not force
                and receipt.get("status") in {"success", "no_data"}
                and receipt.get("input_fingerprint") == current_fingerprint
            ):
                continue
            if receipt.get("status") in TERMINAL_STATUSES:
                state["tasks"][task_id] = {"status": "pending"}
        self._save_state(state)

        pending = {task_id for task_id in selected if state["tasks"].get(task_id, {}).get("status") != "success"}
        pending -= {task_id for task_id in selected if state["tasks"].get(task_id, {}).get("status") == "no_data"}
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {}
            while pending or futures:
                for task_id in list(pending):
                    if self._ready(task_id, state, selected):
                        receipt = state["tasks"].get(task_id, {})
                        attempt = int(receipt.get("attempt", 0)) + 1
                        state["tasks"][task_id] = {"status": "running", "attempt": attempt}
                        self._save_state(state)
                        print(f"[RUN] {task_id} (attempt {attempt})", flush=True)
                        pending.remove(task_id)
                        futures[pool.submit(self._run_one, self.specs[task_id], dict(state), attempt)] = task_id

                if not futures:
                    for task_id in list(pending):
                        spec = self.specs[task_id]
                        if any(state["tasks"].get(dep, {}).get("status") in FAILED_STATUSES for dep in spec.deps):
                            state["tasks"][task_id] = asdict(TaskResult(task_id, "blocked", error_type="dependency_failed"))
                            pending.remove(task_id)
                    if pending:
                        raise RuntimeError(f"DAG cannot make progress: {sorted(pending)}")
                    break

                for future in as_completed(list(futures)):
                    task_id = futures.pop(future)
                    result = future.result()
                    result.input_fingerprint = self._fingerprint(self.specs[task_id], state)
                    state["tasks"][task_id] = asdict(result)
                    for descendant in self._descendants(task_id):
                        receipt = state["tasks"].get(descendant, {})
                        if receipt.get("status") in {"success", "no_data"}:
                            current = self._fingerprint(self.specs[descendant], state)
                            if receipt.get("input_fingerprint") != current:
                                state["tasks"][descendant] = {"status": "pending"}
                                pending.add(descendant)
                    detail = f" ({result.error_type})" if result.error_type else ""
                    print(f"[{result.status.upper()}] {task_id}{detail}", flush=True)
                    self._save_state(state)

        statuses = [receipt.get("status") for receipt in state["tasks"].values() if receipt.get("status") in TERMINAL_STATUSES]
        state["status"] = "success" if statuses and all(status in {"success", "no_data", "skipped"} for status in statuses) else "failed"
        self._save_state(state)
        return state

    def retry(self, task_id: str) -> dict[str, Any]:
        if task_id not in self.specs:
            raise ValueError(f"Unknown task: {task_id}")
        selected = {task_id, *self._descendants(task_id)}
        state = self._load_state()
        for candidate in selected:
            state["tasks"].pop(candidate, None)
        self._save_state(state)
        return self.run(selected=selected)
