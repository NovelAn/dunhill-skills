"""Task graph entrypoint; legacy execution remains the migration fallback."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable

from scripts.workflow_dag import DagRunner, TaskResult, TaskSpec, atomic_write_json
from scripts.workflow_tasks import run_step1_task, run_step2_task


ROOT_DIR = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT_DIR / "runs"
JYCM_REPORTS = ("445603", "225266", "446524", "445350", "458866")
QUICKBI_SOURCES = ("tm_order", "tm_refund_success", "tm_refund_pending", "dtc_order", "dtc_refund")


def _test_runner(task_id: str) -> Callable:
    def run(_context):
        return TaskResult.success(task_id, evidence={"test_mode": True})

    return run


def _step1_runner(task_id: str) -> Callable:
    def run(_context):
        download_dir = Path(os.environ.get("DOWNLOAD_DIR", str(Path.home() / "Downloads")))
        return run_step1_task(task_id, ROOT_DIR, download_dir)

    return run


def _real_runner(task_id: str) -> Callable:
    if task_id in (
        "refund_export",
        "live_export",
        *(f"quickbi_browser.{source}" for source in QUICKBI_SOURCES),
    ):
        return _step1_runner(task_id)

    def run(_context):
        return run_step2_task(task_id, ROOT_DIR)

    return run


def build_task_specs(test_mode: bool = False) -> dict[str, TaskSpec]:
    runner = _test_runner if test_mode else _real_runner
    specs: dict[str, TaskSpec] = {}

    for task_id in (
        "refund_export",
        "live_export",
        *(f"quickbi_browser.{source}" for source in QUICKBI_SOURCES),
    ):
        task_runner = runner(task_id) if test_mode else _step1_runner(task_id)
        specs[task_id] = TaskSpec(task_id, resources=("chrome_mcp", "browser_downloads"), runner=task_runner)

    specs["taobao_auth_check"] = TaskSpec("taobao_auth_check", resources=("chrome_mcp",), runner=runner("taobao_auth_check"))
    for report_id in JYCM_REPORTS:
        task_id = f"jycm_download.{report_id}"
        specs[task_id] = TaskSpec(task_id, resources=("browser_downloads",), runner=runner(task_id))
    specs["sycm_download"] = TaskSpec(
        "sycm_download", deps=("taobao_auth_check",), resources=("chrome_mcp",), runner=runner("sycm_download")
    )
    for source in QUICKBI_SOURCES:
        task_id = f"quickbi_api.{source}"
        specs[task_id] = TaskSpec(task_id, runner=runner(task_id))

    source_tasks = [
        *(f"jycm_download.{report_id}" for report_id in JYCM_REPORTS),
        "sycm_download",
        *(f"quickbi_api.{source}" for source in QUICKBI_SOURCES),
    ]
    reconciliation_tasks = []
    for source_task in source_tasks:
        verify = f"source_verify.{source_task}"
        upload = f"targeted_upload.{source_task}"
        reconcile = f"database_reconcile.{source_task}"
        specs[verify] = TaskSpec(verify, deps=(source_task,), runner=runner(verify))
        specs[upload] = TaskSpec(upload, deps=(verify,), resources=("mysql_upload",), runner=runner(upload))
        specs[reconcile] = TaskSpec(reconcile, deps=(upload,), resources=("mysql_upload",), runner=runner(reconcile))
        reconciliation_tasks.append(reconcile)

    specs["database_reconcile"] = TaskSpec(
        "database_reconcile", deps=tuple(reconciliation_tasks), runner=runner("database_reconcile")
    )
    specs["unmask_buyer_nicknames"] = TaskSpec(
        "unmask_buyer_nicknames", deps=("database_reconcile",), resources=("mysql_upload",), runner=runner("unmask_buyer_nicknames")
    )
    specs["fq_crawler"] = TaskSpec(
        "fq_crawler", deps=("unmask_buyer_nicknames", "taobao_auth_check"), resources=("chrome_mcp",), runner=runner("fq_crawler")
    )
    specs["nickname_crawler"] = TaskSpec(
        "nickname_crawler", deps=("unmask_buyer_nicknames", "taobao_auth_check"), resources=("chrome_mcp",), runner=runner("nickname_crawler")
    )
    specs["pfs_buyer_type"] = TaskSpec(
        "pfs_buyer_type", deps=("database_reconcile",), resources=("mysql_upload",), runner=runner("pfs_buyer_type")
    )
    specs["dtc_buyer_type"] = TaskSpec(
        "dtc_buyer_type", deps=("database_reconcile",), resources=("mysql_upload",), runner=runner("dtc_buyer_type")
    )
    specs["alimama_auth_check"] = TaskSpec("alimama_auth_check", runner=runner("alimama_auth_check"))
    specs["alimama_auth_refresh_if_needed"] = TaskSpec(
        "alimama_auth_refresh_if_needed", deps=("alimama_auth_check",), resources=("chrome_mcp",), runner=runner("alimama_auth_refresh_if_needed")
    )
    specs["alimama_import"] = TaskSpec(
        "alimama_import", deps=("alimama_auth_refresh_if_needed",), runner=runner("alimama_import")
    )
    return specs


def current_run_dir() -> Path:
    return Path(os.environ.get("DUNHILL_RUN_DIR", str(RUNS_DIR / datetime.now().strftime("%Y-%m-%d"))))


def status() -> int:
    run_dir = current_run_dir()
    state_path = run_dir / "state.json"
    if not state_path.exists():
        print(json.dumps({"status": "not_run", "state_path": str(state_path)}, ensure_ascii=False, indent=2))
        return 0
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "invalid_state", "error": str(error), "state_path": str(state_path)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"status": state.get("status"), "state_path": str(state_path), "tasks": state.get("tasks", {})}, ensure_ascii=False, indent=2))
    return 0


def legacy_run(args: list[str]) -> int:
    command = [sys.executable, "-u", str(ROOT_DIR / "scripts" / "daily_orchestrator.py"), *args]
    return subprocess.run(command, cwd=str(ROOT_DIR)).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dunhill resumable Step 1-2 workflow")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    subparsers.add_parser("run")
    subparsers.add_parser("resume")
    retry = subparsers.add_parser("retry")
    retry.add_argument("task_id")
    subparsers.add_parser("retry-failed")
    args = parser.parse_args(argv)

    if args.command == "status":
        return status()
    if os.environ.get("DUNHILL_WORKFLOW_TEST_MODE") == "1":
        state_path = current_run_dir() / "state.json"
        state = DagRunner(build_task_specs(test_mode=True), state_path).run()
        atomic_write_json(state_path, state)
        return 0
    # ponytail: keep one safe migration fallback until all real task adapters have parity.
    return legacy_run([])


if __name__ == "__main__":
    raise SystemExit(main())
