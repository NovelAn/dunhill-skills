"""
Step 1 entrypoint.

All model runtimes use the same Playwright Chrome Extension + MCP bridge flow.
This avoids Codex Extension computer-use clicks on Taobao/QianNiu pages while
still reusing the user's local Chrome login state.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from chrome_mcp_bridge import (
    PRIMARY_ENV_PATH,
    bootstrap_playwright_extension_token,
    ensure_chrome_running,
)


SCRIPT_DIR = Path(__file__).parent
ROOT_DIR = SCRIPT_DIR.parent


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Step 1 through Playwright MCP Extension bridge")
    parser.add_argument("--skip-refund", action="store_true")
    parser.add_argument("--skip-live", action="store_true")
    parser.add_argument("--skip-quickbi", action="store_true")
    parser.add_argument("--quickbi-sources", nargs="+")
    parser.add_argument("--timeout", type=int, default=420)
    args = parser.parse_args()

    command = [
        sys.executable,
        "-u",
        str(SCRIPT_DIR / "step1_chrome_bridge.py"),
        "--timeout",
        str(args.timeout),
    ]
    if args.skip_refund:
        command.append("--skip-refund")
    if args.skip_live:
        command.append("--skip-live")
    if args.skip_quickbi:
        command.append("--skip-quickbi")
    if args.quickbi_sources:
        command.append("--quickbi-sources")
        command.extend(args.quickbi_sources)

    print("Step 1 flow: Playwright Chrome Extension + MCP bridge")
    print("Refund/live/QuickBI exports run through high-speed scripts in the local Chrome login state.")
    print("Ensuring Google Chrome is running...")
    if not ensure_chrome_running():
        print("[FAIL] Google Chrome could not be started or reached through macOS AppleScript.")
        return 1
    print("[OK] Google Chrome is running.")
    print(f"Refreshing Playwright Extension token once and writing it to {PRIMARY_ENV_PATH}")
    token = bootstrap_playwright_extension_token()
    if token:
        print("[OK] Playwright Extension token refreshed for this Step 1 run.")
    else:
        print("[WARN] Playwright Extension token refresh did not return a token; child sessions will try fallback discovery.")
    result = subprocess.run(command, cwd=str(ROOT_DIR))
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
