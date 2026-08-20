"""Task adapters that wrap existing Dunhill scripts without duplicating them."""

from __future__ import annotations

import re
import subprocess
import sys
import time
from datetime import date
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

DATA_IMPORT_DIR = Path("/Users/novel/Projects/data-import")
DATA_IMPORT_PYTHON = DATA_IMPORT_DIR / ".venv" / "bin" / "python"

JYCM_SAVE_NAMES = {
    "445603": "dunhill_shop_d_recent_30d_",
    "225266": "dunhill_traffic_d_recent_1d_",
    "446524": "dunhill_client_d_recent_30d_",
    "445350": "dunhill_product_d_recent_1d_",
    "458866": "dunhill_product_traffic_d_recent_1d_",
}

QUICKBI_UPLOAD_TARGETS = {
    "tm_order": "dunhill_BI订单源",
    "tm_refund_success": "dunhill_TM退款源_hive",
    "tm_refund_pending": "dunhill_TM退款源_hive",
    "dtc_order": "dunhill_DTC订单源_hive",
    "dtc_refund": "dunhill_DTC退款源",
}

# ponytail: reconcile v1 uses backup-file evidence except tm_order (real DB keys);
# add per-source SQL counts when a source is proven to drift.
BACKUP_TARGETS = {
    "445603": "dunhill_tm取数源_backup",
    "225266": "dunhill_tm流量源_new",
    "445350": "dunhill_tm商品源",
    "458866": "dunhill_tm商品流量源",
    "tm_order": "dunhill_BI订单源",
    "tm_refund_success": "dunhill_TM退款源_hive",
    "tm_refund_pending": "dunhill_TM退款源_hive",
    "dtc_order": "dunhill_DTC订单源_hive",
    "dtc_refund": "dunhill_DTC退款源",
}

STEP2_TIMEOUTS = {
    "jycm": 900,
    "sycm": 1800,
    "quickbi": 1800,
    "upload": 1800,
    "reconcile": 900,
    "crawler": 1800,
    "alimama": 1800,
}


def _manage(*args: str) -> list[str]:
    return [str(DATA_IMPORT_PYTHON), "manage.py", *args]


def _uploader(*args: str) -> list[str]:
    return [str(DATA_IMPORT_PYTHON), "-m", "data_pipeline.processors.file_uploader", *args]


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


def step2_command(task_id: str, run_day: date) -> tuple[list[str], int] | None:
    """Map a Step 2 DAG task to one existing data-import command."""
    today = run_day.strftime("%Y%m%d")
    if task_id.startswith("jycm_download."):
        report_id = task_id.split(".", 1)[1]
        save_name = JYCM_SAVE_NAMES.get(report_id)
        if not save_name:
            return None
        return _manage("jycm", report_id, save_name + today), STEP2_TIMEOUTS["jycm"]
    if task_id == "sycm_download":
        return _manage("sycm", "shop"), STEP2_TIMEOUTS["sycm"]
    if task_id.startswith("quickbi_api."):
        return _manage("quickbi"), STEP2_TIMEOUTS["quickbi"]
    if task_id.startswith("targeted_upload."):
        source_task = task_id.split(".", 1)[1]
        if source_task.startswith("jycm_download."):
            template = JYCM_SAVE_NAMES[source_task.split(".", 1)[1]]
            return _uploader("--template", template), STEP2_TIMEOUTS["upload"]
        if source_task == "sycm_download":
            return _manage("upload", "-m", "modules.dunhill.ali.sycm"), STEP2_TIMEOUTS["upload"]
        source = source_task.split(".", 1)[1]
        return _uploader("--target", QUICKBI_UPLOAD_TARGETS[source]), STEP2_TIMEOUTS["upload"]
    if task_id == "unmask_buyer_nicknames":
        return _manage("order", "update_mask"), STEP2_TIMEOUTS["reconcile"]
    if task_id == "fq_crawler":
        return _manage("order", "fq"), STEP2_TIMEOUTS["crawler"]
    if task_id == "nickname_crawler":
        return _manage("order", "nick"), STEP2_TIMEOUTS["crawler"]
    if task_id == "pfs_buyer_type":
        return _manage("order", "update_pfs"), STEP2_TIMEOUTS["crawler"]
    if task_id == "dtc_buyer_type":
        return _manage("order", "update_dtc"), STEP2_TIMEOUTS["crawler"]
    if task_id == "alimama_auth_refresh_if_needed":
        return _manage("alimama", "--refresh-auth"), 600
    if task_id == "alimama_import":
        return _manage("alimama"), STEP2_TIMEOUTS["alimama"]
    return None


def _source_file_token(source_task: str, run_day: date) -> tuple[str, str] | None:
    """Return (glob prefix, backup target) for verify/reconcile tasks."""
    today = run_day.strftime("%Y%m%d")
    if source_task.startswith("jycm_download."):
        report_id = source_task.split(".", 1)[1]
        save_name = JYCM_SAVE_NAMES.get(report_id)
        if not save_name:
            return None
        return save_name + today + "*.xlsx", BACKUP_TARGETS.get(report_id, "")
    if source_task == "sycm_download":
        return "dunhill_*d_*" + today + "*.xlsx", "dunhill_tm取数源_backup"
    if source_task.startswith("quickbi_api."):
        source = source_task.split(".", 1)[1]
        prefix = QUICKBI_PREFIXES[source]
        return prefix + "*.xlsx", BACKUP_TARGETS[source]
    return None


def _download_dir() -> Path:
    return Path(__import__("os").environ.get("DOWNLOAD_DIR", str(Path.home() / "Downloads")))


def _default_save_path() -> Path:
    from scripts.step2_run_import import get_default_save_path

    return Path(get_default_save_path())


def run_step2_task(task_id: str, root_dir: Path) -> TaskResult:
    run_day = date.today()
    started = time.time()

    if task_id in ("taobao_auth_check", "alimama_auth_check", "database_reconcile"):
        # Gates enforced through dependent command exit codes / dependency status.
        return TaskResult.success(task_id, evidence={"gate": "delegated"})

    if task_id.startswith("source_verify."):
        source_task = task_id.split(".", 1)[1]
        token = _source_file_token(source_task, run_day)
        if not token:
            return TaskResult.failed(task_id, "migration_pending", evidence={"message": f"no source mapping for {source_task}"})
        pattern, _ = token
        files = sorted(_download_dir().glob(pattern))
        if files:
            return TaskResult.success(task_id, outputs=[str(path) for path in files], evidence={"files": [path.name for path in files]})
        return TaskResult.failed(task_id, "file_error", evidence={"message": f"no download matching {pattern}"})

    if task_id.startswith("database_reconcile."):
        source_task = task_id.split(".", 1)[1]
        token = _source_file_token(source_task, run_day)
        if not token:
            return TaskResult.failed(task_id, "migration_pending", evidence={"message": f"no source mapping for {source_task}"})
        pattern, backup_target = token
        if source_task == "quickbi_api.tm_order":
            from scripts.step2_run_import import verify_tm_order_database

            ok, detail = verify_tm_order_database(DATA_IMPORT_DIR, run_day)
            if not ok:
                return TaskResult.failed(task_id, "database_error", retryable=True, evidence={"message": detail})
            return TaskResult.success(task_id, evidence={"reconciled": detail})
        if backup_target and list((_default_save_path() / backup_target).glob(pattern)):
            return TaskResult.success(task_id, evidence={"backup": backup_target, "pattern": pattern})
        return TaskResult.failed(task_id, "file_error", retryable=True, evidence={"message": f"backup missing: {backup_target or '?'}/{pattern}"})

    if task_id.startswith("quickbi_api."):
        source = task_id.split(".", 1)[1]
        pattern = QUICKBI_PREFIXES[source] + run_day.strftime("%Y%m%d") + "*.xlsx"
        if list(_download_dir().glob(pattern)):
            # The crawler downloads all five sources at once; reuse them per source.
            return TaskResult.success(task_id, outputs=[str(path) for path in _download_dir().glob(pattern)], evidence={"already_downloaded": pattern})

    mapping = step2_command(task_id, run_day)
    if mapping is None:
        return TaskResult.failed(task_id, "migration_pending", evidence={"message": "no adapter yet"})
    command, timeout = mapping
    env = {**__import__("os").environ, "PYTHONPATH": str(DATA_IMPORT_DIR / "src")}
    try:
        result = subprocess.run(
            command,
            cwd=str(DATA_IMPORT_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as error:
        return TaskResult.failed(task_id, "transient_network", retryable=True, evidence={"message": str(error)})
    output = f"{result.stdout}\n{result.stderr}"
    if result.returncode != 0:
        error_type = _error_type(output)
        return TaskResult.failed(task_id, error_type, retryable=error_type in ("transient_network", "auth_required"), evidence={"exit_code": result.returncode, "log_tail": output[-1000:]})
    return TaskResult.success(task_id, evidence={"command": command[-3:], "duration_seconds": round(time.time() - started, 2)})
