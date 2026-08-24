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

    def test_every_step1_download_source_has_upload_chain(self):
        # 一致性锚点：每个 step1 下载源（quickbi_browser.* 是 quickbi_api 的兜底除外）
        # 必须出现在 source_tasks 并拥有 verify→upload→reconcile 链，
        # 否则下载的文件会躺在 Downloads 里永远不入库（2026-08-21 千牛退款源事故）
        specs = build_task_specs(test_mode=True)
        download_sources = [
            task_id
            for task_id in specs
            if task_id in ("refund_export", "live_export", "sycm_download")
            or task_id.startswith(("jycm_download.", "quickbi_api."))
        ]
        self.assertTrue(download_sources)
        for source in download_sources:
            self.assertIn(f"targeted_upload.{source}", specs, f"{source} 缺少上传任务")
            self.assertIn(f"source_verify.{source}", specs, f"{source} 缺少验证任务")
            self.assertIn(f"database_reconcile.{source}", specs, f"{source} 缺少对账任务")
            self.assertEqual(
                specs[f"targeted_upload.{source}"].deps,
                (f"source_verify.{source}",),
            )
            self.assertEqual(
                specs[f"database_reconcile.{source}"].deps,
                (f"targeted_upload.{source}",),
            )
            if source.startswith("quickbi_api."):
                name = source.split(".", 1)[1]
                # browser 兜底必须挂在 API 之后，且 verify 同时依赖两者（任一通道产出即可上传）
                self.assertEqual(
                    specs[f"quickbi_browser.{name}"].deps,
                    (source,),
                )
                self.assertIn(f"quickbi_browser.{name}", specs[f"source_verify.{source}"].deps)

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
