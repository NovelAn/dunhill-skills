"""Task adapters that wrap existing Dunhill scripts without duplicating them."""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable

from scripts.workflow_dag import TaskResult


QUICKBI_PREFIXES = {
    "tm_order": "BI_tm_t01_trade_order_line",
    "tm_refund_success": "BI_tm_trade_refund_info_allsuc_filter",
    "tm_refund_pending": "BI_tm_trade_refund_info_paydate_filter",
    "dtc_order": "BI_dtc_t01_trade_order_line",
    "dtc_refund": "BI_dtc_t01_trade_refund_info_allsuc_filter",
}


def run_command(command: list[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def step1_command(task_id: str, root_dir: Path, timeout: int = 420) -> list[str]:
    script = root_dir / "scripts" / "step1_collect_data.py"
    command = [sys.executable, "-u", str(script), "--timeout", str(timeout)]
    if task_id == "refund_export":
        return [*command, "--skip-live", "--skip-quickbi"]
    if task_id == "live_export":
        return [*command, "--skip-refund", "--skip-quickbi"]
    prefix = "quickbi_browser."
    if task_id.startswith(prefix) and task_id[len(prefix):] in QUICKBI_PREFIXES:
        return [
            *command,
            "--skip-refund",
            "--skip-live",
            "--quickbi-sources",
            task_id[len(prefix):],
        ]
    raise ValueError(f"Unsupported Step 1 task: {task_id}")


def _files_matching(download_dir: Path, task_id: str, before: set[Path]) -> list[Path]:
    if task_id == "refund_export":
        candidates: Iterable[Path] = download_dir.glob("*.xlsx")
        candidates = [path for path in candidates if re.match(r"^\d+_\d+_\d+\.xlsx$", path.name)]
    elif task_id == "live_export":
        candidates = [
            path
            for pattern in ("直播间大盘数据-*.xlsx", "直播分场次效果*.xlsx", "*订单明细*.xlsx", "*成交订单明细*.xlsx")
            for path in download_dir.glob(pattern)
        ]
    else:
        source = task_id.split(".", 1)[1]
        prefix = QUICKBI_PREFIXES[source]
        candidates = download_dir.glob(f"{prefix}*.xlsx")
    return sorted({path for path in candidates if path.is_file() and path not in before}, key=lambda path: path.stat().st_mtime)


def _error_type(output: str) -> str:
    lowered = output.lower()
    if any(marker in lowered for marker in ("login", "auth", "登录", "cookie")):
        return "auth_required"
    if any(marker in lowered for marker in ("timeout", "timed out", "connection", "net::err")):
        return "transient_network"
    return "file_error"


def run_step1_task(task_id: str, root_dir: Path, download_dir: Path, timeout: int = 420) -> TaskResult:
    before = {path for path in download_dir.glob("*.xlsx") if path.is_file()}
    started = time.time()
    try:
        result = run_command(step1_command(task_id, root_dir, timeout), root_dir, timeout + 30)
    except subprocess.TimeoutExpired as error:
        return TaskResult.failed(task_id, "transient_network", retryable=True, evidence={"message": str(error)})

    output = f"{result.stdout}\n{result.stderr}"
    outputs = _files_matching(download_dir, task_id, before)
    if result.returncode != 0:
        return TaskResult.failed(task_id, _error_type(output), retryable=_error_type(output) == "transient_network", evidence={"exit_code": result.returncode, "log_tail": output[-1000:]})
    if outputs:
        return TaskResult.success(task_id, outputs=[str(path) for path in outputs], evidence={"new_files": len(outputs), "duration_seconds": round(time.time() - started, 2)})
    if re.search(r'"rows"\s*:\s*0|rows\s*[:=]\s*0|无数据|no data', output, re.IGNORECASE):
        return TaskResult.no_data(task_id, evidence={"rows": 0, "confirmed_by": "export_log"})
    return TaskResult.failed(task_id, "file_error", evidence={"message": "command succeeded but produced no new source file"})

