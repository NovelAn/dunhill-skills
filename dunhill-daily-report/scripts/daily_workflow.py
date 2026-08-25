"""Task graph entrypoint; legacy execution remains the migration fallback."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.workflow_dag import DagRunner, TaskResult, TaskSpec, atomic_write_json
from scripts.workflow_tasks import run_step1_task, run_step2_task
from scripts.daily_orchestrator import load_config, send_lark_success_notification, write_summary


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

    def run(context):
        return run_step2_task(task_id, ROOT_DIR, upstream_state=getattr(context, "state", None))

    return run


def build_task_specs(test_mode: bool = False) -> dict[str, TaskSpec]:
    runner = _test_runner if test_mode else _real_runner
    specs: dict[str, TaskSpec] = {}

    specs["taobao_auth_check"] = TaskSpec("taobao_auth_check", resources=("chrome_mcp",), runner=runner("taobao_auth_check"))

    # Step1 源先行（千牛退款 + 直播），Step2 下载源等它们完成后再跑
    step1_sources: tuple[str, ...] = ("refund_export", "live_export")
    for task_id in step1_sources:
        task_runner = runner(task_id) if test_mode else _step1_runner(task_id)
        specs[task_id] = TaskSpec(task_id, resources=("chrome_mcp", "browser_downloads"), runner=task_runner)

    for report_id in JYCM_REPORTS:
        task_id = f"jycm_download.{report_id}"
        specs[task_id] = TaskSpec(task_id, deps=step1_sources, resources=("browser_downloads",), runner=runner(task_id))
    specs["sycm_download"] = TaskSpec(
        "sycm_download", deps=("taobao_auth_check", *step1_sources), resources=("chrome_mcp",), runner=runner("sycm_download")
    )
    for source in QUICKBI_SOURCES:
        # quickbi_crawler 锁：manage.py quickbi 一次抓全部 5 个源，并行跑会并发写同一批文件
        # （2026-08-22 verify glob 落空的根源）。串行后第一个跑完整爬虫，其余看到文件即秒回。
        specs[f"quickbi_api.{source}"] = TaskSpec(
            f"quickbi_api.{source}", deps=step1_sources, resources=("quickbi_crawler",), runner=runner(f"quickbi_api.{source}")
        )
    for source in QUICKBI_SOURCES:
        # quickbi_browser 是 quickbi_api 的兜底（预览 50 行上限，超过则浏览器导出全量）；
        # 挂在 API 之后，且上传链同时依赖两者——否则浏览器下载的文件没人消费
        task_id = f"quickbi_browser.{source}"
        task_runner = runner(task_id) if test_mode else _step1_runner(task_id)
        specs[task_id] = TaskSpec(task_id, deps=(f"quickbi_api.{source}",), resources=("chrome_mcp", "browser_downloads"), runner=task_runner)

    source_tasks = [
        "refund_export",  # 千牛后台退款导出（主退款源，必须每天入库）
        "live_export",  # 直播大盘/场次/订单明细
        *(f"jycm_download.{report_id}" for report_id in JYCM_REPORTS),
        "sycm_download",
        *(f"quickbi_api.{source}" for source in QUICKBI_SOURCES),
    ]
    reconciliation_tasks = []
    for source_task in source_tasks:
        verify = f"source_verify.{source_task}"
        upload = f"targeted_upload.{source_task}"
        reconcile = f"database_reconcile.{source_task}"
        # quickbi 源的 verify 额外依赖 browser 兜底：两条通道任一产出文件即可上传
        verify_deps = (
            (source_task, f"quickbi_browser.{source_task.split('.', 1)[1]}")
            if source_task.startswith("quickbi_api.")
            else (source_task,)
        )
        specs[verify] = TaskSpec(verify, deps=verify_deps, runner=runner(verify))
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


def _task_step(task_id: str) -> str:
    # Step1 = 千牛退款 + 直播浏览器导出；quickbi_browser 是 Step2 QuickBI ≥50 行时的兜底，归 Step2
    if task_id in {"refund_export", "live_export"}:
        return "step1"
    return "step2"


def _step_state(state: dict, step: str) -> dict:
    task_ids = [task_id for task_id in state.get("tasks", {}) if _task_step(task_id) == step]
    statuses = [state["tasks"][task_id].get("status") for task_id in task_ids]
    failed = [task_id for task_id in task_ids if state["tasks"][task_id].get("status") in {"failed", "blocked"}]
    if failed:
        return {
            "status": "failed",
            "needs_action": [f"{task_id}: {state['tasks'][task_id].get('error_type', 'failed')}" for task_id in failed],
        }
    if any(status not in {"success", "no_data", "skipped"} for status in statuses):
        return {"status": "running", "needs_action": []}
    return {"status": "success", "needs_action": []}


def workflow_complete(state: dict) -> bool:
    statuses = [receipt.get("status") for receipt in state.get("tasks", {}).values()]
    return bool(statuses) and all(status in {"success", "no_data", "skipped"} for status in statuses)


def sync_legacy_state(state: dict) -> dict:
    """Write orchestrator-compatible fields so report_daily_status keeps working."""
    state["run_date"] = state.get("run_date") or current_run_dir().name
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    state["steps"] = {step: _step_state(state, step) for step in ("step1", "step2")}
    state["needs_action"] = sorted({hint for step in state["steps"].values() for hint in step.get("needs_action", [])})
    return state


STATUS_ICONS = {"success": "OK ", "no_data": "0  ", "failed": "FAIL", "blocked": "BLK ", "running": "RUN ", "skipped": "SKIP", "pending": ".  "}


def render_progress(state: dict) -> str:
    specs = build_task_specs(test_mode=True)
    lines = [f"Dunhill Step 1-2 DAG | run_date={state.get('run_date', '-')} | status={state.get('status', '-')}"]
    for step in ("step1", "step2"):
        lines.append("")
        lines.append(f"[{step}]")
        for task_id in specs:
            if _task_step(task_id) != step:
                continue
            receipt = state.get("tasks", {}).get(task_id, {})
            status = receipt.get("status", "pending")
            icon = STATUS_ICONS.get(status, "?   ")
            detail = receipt.get("error_type") or ""
            lines.append(f"  {icon} {task_id:<45} {detail}")
    return "\n".join(lines)


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


def watch(once: bool = False) -> int:
    state_path = current_run_dir() / "state.json"
    while True:
        if not state_path.exists():
            print(f"state not found: {state_path}")
            if once:
                return 0
            time.sleep(2)
            continue
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = {"status": "invalid_state"}
        body = render_progress(state)
        if once:
            print(body)
            return 0
        print("\033[2J\033[H" + body + "\n(refresh 2s, ctrl-c to quit)")
        if state.get("status") in {"success", "failed"}:
            return 0
        time.sleep(2)


def legacy_run(args: list[str] | None = None) -> int:
    command = [sys.executable, "-u", str(ROOT_DIR / "scripts" / "daily_orchestrator.py"), *args]
    return subprocess.run(command, cwd=str(ROOT_DIR)).returncode


def _failed_with_descendants(state: dict, specs: dict[str, TaskSpec]) -> set[str]:
    selected = {task_id for task_id, receipt in state.get("tasks", {}).items() if receipt.get("status") == "failed"}
    changed = True
    while changed:
        changed = False
        for task_id, spec in specs.items():
            if task_id not in selected and any(dep in selected for dep in spec.deps):
                selected.add(task_id)
                changed = True
    return selected


def run_workflow(selected: set[str] | None = None) -> int:
    run_dir = current_run_dir()
    state_path = run_dir / "state.json"
    specs = build_task_specs(test_mode=False)
    if selected is None and state_path.exists():
        try:
            previous = json.loads(state_path.read_text(encoding="utf-8"))
            selected = _failed_with_descendants(previous, specs) or None
        except (OSError, json.JSONDecodeError):
            pass
    state = DagRunner(specs, state_path).run(selected=selected)
    state = sync_legacy_state(state)
    atomic_write_json(state_path, state)
    write_summary(run_dir, state)
    if workflow_complete(state) and state.get("status") == "success":
        state["notification"] = send_lark_success_notification(load_config(), state, run_dir, dry_run=False)
    else:
        state["notification"] = None
    atomic_write_json(state_path, state)
    write_summary(run_dir, state)
    print("\n" + "=" * 70)
    print(render_progress(state))
    return 0 if state.get("status") == "success" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dunhill resumable Step 1-2 workflow")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    subparsers.add_parser("run")
    subparsers.add_parser("resume")
    watch_parser = subparsers.add_parser("watch")
    watch_parser.add_argument("--once", action="store_true")
    retry = subparsers.add_parser("retry")
    retry.add_argument("task_id")
    subparsers.add_parser("retry-failed")
    subparsers.add_parser("legacy")
    args = parser.parse_args(argv)

    if args.command == "status":
        return status()
    if args.command == "watch":
        return watch(once=args.once)
    if os.environ.get("DUNHILL_WORKFLOW_TEST_MODE") == "1":
        state_path = current_run_dir() / "state.json"
        state = DagRunner(build_task_specs(test_mode=True), state_path).run()
        state = sync_legacy_state(state)
        atomic_write_json(state_path, state)
        return 0
    if args.command == "run":
        return run_workflow()
    if args.command == "resume":
        return run_workflow()
    if args.command == "retry":
        return run_workflow(selected={args.task_id})
    if args.command == "retry-failed":
        state_path = current_run_dir() / "state.json"
        specs = build_task_specs(test_mode=False)
        state = json.loads(state_path.read_text(encoding="utf-8"))
        return run_workflow(selected=_failed_with_descendants(state, specs))
    if args.command == "legacy":
        return legacy_run([])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
