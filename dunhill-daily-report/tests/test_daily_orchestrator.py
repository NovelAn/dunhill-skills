import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import scripts.daily_orchestrator as orchestrator


class DailyOrchestratorTests(unittest.TestCase):
    def test_weekend_skips_lark_notification(self):
        config = {"notifications": {"lark": {"enabled": True, "chat_id": "oc_x"}}}
        with patch("scripts.daily_orchestrator.datetime") as dt:
            dt.now.return_value = datetime(2026, 8, 22)  # Saturday
            notification = orchestrator.send_lark_success_notification(config, {}, Path("."), dry_run=True)
        self.assertTrue(notification["skipped"])
        self.assertEqual(notification["reason"], "weekend")

    def test_legacy_success_without_current_contract_is_not_reused(self):
        self.assertFalse(orchestrator.step_success_is_current({"status": "success"}))

    def test_notification_requires_both_steps_on_current_contract(self):
        current = {
            "status": "success",
            "validation_contract": orchestrator.SUCCESS_CONTRACT_VERSION,
        }
        state = {"steps": {"step1": current, "step2": current}}

        self.assertTrue(orchestrator.workflow_ready_for_notification(state))
        self.assertFalse(orchestrator.workflow_ready_for_notification({"steps": {"step1": current}}))

    def test_step1_retry_command_only_runs_failed_subtasks(self):
        args = Namespace(force=False)
        state = {
            "step1_tasks": {
                "refund": "success",
                "live": "success",
                "quickbi:tm_order": "failed",
                "quickbi:tm_refund_success": "success",
                "quickbi:tm_refund_pending": "success",
                "quickbi:dtc_order": "success",
                "quickbi:dtc_refund": "success",
            }
        }

        command = orchestrator.step_command("step1", args, state)

        self.assertIn("--skip-refund", command)
        self.assertIn("--skip-live", command)
        self.assertIn("--quickbi-sources", command)
        self.assertIn("tm_order", command)
        self.assertNotIn("tm_refund_success", command)

    def test_step2_runs_even_when_step1_fails(self):
        calls = []

        def fake_run_step(step, *_args):
            calls.append(step)
            return step == "step2"

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(orchestrator, "RUNS_DIR", Path(temp_dir) / "runs"), \
                patch.object(orchestrator, "ensure_runtime_python"), \
                patch.object(orchestrator, "ensure_caffeinated"), \
                patch.object(orchestrator, "load_config", return_value={}), \
                patch.object(orchestrator, "run_step_with_retries", side_effect=fake_run_step):
                exit_code = orchestrator.main([
                    "--date",
                    "2026-06-26",
                    "--no-caffeinate",
                    "--no-notify",
                    "--completion-rounds",
                    "1",
                ])

        self.assertEqual(exit_code, 1)
        self.assertEqual(calls, ["step1", "step2"])

    def test_failed_step1_is_retried_after_step2_then_step2_reruns(self):
        calls = []
        outcomes = iter([False, True, True, True])

        def fake_run_step(step, *_args):
            calls.append(step)
            return next(outcomes)

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(orchestrator, "RUNS_DIR", Path(temp_dir) / "runs"), \
                patch.object(orchestrator, "ensure_runtime_python"), \
                patch.object(orchestrator, "ensure_caffeinated"), \
                patch.object(orchestrator, "load_config", return_value={}), \
                patch.object(orchestrator, "run_step_with_retries", side_effect=fake_run_step):
                exit_code = orchestrator.main(["--date", "2026-06-26", "--no-caffeinate", "--no-notify"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls, ["step1", "step2", "step1", "step2"])

    def test_step1_partial_failure_waits_for_step2_before_failed_only_retry(self):
        calls = []
        state = {
            "run_date": "2026-06-29",
            "status": "pending",
            "steps": {},
            "step1_tasks": {},
        }

        def fake_run_step(step, command, _run_dir, current_state, _dry_run, retries):
            calls.append((step, command[3:], retries))
            if step == "step1" and len([call for call in calls if call[0] == "step1"]) == 1:
                current_state["step1_tasks"] = {
                    "refund": "success",
                    "live": "failed",
                    **{f"quickbi:{key}": "success" for key in orchestrator.QUICKBI_SOURCE_KEYS},
                }
                return False
            return True

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(orchestrator, "RUNS_DIR", Path(temp_dir) / "runs"), \
                patch.object(orchestrator, "ensure_runtime_python"), \
                patch.object(orchestrator, "ensure_caffeinated"), \
                patch.object(orchestrator, "load_config", return_value={}), \
                patch.object(orchestrator, "load_state", return_value=state), \
                patch.object(orchestrator, "run_step_with_retries", side_effect=fake_run_step):
                exit_code = orchestrator.main(["--date", "2026-06-29", "--no-caffeinate", "--no-notify"])

        self.assertEqual(exit_code, 0)
        self.assertEqual([call[0] for call in calls], ["step1", "step2", "step1", "step2"])
        self.assertEqual(calls[0][2], 0)
        self.assertEqual(calls[1][2], 1)
        self.assertEqual(calls[2][1], ["--skip-refund", "--skip-quickbi"])

    def test_step2_reruns_when_same_day_step1_retry_succeeds(self):
        calls = []
        state = {
            "run_date": "2026-06-26",
            "status": "failed",
            "steps": {
                "step1": {"status": "failed"},
                "step2": {"status": "success"},
            },
        }

        def fake_run_step(step, *_args):
            calls.append(step)
            return True

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(orchestrator, "RUNS_DIR", Path(temp_dir) / "runs"), \
                patch.object(orchestrator, "ensure_runtime_python"), \
                patch.object(orchestrator, "ensure_caffeinated"), \
                patch.object(orchestrator, "load_config", return_value={}), \
                patch.object(orchestrator, "load_state", return_value=state), \
                patch.object(orchestrator, "run_step_with_retries", side_effect=fake_run_step):
                exit_code = orchestrator.main(["--date", "2026-06-26", "--no-caffeinate", "--no-notify"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls, ["step1", "step2"])


if __name__ == "__main__":
    unittest.main()
