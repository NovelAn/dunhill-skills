import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.daily_workflow import build_task_specs, main, render_progress, sync_legacy_state, workflow_complete


class DailyWorkflowTests(unittest.TestCase):
    def test_sync_legacy_state_maps_steps_and_needs_action(self):
        state = {
            "tasks": {
                "refund_export": {"status": "success"},
                "quickbi_browser.tm_order": {"status": "success"},
                "jycm_download.445603": {"status": "failed", "error_type": "transient_network"},
            }
        }

        synced = sync_legacy_state(state)

        self.assertEqual(synced["steps"]["step1"]["status"], "success")
        self.assertEqual(synced["steps"]["step2"]["status"], "failed")
        self.assertIn("jycm_download.445603: transient_network", synced["needs_action"])
        self.assertFalse(workflow_complete(synced))

    def test_render_progress_shows_each_task_status(self):
        state = {
            "run_date": "2026-08-20",
            "status": "running",
            "tasks": {"refund_export": {"status": "success"}, "fq_crawler": {"status": "running"}},
        }

        body = render_progress(state)

        self.assertIn("OK  refund_export", body)
        self.assertIn("RUN  fq_crawler", body)
        self.assertIn(".  ", body)

    def test_graph_contains_independent_buyer_type_branches(self):
        specs = build_task_specs(test_mode=True)
        self.assertEqual(specs["pfs_buyer_type"].deps, ("database_reconcile",))
        self.assertEqual(specs["dtc_buyer_type"].deps, ("database_reconcile",))
        self.assertNotIn("pfs_buyer_type", specs["dtc_buyer_type"].deps)

    def test_nickname_crawlers_require_auth_and_unmask(self):
        specs = build_task_specs(test_mode=True)
        self.assertEqual(
            set(specs["fq_crawler"].deps),
            {"unmask_buyer_nicknames", "taobao_auth_check"},
        )
        self.assertEqual(
            set(specs["nickname_crawler"].deps),
            {"unmask_buyer_nicknames", "taobao_auth_check"},
        )

    def test_status_command_reads_existing_state_without_running_tasks(self):
        with TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state_path.write_text(
                json.dumps({"status": "partial", "tasks": {"pfs_buyer_type": {"status": "failed"}}}),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"DUNHILL_RUN_DIR": directory}), patch(
                "scripts.daily_workflow.subprocess.run",
                side_effect=AssertionError("status must not run workflow"),
            ):
                self.assertEqual(main(["status"]), 0)


if __name__ == "__main__":
    unittest.main()
