"""
Tests for uninstall.sh's statusLine cleanup in ~/.claude/settings.json.

The script runs for real, but against a throwaway HOME, and from a copy in a
separate temp directory: its pkill pattern is built from its own location, so
it can never match a real running tracker.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

UNINSTALL_SH = Path(__file__).resolve().parent.parent / "uninstall.sh"


@unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "requires bash and jq")
class TestUninstallStatusLine(unittest.TestCase):

    def _run_uninstall(self, settings):
        with tempfile.TemporaryDirectory() as fake_home, \
                tempfile.TemporaryDirectory() as script_dir:
            settings_path = Path(fake_home) / ".claude" / "settings.json"
            settings_path.parent.mkdir()
            settings_path.write_text(json.dumps(settings))
            script = Path(script_dir) / "uninstall.sh"
            shutil.copy(UNINSTALL_SH, script)
            result = subprocess.run(
                ["bash", str(script)],
                env={**os.environ, "HOME": fake_home},
                capture_output=True, text=True, timeout=30, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(settings_path.read_text())

    def test_keeps_user_statusline_when_marker_only_in_permissions(self):
        user_line = {"type": "command", "command": "~/my-line.sh"}
        after = self._run_uninstall({
            "statusLine": user_line,
            "permissions": {"allow": ["Bash(python3 ~/.tokease/tokease-statusline.py)"]},
        })
        self.assertEqual(after.get("statusLine"), user_line)

    def test_removes_our_statusline(self):
        after = self._run_uninstall({
            "statusLine": {"type": "command",
                           "command": "python3 ~/.tokease/tokease-statusline.py"},
            "theme": "dark",
        })
        self.assertNotIn("statusLine", after)
        self.assertEqual(after.get("theme"), "dark")


if __name__ == "__main__":
    unittest.main()
