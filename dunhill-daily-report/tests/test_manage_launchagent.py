import plistlib
import tempfile
import unittest
from pathlib import Path

from scripts.manage_launchagent import LABEL, render_plist, update_codex_automation


class LaunchAgentTests(unittest.TestCase):
    def test_rendered_plist_runs_in_gui_session_at_0910(self):
        root = Path("/tmp/dunhill daily report")
        home = Path("/Users/tester")

        payload = plistlib.loads(render_plist(root=root, home=home))

        self.assertEqual(payload["Label"], LABEL)
        self.assertEqual(payload["LimitLoadToSessionType"], "Aqua")
        self.assertEqual(payload["StartCalendarInterval"], {"Hour": 9, "Minute": 10})
        self.assertEqual(
            payload["ProgramArguments"],
            ["/bin/zsh", str(root / "scripts" / "launchagent_runner.sh")],
        )
        self.assertEqual(payload["WorkingDirectory"], str(root))
        self.assertEqual(
            payload["StandardOutPath"],
            str(root / "runs" / "launchagent.stdout.log"),
        )
        self.assertEqual(
            payload["StandardErrorPath"],
            str(root / "runs" / "launchagent.stderr.log"),
        )

    def test_runner_is_lock_aware_and_invokes_only_steps_1_and_2_orchestrator(self):
        root = Path(__file__).resolve().parents[1]
        runner = (root / "scripts" / "launchagent_runner.sh").read_text(encoding="utf-8")

        self.assertIn('cd "$ROOT_DIR"', runner)
        self.assertIn('mkdir "$LOCK_DIR"', runner)
        self.assertIn("trap cleanup EXIT INT TERM", runner)
        self.assertIn('PYTHON_BIN="/Users/novel/Projects/data-import/.venv/bin/python"', runner)
        self.assertIn('"$PYTHON_BIN" -u scripts/daily_orchestrator.py', runner)
        self.assertNotIn("step3", runner.lower())
        self.assertNotIn("step4", runner.lower())
        self.assertNotIn("step5", runner.lower())

    def test_codex_automation_is_changed_to_later_read_only_monitor(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            automation_path = Path(temp_dir) / "automation.toml"
            automation_path.write_text(
                'prompt = "Run python -u scripts/daily_orchestrator.py"\n'
                'rrule = "RRULE:FREQ=WEEKLY;BYHOUR=9;BYMINUTE=10;BYDAY=SU,MO,TU,WE,TH,FR,SA"\n',
                encoding="utf-8",
            )

            update_codex_automation(automation_path)
            updated = automation_path.read_text(encoding="utf-8")

            self.assertIn("python -u scripts/report_daily_status.py", updated)
            self.assertNotIn("scripts/daily_orchestrator.py", updated)
            self.assertIn("BYHOUR=9;BYMINUTE=35", updated)


if __name__ == "__main__":
    unittest.main()
