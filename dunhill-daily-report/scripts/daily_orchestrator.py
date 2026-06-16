"""
Dunhill daily report orchestrator for Mac Step 1-2 automation.

The orchestrator keeps a per-run state file, supports resume/partial runs, and
stops after Step 2 on macOS because Steps 3-5 require Windows Excel Power Query.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT_DIR / "scripts"
RUNS_DIR = ROOT_DIR / "runs"
CONFIG_PATH = ROOT_DIR / "config" / "dunhill-config.yaml"
STEPS = ["step1", "step2"]
RETRYABLE_FAILURE_MARKERS = (
    "timed out",
    "timeout",
    "playwright mcp extension",
    "playwright mcp exited",
    "pending client connection closed",
    "target page, context or browser has been closed",
    "execution context was destroyed",
    "protocol error",
    "connection closed",
    "connection refused",
    "econnreset",
    "net::err",
)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def ensure_runtime_python(argv: list[str]) -> None:
    for env_path in (
        ROOT_DIR / ".env",
        Path.home() / ".claude" / "skills" / ".env",
        Path.home() / ".claude" / "skills" / "dunhill-skills" / ".env",
    ):
        _load_env_file(env_path)

    etl_dir = Path(os.path.expanduser(os.environ.get("ETL_PIPELINES_DIR", "~/projects/data-import")))
    venv_python = etl_dir / ".venv" / "bin" / "python"
    if not venv_python.exists():
        return

    current_python = Path(sys.executable).resolve()
    if current_python == venv_python.resolve():
        return

    os.execv(str(venv_python), [str(venv_python), "-u", __file__, *argv])


def ensure_caffeinated(argv: list[str]) -> None:
    if platform.system() != "Darwin":
        return
    if os.environ.get("DUNHILL_ORCHESTRATOR_CAFFEINATED") == "1":
        return
    if "--no-caffeinate" in argv:
        return
    caffeinate = "/usr/bin/caffeinate"
    if not Path(caffeinate).exists():
        return

    env = os.environ.copy()
    env["DUNHILL_ORCHESTRATOR_CAFFEINATED"] = "1"
    command = [caffeinate, "-dimsu", sys.executable, "-u", __file__, *argv]
    os.execvpe(caffeinate, command, env)


def load_state(path: Path, run_date: str) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {
        "run_date": run_date,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "status": "pending",
        "steps": {},
    }


def load_config() -> dict:
    import yaml

    if not CONFIG_PATH.exists():
        return {}
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_state(path: Path, state: dict) -> None:
    state["updated_at"] = now_iso()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def selected_steps(args: argparse.Namespace) -> list[str]:
    steps = [item.strip() for item in args.steps.split(",") if item.strip()]
    invalid = [step for step in steps if step not in STEPS]
    if invalid:
        raise SystemExit(f"Unsupported step(s): {', '.join(invalid)}")

    if args.only:
        if args.only not in STEPS:
            raise SystemExit(f"Unsupported --only step: {args.only}")
        steps = [args.only]

    if args.from_step:
        if args.from_step not in STEPS:
            raise SystemExit(f"Unsupported --from step: {args.from_step}")
        start_index = steps.index(args.from_step) if args.from_step in steps else STEPS.index(args.from_step)
        ordered = [step for step in STEPS[start_index:] if step in steps or not args.only]
        steps = ordered

    return steps


def step_command(step: str, args: argparse.Namespace) -> list[str]:
    if step == "step1":
        return [sys.executable, "-u", str(SCRIPT_DIR / "step1_collect_data.py")]
    if step == "step2":
        command = [sys.executable, "-u", str(SCRIPT_DIR / "step2_run_import.py")]
        if args.refresh_alimama_auth_first:
            command.append("--refresh-alimama-auth-first")
        if args.skip_alimama:
            command.append("--skip-alimama")
        return command
    raise ValueError(f"Unsupported step: {step}")


def classify_failure(log_path: Path) -> list[str]:
    if not log_path.exists():
        return ["未找到日志文件，请检查脚本是否启动成功。"]
    text = log_path.read_text(encoding="utf-8", errors="replace")
    hints = []
    if "PLAYWRIGHT_MCP_EXTENSION" in text or "Playwright MCP Extension" in text:
        hints.append("检查 Chrome Playwright Extension 是否已连接，并确认 token 可用。")
    if "cookies 已过期" in text or "login" in text.lower():
        hints.append("检查千牛/淘宝登录态；必要时在本机 Chrome 完成登录后重试。")
    if "csrf" in text.lower() or "阿里妈妈" in text and "失败" in text:
        hints.append("检查阿里妈妈页面是否已在本机 Chrome 登录，或重跑 Step 2 的 auth 刷新。")
    if "QuickBI" in text and ("缺失" in text or "50" in text):
        hints.append("检查 Step 1 QuickBI 完整文件补充是否成功。")
    if not hints:
        hints.append("查看对应 step 日志中的 [FAIL]/[ERROR]/[WARN] 行定位原因。")
    return hints


def terminate_process_group(process: subprocess.Popen, grace_seconds: int = 5) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        process.terminate()
    try:
        process.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        process.kill()
    process.wait()


def is_retryable_failure(log_path: Path) -> bool:
    if not log_path.exists():
        return True
    text = log_path.read_text(encoding="utf-8", errors="replace").lower()
    return any(marker in text for marker in RETRYABLE_FAILURE_MARKERS)


def run_step(
    step: str,
    command: list[str],
    run_dir: Path,
    state: dict,
    dry_run: bool,
    attempt: int,
) -> bool:
    logs_dir = run_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"{step}.log" if attempt == 1 else logs_dir / f"{step}_attempt{attempt}.log"

    previous_attempts = state.get("steps", {}).get(step, {}).get("attempts", [])
    attempt_state = {
        "attempt": attempt,
        "status": "running",
        "started_at": now_iso(),
        "ended_at": None,
        "duration_seconds": None,
        "exit_code": None,
        "log_path": str(log_path),
        "retryable": None,
    }

    step_state = {
        "status": "running",
        "attempt": attempt,
        "started_at": now_iso(),
        "ended_at": None,
        "duration_seconds": None,
        "command": command,
        "exit_code": None,
        "log_path": str(log_path),
        "needs_action": [],
        "attempts": [*previous_attempts, attempt_state],
    }
    state["steps"][step] = step_state
    save_state(run_dir / "state.json", state)

    print("\n" + "=" * 70)
    print(f"Running {step} attempt {attempt}: {' '.join(command)}")
    print("=" * 70)

    if dry_run:
        updates = {
            "status": "skipped",
            "ended_at": now_iso(),
            "duration_seconds": 0,
            "exit_code": 0,
            "retryable": False,
        }
        step_state.update(updates)
        attempt_state.update(updates)
        log_path.write_text("[DRY RUN] Command was not executed.\n", encoding="utf-8")
        save_state(run_dir / "state.json", state)
        return True

    start = time.time()
    process: subprocess.Popen | None = None
    try:
        with log_path.open("w", encoding="utf-8") as log_file:
            process = subprocess.Popen(
                command,
                cwd=str(ROOT_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                encoding="utf-8",
                errors="replace",
                start_new_session=True,
            )
            assert process.stdout is not None
            for line in process.stdout:
                print(line, end="")
                log_file.write(line)
                log_file.flush()
            exit_code = process.wait()
    except KeyboardInterrupt:
        if process is not None:
            terminate_process_group(process)
        duration = round(time.time() - start, 2)
        updates = {
            "status": "interrupted",
            "ended_at": now_iso(),
            "duration_seconds": duration,
            "exit_code": -signal.SIGINT,
            "retryable": False,
        }
        step_state.update(updates)
        attempt_state.update(updates)
        step_state["needs_action"] = ["运行被手动中断；已清理当前 step 子进程组。"]
        save_state(run_dir / "state.json", state)
        raise

    duration = round(time.time() - start, 2)
    retryable = exit_code != 0 and is_retryable_failure(log_path)
    updates = {
        "ended_at": now_iso(),
        "duration_seconds": duration,
        "exit_code": exit_code,
        "retryable": retryable,
    }
    step_state.update(updates)
    attempt_state.update(updates)
    if exit_code == 0:
        step_state["status"] = "success"
        attempt_state["status"] = "success"
        print(f"\n[OK] {step} completed in {duration}s")
    else:
        step_state["status"] = "failed"
        attempt_state["status"] = "failed"
        step_state["needs_action"] = classify_failure(log_path)
        print(f"\n[FAIL] {step} failed with exit code {exit_code}")
        for hint in step_state["needs_action"]:
            print(f"  - {hint}")

    save_state(run_dir / "state.json", state)
    return exit_code == 0


def run_step_with_retries(
    step: str,
    command: list[str],
    run_dir: Path,
    state: dict,
    dry_run: bool,
    retries: int,
) -> bool:
    max_attempts = max(1, retries + 1)
    for attempt in range(1, max_attempts + 1):
        success = run_step(step, command, run_dir, state, dry_run, attempt)
        if success:
            return True

        step_state = state.get("steps", {}).get(step, {})
        retryable = bool(step_state.get("retryable"))
        if dry_run or attempt >= max_attempts or not retryable:
            return False

        wait_seconds = min(20, 5 * attempt)
        print(f"[RETRY] {step} hit a transient browser/MCP failure; retrying in {wait_seconds}s.")
        step_state["next_retry_after_seconds"] = wait_seconds
        save_state(run_dir / "state.json", state)
        time.sleep(wait_seconds)

    return False


def write_summary(run_dir: Path, state: dict) -> None:
    lines = [
        f"# Dunhill Daily Run {state['run_date']}",
        "",
        f"- Status: {state.get('status')}",
        f"- Updated at: {state.get('updated_at')}",
        "",
        "## Steps",
    ]
    for step in STEPS:
        info = state.get("steps", {}).get(step, {"status": "pending"})
        lines.append(f"- {step}: {info.get('status')}")
        if info.get("duration_seconds") is not None:
            lines.append(f"  - Duration: {info.get('duration_seconds')}s")
        if info.get("log_path"):
            lines.append(f"  - Log: {info.get('log_path')}")
        for hint in info.get("needs_action", []):
            lines.append(f"  - Needs action: {hint}")

    notification = state.get("notification")
    if notification:
        lines.extend([
            "",
            "## Notification",
            f"- Lark success: {notification.get('lark_success')}",
            f"- Identity: {notification.get('identity')}",
            f"- Dry run: {notification.get('dry_run')}",
        ])
        if notification.get("message_id"):
            lines.append(f"- Message ID: {notification.get('message_id')}")
        if notification.get("sent_at"):
            lines.append(f"- Sent at: {notification.get('sent_at')}")
        if notification.get("error"):
            lines.append(f"- Error: {notification.get('error')}")

    lines.extend([
        "",
        "## Mac Boundary",
        "This orchestrator intentionally stops after Step 2 on macOS. Steps 3-5 require Windows Excel Power Query / MySQL refresh support.",
        "",
    ])
    (run_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def build_lark_post_content(config: dict, state: dict, run_dir: Path) -> str:
    lark_config = config.get("notifications", {}).get("lark", {})
    mentions = lark_config.get("mention_members", [])
    run_date = state.get("run_date") or run_dir.name

    first_line = []
    for member in mentions:
        open_id = member.get("open_id")
        name = member.get("name", "")
        if open_id:
            first_line.append({"tag": "at", "user_id": open_id, "user_name": name})
            first_line.append({"tag": "text", "text": " "})

    if not first_line:
        first_line.append({"tag": "text", "text": "各位 "})
    first_line.append({"tag": "text", "text": "dunhill的日报和订单相关数据已经更新。"})

    second_line = [{"tag": "text", "text": f"运行日期: {run_date}"}]

    content = {
        "zh_cn": {
            "title": f"Dunhill数据更新完成 {run_date}",
            "content": [first_line, second_line],
        }
    }
    return json.dumps(content, ensure_ascii=False)


def extract_json_object(output: str) -> dict | None:
    for line in reversed([item.strip() for item in output.splitlines() if item.strip()]):
        if not line.startswith("{"):
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    start = output.find("{")
    end = output.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(output[start:end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def lark_message_id(parsed: dict | None) -> str | None:
    if not parsed:
        return None
    data = parsed.get("data") if isinstance(parsed.get("data"), dict) else {}
    for container in (data, parsed):
        for key in ("message_id", "messageId", "open_message_id"):
            value = container.get(key)
            if value:
                return str(value)
    return None


def resolve_lark_cli() -> str | None:
    env_path = os.environ.get("LARK_CLI_BIN")
    candidates = [
        env_path,
        "/private/tmp/lark-cli-local/node_modules/.bin/lark-cli",
        str(Path.home() / ".local" / "bin" / "lark-cli"),
        shutil.which("lark-cli"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path.exists() and os.access(path, os.X_OK):
            return str(path)
    return None


def send_lark_success_notification(config: dict, state: dict, run_dir: Path, dry_run: bool) -> dict:
    lark_config = config.get("notifications", {}).get("lark", {})
    identity = lark_config.get("send_identity", "user")
    notification = {
        "lark_success": False,
        "identity": identity,
        "dry_run": bool(dry_run),
        "sent_at": now_iso(),
    }
    if not lark_config.get("enabled", False):
        print("[INFO] Lark notification is disabled.")
        notification.update({"lark_success": True, "skipped": True, "reason": "disabled"})
        return notification

    chat_id = lark_config.get("chat_id")
    if not chat_id:
        print("[WARN] Lark notification skipped: notifications.lark.chat_id is not configured.")
        notification["error"] = "notifications.lark.chat_id is not configured"
        return notification

    lark_cli = resolve_lark_cli()
    if not lark_cli:
        notification["error"] = "lark-cli executable not found"
        print("[WARN] Lark notification skipped: no usable lark-cli executable was found.")
        return notification
    content = build_lark_post_content(config, state, run_dir)
    run_date = str(state.get("run_date") or run_dir.name)
    idempotency_key = f"dh-{run_date.replace('-', '')}-s12"
    command = [
        lark_cli,
        "im",
        "+messages-send",
        "--as",
        identity,
        "--chat-id",
        chat_id,
        "--msg-type",
        "post",
        "--content",
        content,
        "--idempotency-key",
        idempotency_key,
    ]
    if dry_run:
        command.append("--dry-run")

    print("\n" + "=" * 70)
    print("Sending Lark success notification...")
    print("=" * 70)
    process = subprocess.run(
        command,
        cwd=str(ROOT_DIR),
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if process.stdout.strip():
        print(process.stdout.strip())
    if process.stderr.strip():
        print(process.stderr.strip())

    parsed = extract_json_object(process.stdout)
    message_id = lark_message_id(parsed)
    if message_id:
        notification["message_id"] = message_id

    if process.returncode == 0:
        print("[OK] Lark notification sent." if not dry_run else "[OK] Lark notification dry-run passed.")
        notification["lark_success"] = True
        return notification

    print(f"[WARN] Lark notification failed with exit code {process.returncode}.")
    notification["exit_code"] = process.returncode
    notification["error"] = (process.stderr.strip() or process.stdout.strip())[-1000:]
    return notification


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ensure_runtime_python(argv)
    ensure_caffeinated(argv)

    parser = argparse.ArgumentParser(description="Dunhill daily Step 1-2 orchestrator")
    parser.add_argument("--date", default=today_str(), help="Run date for state folder, default: today")
    parser.add_argument("--steps", default="step1,step2", help="Comma-separated steps, default: step1,step2")
    parser.add_argument("--from", dest="from_step", help="Resume from this step")
    parser.add_argument("--only", help="Run only one step")
    parser.add_argument("--force", action="store_true", help="Re-run steps even if state already says success")
    parser.add_argument("--dry-run", action="store_true", help="Print and record steps without executing")
    parser.add_argument("--step-retries", type=int, default=1,
                        help="Retry each failed step this many times for transient browser/MCP failures")
    parser.add_argument("--no-caffeinate", action="store_true", help="Do not wrap the run with macOS caffeinate")
    parser.add_argument("--refresh-alimama-auth-first", action="store_true", default=True,
                        help="Refresh Alimama auth before Step 2; enabled by default")
    parser.add_argument("--no-refresh-alimama-auth-first", action="store_false",
                        dest="refresh_alimama_auth_first",
                        help="Do not force-refresh Alimama auth before Step 2")
    parser.add_argument("--skip-alimama", action="store_true", help="Pass --skip-alimama to Step 2")
    parser.add_argument("--no-notify", action="store_true", help="Do not send Lark success notification")
    parser.add_argument("--notify-dry-run", action="store_true", help="Validate Lark notification without sending it")
    args = parser.parse_args(argv)

    config = load_config()
    run_dir = RUNS_DIR / args.date
    state_path = run_dir / "state.json"
    state = load_state(state_path, args.date)
    state["status"] = "running"
    save_state(state_path, state)

    steps = selected_steps(args)
    print(f"Dunhill daily orchestrator: {args.date}")
    print(f"Run directory: {run_dir}")
    print(f"Selected steps: {', '.join(steps)}")

    ok = True
    for step in steps:
        previous = state.get("steps", {}).get(step, {})
        if previous.get("status") == "success" and not args.force:
            print(f"[SKIP] {step} already succeeded. Use --force to re-run.")
            continue
        if not run_step_with_retries(
            step,
            step_command(step, args),
            run_dir,
            state,
            args.dry_run,
            args.step_retries,
        ):
            ok = False
            break

    state["status"] = "success" if ok else "failed"
    state["ended_at"] = now_iso()
    save_state(state_path, state)
    write_summary(run_dir, state)

    notify_ok = True
    if ok and not args.no_notify:
        notification = send_lark_success_notification(
            config,
            state,
            run_dir,
            dry_run=args.notify_dry_run or args.dry_run,
        )
        notify_ok = bool(notification.get("lark_success"))
        state["notification"] = notification
        save_state(state_path, state)
        write_summary(run_dir, state)
    elif ok and args.no_notify:
        state["notification"] = {
            "lark_success": True,
            "identity": None,
            "dry_run": False,
            "skipped": True,
            "reason": "--no-notify",
            "sent_at": now_iso(),
        }
        save_state(state_path, state)
        write_summary(run_dir, state)

    print("\n" + "=" * 70)
    print(f"Run status: {state['status']}")
    print(f"State: {state_path}")
    print(f"Summary: {run_dir / 'summary.md'}")
    if ok and not notify_ok:
        print("[WARN] Data update succeeded, but Lark notification failed. Check state.notification.")
    if ok:
        print("Mac Step 1-2 finished. Stop here unless Windows Excel Step 3-5 outputs already exist.")
    print("=" * 70)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
