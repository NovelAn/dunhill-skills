import os
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from scripts.daily_orchestrator import classify_failure
from scripts.step2_run_import import (
    check_required_quickbi_files,
    confirmed_zero_quickbi_sources,
    find_step1_upload_residuals,
    tm_order_import_complete,
)


class QuickBICompletionGateTests(unittest.TestCase):
    def test_yesterday_backup_does_not_hide_today_download_residual(self):
        with tempfile.TemporaryDirectory() as download_dir, tempfile.TemporaryDirectory() as backup_dir:
            day = date(2026, 8, 18)
            backup_target = Path(backup_dir) / "dunhill_BI订单源"
            backup_target.mkdir()
            (backup_target / "BI_tm_t01_trade_order_line_20260817.xlsx").touch()

            download = Path(download_dir) / "BI_tm_t01_trade_order_line_20260818.xlsx"
            download.touch()
            timestamp = datetime(2026, 8, 18, 9, 20).timestamp()
            os.utime(download, (timestamp, timestamp))

            residuals = find_step1_upload_residuals(download_dir, day, backup_dir)

        self.assertEqual([item["name"] for item in residuals], [download.name])

    def test_exact_backup_file_proves_today_download_was_uploaded(self):
        with tempfile.TemporaryDirectory() as download_dir, tempfile.TemporaryDirectory() as backup_dir:
            day = date(2026, 8, 18)
            filename = "BI_tm_t01_trade_order_line_20260818.xlsx"
            backup_target = Path(backup_dir) / "dunhill_BI订单源"
            backup_target.mkdir()
            (backup_target / filename).touch()

            download = Path(download_dir) / filename
            download.touch()
            timestamp = datetime(2026, 8, 18, 9, 20).timestamp()
            os.utime(download, (timestamp, timestamp))

            residuals = find_step1_upload_residuals(download_dir, day, backup_dir)

        self.assertEqual(residuals, [])

    def test_same_backup_name_with_different_content_does_not_prove_upload(self):
        with tempfile.TemporaryDirectory() as download_dir, tempfile.TemporaryDirectory() as backup_dir:
            day = date(2026, 8, 18)
            filename = "BI_tm_t01_trade_order_line_20260818.xlsx"
            backup_target = Path(backup_dir) / "dunhill_BI订单源"
            backup_target.mkdir()
            (backup_target / filename).write_bytes(b"old")

            download = Path(download_dir) / filename
            download.write_bytes(b"new")
            timestamp = datetime(2026, 8, 18, 9, 20).timestamp()
            os.utime(download, (timestamp, timestamp))

            residuals = find_step1_upload_residuals(download_dir, day, backup_dir)

        self.assertEqual([item["name"] for item in residuals], [filename])

    def test_yesterday_named_quickbi_file_is_not_a_today_source_even_if_touched_today(self):
        with tempfile.TemporaryDirectory() as download_dir, tempfile.TemporaryDirectory() as backup_dir:
            day = date(2026, 8, 18)
            download = Path(download_dir) / "BI_tm_t01_trade_order_line_20260817.xlsx"
            download.touch()
            timestamp = datetime(2026, 8, 18, 9, 20).timestamp()
            os.utime(download, (timestamp, timestamp))

            residuals = find_step1_upload_residuals(download_dir, day, backup_dir)

        self.assertEqual(residuals, [])

    def test_dtc_quickbi_file_is_part_of_upload_residual_gate(self):
        with tempfile.TemporaryDirectory() as download_dir, tempfile.TemporaryDirectory() as backup_dir:
            day = date(2026, 8, 18)
            download = Path(download_dir) / "BI_dtc_t01_trade_order_line_20260818.xlsx"
            download.touch()
            timestamp = datetime(2026, 8, 18, 9, 20).timestamp()
            os.utime(download, (timestamp, timestamp))

            residuals = find_step1_upload_residuals(download_dir, day, backup_dir)

        self.assertEqual([item["name"] for item in residuals], [download.name])

    def test_empty_live_order_is_valid_no_data_without_backup(self):
        import pandas as pd

        with tempfile.TemporaryDirectory() as download_dir, tempfile.TemporaryDirectory() as backup_dir:
            day = date(2026, 8, 18)
            download = Path(download_dir) / "直播间成交订单明细 2026-08-17.xlsx"
            pd.DataFrame(columns=["订单号"]).to_excel(download, index=False)
            timestamp = datetime(2026, 8, 18, 9, 20).timestamp()
            os.utime(download, (timestamp, timestamp))

            residuals = find_step1_upload_residuals(download_dir, day, backup_dir)

        self.assertEqual(residuals, [])

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

    def test_tm_order_reconciliation_requires_every_source_key_in_database(self):
        source_keys = {("order-1", "line-1"), ("order-2", "line-2")}

        self.assertFalse(tm_order_import_complete(source_keys, {("order-1", "line-1")}))
        self.assertTrue(tm_order_import_complete(source_keys, source_keys))


if __name__ == "__main__":
    unittest.main()
