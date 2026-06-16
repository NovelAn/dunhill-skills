import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.chrome_mcp_bridge import ensure_chrome_running, resolve_node_binary


class EnsureChromeRunningTests(unittest.TestCase):
    @patch("scripts.chrome_mcp_bridge.time.sleep")
    @patch("scripts.chrome_mcp_bridge.subprocess.run")
    def test_launches_chrome_and_waits_until_running(self, run, _sleep):
        run.side_effect = [
            subprocess.CompletedProcess([], 0, stdout="false\n", stderr=""),
            subprocess.CompletedProcess([], 0, stdout="", stderr=""),
            subprocess.CompletedProcess([], 0, stdout="true\n", stderr=""),
        ]

        self.assertTrue(ensure_chrome_running(timeout=2))
        self.assertIn('tell application "Google Chrome" to activate', run.call_args_list[1].args[0])

    @patch("scripts.chrome_mcp_bridge.subprocess.run")
    def test_returns_false_when_chrome_cannot_be_launched(self, run):
        run.side_effect = [
            subprocess.CompletedProcess([], 0, stdout="false\n", stderr=""),
            subprocess.CompletedProcess([], 1, stdout="", stderr="launch failed"),
        ]

        self.assertFalse(ensure_chrome_running(timeout=2))


class ResolveNodeBinaryTests(unittest.TestCase):
    @patch("scripts.chrome_mcp_bridge.shutil.which", return_value=None)
    def test_uses_nvm_node_20_when_path_has_no_supported_node(self, _which):
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            node = home / ".nvm" / "versions" / "node" / "v20.19.6" / "bin" / "node"
            node.parent.mkdir(parents=True)
            node.write_text("#!/bin/sh\necho v20.19.6\n", encoding="utf-8")
            node.chmod(0o755)

            with patch("scripts.chrome_mcp_bridge.Path.home", return_value=home):
                self.assertEqual(resolve_node_binary(), str(node.resolve()))


if __name__ == "__main__":
    unittest.main()
