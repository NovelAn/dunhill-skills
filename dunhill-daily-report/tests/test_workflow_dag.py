import json
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.workflow_dag import (
    DagRunner,
    TaskResult,
    TaskSpec,
    atomic_write_json,
    fingerprint_inputs,
)


class WorkflowDagTests(unittest.TestCase):
    def test_atomic_write_replaces_complete_json(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            atomic_write_json(path, {"tasks": {"a": {"status": "success"}}})
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"tasks": {"a": {"status": "success"}}},
            )
            self.assertEqual(list(Path(directory).glob("state.json.*.tmp")), [])

    def test_fingerprint_changes_when_upstream_output_changes(self):
        first = fingerprint_inputs("2026-08-19", "v1", {"source": "sha256:a"})
        second = fingerprint_inputs("2026-08-19", "v1", {"source": "sha256:b"})
        self.assertNotEqual(first, second)

    def test_failed_only_retry_skips_current_success_and_descendant(self):
        with TemporaryDirectory() as directory:
            calls = []
            specs = {
                "a": TaskSpec("a", runner=lambda _: calls.append("a") or TaskResult.success("a")),
                "b": TaskSpec(
                    "b",
                    deps=("a",),
                    runner=lambda _: calls.append("b") or TaskResult.failed("b", "file_error"),
                ),
                "c": TaskSpec(
                    "c",
                    deps=("b",),
                    runner=lambda _: calls.append("c") or TaskResult.success("c"),
                ),
            }
            runner = DagRunner(specs, Path(directory) / "state.json")
            runner.run()
            runner.retry("b")
            self.assertEqual(calls, ["a", "b", "b"])

    def test_resource_lock_serializes_tasks(self):
        with TemporaryDirectory() as directory:
            active = 0
            maximum = 0
            guard = threading.Lock()

            def work(task):
                nonlocal active, maximum
                with guard:
                    active += 1
                    maximum = max(maximum, active)
                time.sleep(0.02)
                with guard:
                    active -= 1
                return TaskResult.success(task.task_id)

            specs = {
                name: TaskSpec(name, resources=("mysql_upload",), runner=work)
                for name in ("a", "b")
            }
            DagRunner(specs, Path(directory) / "state.json", max_workers=2).run()
            self.assertEqual(maximum, 1)


if __name__ == "__main__":
    unittest.main()
