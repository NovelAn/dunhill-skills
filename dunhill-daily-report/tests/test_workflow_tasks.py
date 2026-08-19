import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.workflow_tasks import run_step1_task, step1_command


class WorkflowTaskTests(unittest.TestCase):
    def test_quickbi_task_runs_only_selected_source(self):
        command = step1_command("quickbi_browser.dtc_order", Path("/workspace"))
        self.assertIn("--quickbi-sources", command)
        self.assertEqual(command[-1], "dtc_order")
        self.assertIn("--skip-refund", command)
        self.assertIn("--skip-live", command)

    def test_success_requires_new_file_not_exit_code_alone(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with patch(
                "scripts.workflow_tasks.run_command",
                return_value=subprocess.CompletedProcess([], 0, "done", ""),
            ):
                result = run_step1_task("quickbi_browser.tm_order", root, root)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_type, "file_error")

    def test_explicit_zero_rows_is_terminal_no_data(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with patch(
                "scripts.workflow_tasks.run_command",
                return_value=subprocess.CompletedProcess([], 0, '{"rows": 0}', ""),
            ):
                result = run_step1_task("quickbi_browser.tm_order", root, root)
        self.assertEqual(result.status, "no_data")
        self.assertEqual(result.evidence["rows"], 0)


if __name__ == "__main__":
    unittest.main()
