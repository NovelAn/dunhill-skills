"""Read Dunhill daily run artifacts without executing any workflow step."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def build_report(root: Path, run_date: str) -> dict:
    run_dir = root / "runs" / run_date
    state_path = run_dir / "state.json"
    summary_path = run_dir / "summary.md"
    report = {
        "run_date": run_date,
        "status": "not_run",
        "state_exists": state_path.exists(),
        "state_path": str(state_path),
        "summary_path": str(summary_path),
        "steps": {},
        "notification": None,
        "needs_action": [],
        "launchagent_logs": {
            "runner": str(root / "runs" / "launchagent.runner.log"),
            "stdout": str(root / "runs" / "launchagent.stdout.log"),
            "stderr": str(root / "runs" / "launchagent.stderr.log"),
        },
    }
    if not state_path.exists():
        return report

    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        report["status"] = "invalid_state"
        report["needs_action"] = [f"Unable to read state.json: {exc}"]
        return report

    report["status"] = state.get("status", "unknown")
    report["notification"] = state.get("notification")
    for step_name, step in state.get("steps", {}).items():
        report["steps"][step_name] = step.get("status", "unknown")
        for item in step.get("needs_action", []):
            if item not in report["needs_action"]:
                report["needs_action"].append(item)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--root", type=Path, default=ROOT_DIR)
    args = parser.parse_args()
    print(json.dumps(build_report(args.root, args.date), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
