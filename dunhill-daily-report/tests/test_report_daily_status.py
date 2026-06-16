import json
import tempfile
import unittest
from pathlib import Path

from scripts.report_daily_status import build_report


class DailyStatusReportTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_state(self, run_date, payload):
        run_dir = self.root / "runs" / run_date
        run_dir.mkdir(parents=True)
        (run_dir / "state.json").write_text(json.dumps(payload), encoding="utf-8")
        (run_dir / "summary.md").write_text("# Summary\n", encoding="utf-8")

    def test_missing_state_reports_not_run_without_starting_workflow(self):
        report = build_report(self.root, "2026-06-13")

        self.assertEqual(report["status"], "not_run")
        self.assertFalse(report["state_exists"])
        self.assertEqual(report["notification"], None)

    def test_failed_state_includes_needs_action_and_paths(self):
        self.write_state(
            "2026-06-13",
            {
                "status": "failed",
                "steps": {
                    "step1": {"status": "failed", "needs_action": ["Open Chrome"]},
                    "step2": {"status": "pending", "needs_action": []},
                },
            },
        )

        report = build_report(self.root, "2026-06-13")

        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["needs_action"], ["Open Chrome"])
        self.assertTrue(report["state_path"].endswith("runs/2026-06-13/state.json"))
        self.assertTrue(report["summary_path"].endswith("runs/2026-06-13/summary.md"))

    def test_success_state_preserves_notification(self):
        notification = {"lark_success": True, "message_id": "om_123"}
        self.write_state(
            "2026-06-13",
            {
                "status": "success",
                "steps": {
                    "step1": {"status": "success", "needs_action": []},
                    "step2": {"status": "success", "needs_action": []},
                },
                "notification": notification,
            },
        )

        report = build_report(self.root, "2026-06-13")

        self.assertEqual(report["status"], "success")
        self.assertEqual(report["notification"], notification)
        self.assertEqual(report["steps"], {"step1": "success", "step2": "success"})


if __name__ == "__main__":
    unittest.main()
