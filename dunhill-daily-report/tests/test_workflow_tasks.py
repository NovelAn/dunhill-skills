import subprocess
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from scripts.workflow_tasks import (
    BACKUP_TARGETS,
    JYCM_SAVE_NAMES,
    QUICKBI_UPLOAD_TARGETS,
    run_step1_task,
    run_step2_task,
    step1_command,
    step2_command,
)
from data_pipeline_test_support import load_all_missions, mission_targets


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
            ), patch("scripts.workflow_tasks._default_save_path", return_value=Path(directory)):
                # browser 导出脚本 exit 0 但无新文件 = 页面查询为空 → no_data（不再是 failed）；
                # 真失败路径用非 browser 任务验证
                result = run_step1_task("refund_export", root, root)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_type, "file_error")

    def test_explicit_zero_rows_is_terminal_no_data(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with patch(
                "scripts.workflow_tasks.run_command",
                return_value=subprocess.CompletedProcess([], 0, '{"rows": 0}', ""),
            ), patch("scripts.workflow_tasks._default_save_path", return_value=Path(directory)):
                result = run_step1_task("quickbi_browser.tm_order", root, root)
        self.assertEqual(result.status, "no_data")
        self.assertEqual(result.evidence["rows"], 0)

    def test_quickbi_browser_skipped_when_api_file_already_in_downloads(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            stamp = date.today().strftime("%Y%m%d")
            (root / f"BI_tm_t01_trade_order_line_{stamp}.xlsx").touch()
            with patch("scripts.workflow_tasks._default_save_path", return_value=root):
                result = run_step1_task("quickbi_browser.tm_order", root, root)
        self.assertEqual(result.status, "skipped")

    def test_quickbi_browser_skipped_when_api_file_already_in_backup(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            backup = root / BACKUP_TARGETS["tm_order"]
            backup.mkdir(parents=True)
            stamp = date.today().strftime("%Y%m%d")
            (backup / f"BI_tm_t01_trade_order_line_{stamp}.xlsx").touch()
            with patch("scripts.workflow_tasks._default_save_path", return_value=root):
                result = run_step1_task("quickbi_browser.tm_order", Path("/nonexistent"), root)
        self.assertEqual(result.status, "skipped")

    def test_sycm_download_upload_targets_jycm_module(self):
        command, _ = step2_command("targeted_upload.sycm_download", date.today())
        self.assertIn("upload", command)
        self.assertEqual(command[-1], "modules.dunhill.ali.jycm")

    def test_quickbi_upload_targets_match_real_mission_targets(self):
        # BI_* 文件由 *_hive / BI订单源 等 mission 消费，映射必须与 modules 中的 Task target 一致
        from data_pipeline_test_support import mission_targets

        known = mission_targets()
        for source, target in QUICKBI_UPLOAD_TARGETS.items():
            self.assertIn(target, known, f"{source} -> {target} 不存在于任何 mission")
        for key, backup in BACKUP_TARGETS.items():
            if key in QUICKBI_UPLOAD_TARGETS:
                self.assertEqual(
                    backup,
                    QUICKBI_UPLOAD_TARGETS[key],
                    f"BACKUP_TARGETS[{key}] 与 QUICKBI_UPLOAD_TARGETS 不一致",
                )

    def test_jycm_save_names_match_mission_templates(self):
        # JYCM_SAVE_NAMES 的文件名前缀必须能被 mission 的正则模板 fullmatch（file_uploader --template 依赖）
        import re

        missions = load_all_missions()
        for report_id, save_name in JYCM_SAVE_NAMES.items():
            matched = [m.target for m in missions if re.fullmatch(m.file.template, save_name)]
            self.assertTrue(matched, f"{report_id}: {save_name!r} 不匹配任何 mission 模板")

    def test_daily_glob_produces_underscore_date_pattern(self):
        # 真实文件名是 prefix_YYYYMMDD.xlsx（带下划线）；JYCM 前缀自身以 _ 结尾不能产生双下划线
        from datetime import date

        from scripts.workflow_tasks import _daily_glob

        day = date(2026, 8, 21)
        self.assertEqual(_daily_glob("BI_tm_t01_trade_order_line", day), "BI_tm_t01_trade_order_line_20260821*.xlsx")
        self.assertEqual(_daily_glob("dunhill_shop_d_recent_30d_", day), "dunhill_shop_d_recent_30d_20260821*.xlsx")

    def test_taobao_auth_check_runs_real_health_check(self):
        # 门禁必须真的调用 data-import 的 check_taobao_cookie_health，不许再退化为恒真
        with patch("scripts.workflow_tasks.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess([], 1, "", "cookies expired")
            result = run_step2_task("taobao_auth_check", Path("/tmp"))
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_type, "auth_required")
        self.assertIn("check_taobao_cookie_health", mock_run.call_args.args[0][2])

    def test_download_dir_expands_tilde_from_env(self):
        # .env 注入的 DOWNLOAD_DIR=~/Downloads 若不 expanduser 就是相对路径，glob 永远为空（2026-08-22 事故根因）
        import os

        from scripts.workflow_tasks import _download_dir

        with patch.dict(os.environ, {"DOWNLOAD_DIR": "~/Downloads"}):
            self.assertEqual(_download_dir(), Path.home() / "Downloads")

    def test_quickbi_browser_skips_when_full_export_marker_exists(self):
        # resume 场景：浏览器全量导出文件行数仍 ≥50，但 truncated_previews/ 里有标记 → skip 不重导
        with TemporaryDirectory() as directory:
            root = Path(directory)
            stamp = date.today().strftime("%Y%m%d")
            from scripts.workflow_tasks import QUICKBI_PREVIEW_LIMIT

            source_rows = pd.DataFrame({"a": range(QUICKBI_PREVIEW_LIMIT + 10)})
            source_rows.to_excel(root / f"BI_tm_t01_trade_order_line_{stamp}.xlsx", index=False)
            (root / "truncated_previews").mkdir()
            (root / "truncated_previews" / f"BI_tm_t01_trade_order_line_{stamp}.xlsx").touch()
            with patch("scripts.workflow_tasks._default_save_path", return_value=root):
                result = run_step1_task("quickbi_browser.tm_order", root, root)
        self.assertEqual(result.status, "skipped")
        self.assertTrue(result.evidence.get("full_export"))


if __name__ == "__main__":
    unittest.main()
