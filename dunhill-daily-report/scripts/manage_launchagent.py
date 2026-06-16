"""Manage the user LaunchAgent that runs Dunhill Step 1-2 in the GUI session."""

from __future__ import annotations

import argparse
import os
import plistlib
import re
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape


LABEL = "com.dunhill.daily-report"
ROOT_DIR = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = ROOT_DIR / "launchd" / f"{LABEL}.plist.template"
AUTOMATION_PATH = (
    Path.home()
    / ".codex"
    / "automations"
    / "dunhill-daily-step-1-2"
    / "automation.toml"
)
MONITOR_PROMPT = (
    "Run `python -u scripts/report_daily_status.py` from the workspace root. "
    "Do not run the orchestrator or any workflow step. Summarize the final data "
    "status, state.notification, state and summary paths, LaunchAgent logs, and "
    "needs-action items. Steps 3-5 must remain excluded on macOS."
)


def render_plist(root: Path = ROOT_DIR, home: Path | None = None) -> bytes:
    home = home or Path.home()
    runs_dir = root / "runs"
    replacements = {
        "{{LABEL}}": LABEL,
        "{{RUNNER_PATH}}": str(root / "scripts" / "launchagent_runner.sh"),
        "{{ROOT_DIR}}": str(root),
        "{{STDOUT_PATH}}": str(runs_dir / "launchagent.stdout.log"),
        "{{STDERR_PATH}}": str(runs_dir / "launchagent.stderr.log"),
    }
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    for token, value in replacements.items():
        text = text.replace(token, escape(value))
    payload = text.encode("utf-8")
    plistlib.loads(payload)
    return payload


def destination(home: Path | None = None) -> Path:
    return (home or Path.home()) / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def update_codex_automation(path: Path = AUTOMATION_PATH) -> None:
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    prompt_line = f"prompt = {json_string(MONITOR_PROMPT)}"
    schedule_line = (
        'rrule = "RRULE:FREQ=WEEKLY;BYHOUR=9;BYMINUTE=35;'
        'BYDAY=SU,MO,TU,WE,TH,FR,SA"'
    )
    updated, prompt_count = re.subn(r"(?m)^prompt\s*=.*$", prompt_line, text, count=1)
    updated, schedule_count = re.subn(r"(?m)^rrule\s*=.*$", schedule_line, updated, count=1)
    if prompt_count != 1 or schedule_count != 1:
        raise RuntimeError(f"Unexpected Codex automation format: {path}")
    temporary = path.with_suffix(".toml.tmp")
    temporary.write_text(updated, encoding="utf-8")
    os.replace(temporary, path)


def json_string(value: str) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


def launchctl(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["launchctl", *args],
        text=True,
        capture_output=True,
        check=check,
    )


def install() -> None:
    target = destination()
    target.parent.mkdir(parents=True, exist_ok=True)
    (ROOT_DIR / "runs").mkdir(parents=True, exist_ok=True)
    runner = ROOT_DIR / "scripts" / "launchagent_runner.sh"
    runner.chmod(runner.stat().st_mode | 0o100)
    temporary = target.with_suffix(".plist.tmp")
    temporary.write_bytes(render_plist())
    os.replace(temporary, target)

    domain = f"gui/{os.getuid()}"
    launchctl("bootout", domain, str(target), check=False)
    launchctl("bootstrap", domain, str(target))
    launchctl("enable", f"{domain}/{LABEL}")
    update_codex_automation()
    print(f"Installed {LABEL}: {target}")
    if AUTOMATION_PATH.exists():
        print(f"Updated Codex monitor automation: {AUTOMATION_PATH}")


def uninstall() -> None:
    target = destination()
    domain = f"gui/{os.getuid()}"
    launchctl("bootout", domain, str(target), check=False)
    if target.exists():
        target.unlink()
    print(f"Uninstalled {LABEL}")


def status() -> int:
    domain = f"gui/{os.getuid()}/{LABEL}"
    result = launchctl("print", domain, check=False)
    stream = sys.stdout if result.returncode == 0 else sys.stderr
    print(result.stdout or result.stderr, file=stream, end="")
    return result.returncode


def trigger() -> None:
    domain = f"gui/{os.getuid()}/{LABEL}"
    launchctl("kickstart", "-k", domain)
    print(f"Triggered {LABEL}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("render", "install", "status", "trigger", "uninstall"))
    args = parser.parse_args()

    if args.action == "render":
        sys.stdout.buffer.write(render_plist())
        return 0
    if args.action == "install":
        install()
        return 0
    if args.action == "status":
        return status()
    if args.action == "trigger":
        trigger()
        return 0
    uninstall()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
