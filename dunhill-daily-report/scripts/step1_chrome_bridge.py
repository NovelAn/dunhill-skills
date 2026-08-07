"""
Step 1 runner for the Playwright Chrome Extension + MCP bridge flow.

The bridge navigates and operates the refund/live pages through high-speed
scripts while reusing the user's local Chrome login state.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).parent
ROOT_DIR = SCRIPT_DIR.parent
QUICKBI_SOURCE_KEYS = ["tm_order", "tm_refund_success", "tm_refund_pending", "dtc_order", "dtc_refund"]


def record_task(name: str, status: str) -> None:
    path_text = os.environ.get("DUNHILL_STEP1_TASK_STATE")
    if not path_text:
        return
    path = Path(path_text)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except json.JSONDecodeError:
        state = {}
    state[name] = status
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def run_script(args: list[str]) -> bool:
    print("\n" + "=" * 60)
    print("Running:", " ".join(args))
    print("=" * 60)
    result = subprocess.run(args, cwd=str(ROOT_DIR))
    return result.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Step 1 through local Chrome bridge")
    parser.add_argument(
        "--refund-attach-current",
        action="store_true",
        help="Use this if Playwright Extension is already attached to the refund page",
    )
    parser.add_argument("--skip-refund", action="store_true")
    parser.add_argument("--skip-live", action="store_true")
    parser.add_argument(
        "--skip-quickbi",
        action="store_true",
        help="Skip QuickBI full-export supplement for TM order/refund sources",
    )
    parser.add_argument("--quickbi-sources", nargs="+", choices=QUICKBI_SOURCE_KEYS)
    parser.add_argument("--timeout", type=int, default=420)
    args = parser.parse_args()
    failed: list[str] = []

    if not args.skip_refund:
        refund_cmd = [
            sys.executable,
            "-u",
            str(SCRIPT_DIR / "export_refund_chrome.py"),
            "--timeout",
            str(args.timeout),
        ]
        if args.refund_attach_current:
            refund_cmd.append("--attach-current")
        if run_script(refund_cmd):
            record_task("refund", "success")
        else:
            record_task("refund", "failed")
            print("[FAIL] Refund export failed")
            failed.append("refund")

    if not args.skip_live:
        live_cmd = [
            sys.executable,
            "-u",
            str(SCRIPT_DIR / "export_live.py"),
            "--timeout",
            str(args.timeout),
        ]
        if run_script(live_cmd):
            record_task("live", "success")
        else:
            record_task("live", "failed")
            print("[FAIL] Live export failed")
            failed.append("live")

    if not args.skip_quickbi:
        quickbi_sources = args.quickbi_sources or QUICKBI_SOURCE_KEYS
        for source in quickbi_sources:
            quickbi_cmd = [
                sys.executable,
                "-u",
                str(SCRIPT_DIR / "export_quickbi_chrome.py"),
                "--sources",
                source,
                "--timeout",
                str(args.timeout),
            ]
            if run_script(quickbi_cmd):
                record_task(f"quickbi:{source}", "success")
            else:
                record_task(f"quickbi:{source}", "failed")
                print(f"[FAIL] QuickBI supplement export failed: {source}")
                failed.append(f"quickbi:{source}")

    if failed:
        print("\n[FAIL] Step 1 failed tasks: " + ", ".join(failed))
        return 1
    print("\n[OK] Step 1 Chrome bridge exports completed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
