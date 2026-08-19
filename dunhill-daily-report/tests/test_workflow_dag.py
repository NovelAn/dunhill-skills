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

    def test_changed_upstream_output_invalidates_successful_descendant(self):
        with TemporaryDirectory() as directory:
            output = {"value": "a"}
            specs = {
                "a": TaskSpec(
                    "a",
                    runner=lambda _: TaskResult.success("a", outputs=[output["value"]]),
                    inputs=lambda _: {"source": output["value"]},
                ),
                "b": TaskSpec(
                    "b",
                    deps=("a",),
                    runner=lambda context: TaskResult.success(
                        "b", evidence={"upstream": context.state["tasks"]["a"]["outputs"]}
                    ),
                ),
            }
            path = Path(directory) / "state.json"
            runner = DagRunner(specs, path)
            runner.run()
            output["value"] = "b"
            state = runner.run()
            self.assertEqual(state["tasks"]["a"]["outputs"], ["b"])
            self.assertEqual(state["tasks"]["b"]["evidence"]["upstream"], ["b"])

    def test_no_data_is_terminal_and_reusable(self):
        with TemporaryDirectory() as directory:
            calls = []
            specs = {
                "empty_source": TaskSpec(
                    "empty_source",
                    runner=lambda _: calls.append("run") or TaskResult.no_data(
                        "empty_source", evidence={"rows": 0, "confirmed_by": "source"}
                    ),
                )
            }
            runner = DagRunner(specs, Path(directory) / "state.json")
            runner.run()
            runner.run()
            self.assertEqual(calls, ["run"])


if __name__ == "__main__":
    unittest.main()
