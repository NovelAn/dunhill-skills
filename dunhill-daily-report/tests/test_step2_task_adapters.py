import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from scripts.daily_workflow import _real_runner, build_task_specs
from scripts.workflow_dag import TaskResult
from scripts.workflow_tasks import run_step2_task, step2_command


class Step2CommandMappingTests(unittest.TestCase):
    def test_jycm_download_maps_to_single_report_command(self):
        mapping = step2_command("jycm_download.445603", date(2026, 8, 20))
        self.assertEqual(mapping[0][-3:], ["jycm", "445603", "dunhill_shop_d_recent_30d_20260820"])

    def test_quickbi_upload_is_targeted(self):
        mapping = step2_command("targeted_upload.quickbi_api.tm_order", date(2026, 8, 20))
        self.assertEqual(mapping[0][-2:], ["--target", "dunhill_BI订单源"])

    def test_enrichment_tasks_map_to_manage_order_actions(self):
        self.assertEqual(step2_command("fq_crawler", date(2026, 8, 20))[0][-2:], ["order", "fq"])
        self.assertEqual(step2_command("dtc_buyer_type", date(2026, 8, 20))[0][-2:], ["order", "update_dtc"])

    def test_gate_tasks_delegate_without_commands(self):
        self.assertIsNone(step2_command("taobao_auth_check", date(2026, 8, 20)))
        # auth check 是真实子进程调用（连千牛），测试必须 mock，不能依赖当天 cookies 状态
        with mock.patch("scripts.workflow_tasks.subprocess.run") as run:
            run.return_value.returncode = 0
            result = run_step2_task("taobao_auth_check", Path("."))
        self.assertEqual(result.status, "success")


class Step2RunnerTests(unittest.TestCase):
    def test_nonzero_exit_is_failed_with_log_tail(self):
        with mock.patch("scripts.workflow_tasks.subprocess.run") as run:
            run.return_value.returncode = 1
            run.return_value.stdout = "cookie 过期"
            run.return_value.stderr = ""
            result = run_step2_task("fq_crawler", Path("."))
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_type, "auth_required")

    def test_quickbi_api_reuses_existing_download_per_source(self):
        with TemporaryDirectory() as tmp:
            fake_downloads = Path(tmp) / "Downloads"
            fake_downloads.mkdir()
            stamp = date.today().strftime("%Y%m%d")
            (fake_downloads / f"BI_tm_t01_trade_order_line_{stamp}.xlsx").write_bytes(b"not-an-excel")
            with mock.patch(
                "scripts.workflow_tasks._download_dir", return_value=fake_downloads
            ), mock.patch(
                "scripts.workflow_tasks._default_save_path", return_value=Path(tmp) / "backup"
            ), mock.patch("scripts.workflow_tasks.subprocess.run") as run:
                result = run_step2_task("quickbi_api.tm_order", Path("."))
        run.assert_not_called()
        self.assertEqual(result.status, "success")

    def test_real_graph_uses_live_runners_for_step2(self):
        specs = build_task_specs(test_mode=False)
        with mock.patch("scripts.workflow_tasks.subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = ""
            run.return_value.stderr = ""
            result = specs["jycm_download.445603"].runner(None)
        self.assertEqual(result.status, "success")


if __name__ == "__main__":
    unittest.main()
