"""
Step 1 runner for the Playwright Chrome Extension + MCP bridge flow.

The bridge navigates and operates the refund/live pages through high-speed
scripts while reusing the user's local Chrome login state.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).parent
ROOT_DIR = SCRIPT_DIR.parent


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
    parser.add_argument("--timeout", type=int, default=420)
    args = parser.parse_args()

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
        if not run_script(refund_cmd):
            print("[FAIL] Refund export failed")
            return 1

    if not args.skip_live:
        live_cmd = [
            sys.executable,
            "-u",
            str(SCRIPT_DIR / "export_live.py"),
            "--timeout",
            str(args.timeout),
        ]
        if not run_script(live_cmd):
            print("[FAIL] Live export failed")
            return 1

    if not args.skip_quickbi:
        quickbi_cmd = [
            sys.executable,
            "-u",
            str(SCRIPT_DIR / "export_quickbi_chrome.py"),
            "--sources",
            "all",
            "--timeout",
            str(args.timeout),
        ]
        if not run_script(quickbi_cmd):
            print("[FAIL] QuickBI supplement export failed")
            return 1

    print("\n[OK] Step 1 Chrome bridge exports completed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
