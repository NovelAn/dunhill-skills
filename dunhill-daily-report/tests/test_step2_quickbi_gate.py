import tempfile
import unittest
from pathlib import Path

from scripts.daily_orchestrator import classify_failure
from scripts.step2_run_import import check_required_quickbi_files, confirmed_zero_quickbi_sources


class QuickBICompletionGateTests(unittest.TestCase):
    def test_missing_dtc_order_is_reported_even_when_other_sources_exist(self):
        with tempfile.TemporaryDirectory() as download_dir, tempfile.TemporaryDirectory() as backup_dir:
            date_token = "20260625"
            for prefix in (
                "BI_tm_t01_trade_order_line",
                "BI_tm_trade_refund_info_allsuc_filter",
                "BI_tm_trade_refund_info_paydate_filter",
                "BI_dtc_t01_trade_refund_info_allsuc_filter",
            ):
                (Path(backup_dir) / f"{prefix}_{date_token}.xlsx").touch()

            ok, missing = check_required_quickbi_files(
                download_dir,
                "2026-06-25",
                save_path=backup_dir,
            )

        self.assertFalse(ok)
        self.assertEqual(missing, ["BI_dtc_t01_trade_order_line"])

    def test_final_gate_rejects_success_when_required_quickbi_file_is_missing(self):
        from scripts.step2_run_import import quickbi_completion_gate

        ok, missing = quickbi_completion_gate(
            run_succeeded=True,
            files_ok=False,
            missing_files=["BI_dtc_t01_trade_order_line"],
        )

        self.assertFalse(ok)
        self.assertEqual(missing, ["BI_dtc_t01_trade_order_line"])

    def test_confirmed_zero_source_does_not_override_pipeline_failure(self):
        from scripts.step2_run_import import quickbi_completion_gate

        ok, missing = quickbi_completion_gate(
            run_succeeded=False,
            files_ok=False,
            missing_files=["BI_dtc_t01_trade_order_line"],
            confirmed_zero_sources={"BI_dtc_t01_trade_order_line"},
        )

        self.assertFalse(ok)
        self.assertEqual(missing, [])

    def test_confirmed_zero_sources_are_read_from_step1_log(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "step1.log"
            log_path.write_text(
                '[OK] create: {"prefix": "BI_dtc_t01_trade_order_line", "rows": 0, "skipped": true}\n'
                '[OK] create: {"prefix": "BI_tm_t01_trade_order_line", "rows": 9, "skipped": true}\n',
                encoding="utf-8",
            )

            sources = confirmed_zero_quickbi_sources(Path(temp_dir))

        self.assertEqual(sources, {"BI_dtc_t01_trade_order_line"})

    def test_orchestrator_classifies_missing_dtc_order_as_actionable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "step2.log"
            log_path.write_text(
                "[FAIL] 当天必需 QuickBI 文件不完整\n"
                "BI_dtc_t01_trade_order_line\n",
                encoding="utf-8",
            )

            hints = classify_failure(log_path)

        self.assertTrue(any("DTC 订单源未生成当天文件" in hint for hint in hints))


if __name__ == "__main__":
    unittest.main()
