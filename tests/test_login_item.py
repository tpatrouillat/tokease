#!/usr/bin/env python3
"""
Tests for the login-item helpers in tracker.py: _get_app_path,
_is_login_item and _set_login_item.

subprocess.run is always mocked: no real osascript ever runs.

tracker is imported through test_tracker so both files share the same rumps
stub and the same tracker module, whatever order pytest collects them in.
"""

import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

from test_tracker import tracker


class TestGetAppPath(unittest.TestCase):

    def test_returns_none_when_not_frozen(self):
        with patch.object(sys, "frozen", False, create=True):
            self.assertIsNone(tracker._get_app_path())

    def test_returns_none_when_frozen_attribute_absent(self):
        saved = sys.__dict__.pop("frozen", None)
        try:
            self.assertIsNone(tracker._get_app_path())
        finally:
            if saved is not None:
                sys.frozen = saved

    def test_returns_app_bundle_when_frozen(self):
        exe = "/Applications/Foo.app/Contents/MacOS/x"
        with patch.object(sys, "frozen", "macosx_app", create=True), \
                patch.object(sys, "executable", exe):
            self.assertEqual(tracker._get_app_path(), "/Applications/Foo.app")

    def test_returns_none_when_frozen_outside_app_bundle(self):
        with patch.object(sys, "frozen", "macosx_app", create=True), \
                patch.object(sys, "executable", "/usr/local/bin/python3"):
            self.assertIsNone(tracker._get_app_path())


class TestIsLoginItem(unittest.TestCase):

    def _run(self, **kwargs):
        return patch.object(tracker.subprocess, "run", **kwargs)

    def test_true_when_name_listed(self):
        out = MagicMock(stdout=f"Dropbox, {tracker.LOGIN_ITEM_NAME}, Rectangle\n")
        with self._run(return_value=out) as run:
            self.assertTrue(tracker._is_login_item())
        args = run.call_args.args[0]
        self.assertEqual(args[0], "/usr/bin/osascript")

    def test_false_when_name_absent(self):
        with self._run(return_value=MagicMock(stdout="Dropbox, Rectangle\n")):
            self.assertFalse(tracker._is_login_item())

    def test_false_when_stdout_none(self):
        with self._run(return_value=MagicMock(stdout=None)):
            self.assertFalse(tracker._is_login_item())

    def test_false_on_oserror(self):
        with self._run(side_effect=OSError("no osascript")):
            self.assertFalse(tracker._is_login_item())

    def test_false_on_timeout(self):
        exc = subprocess.TimeoutExpired(cmd="osascript", timeout=5)
        with self._run(side_effect=exc):
            self.assertFalse(tracker._is_login_item())


class TestSetLoginItem(unittest.TestCase):

    APP = "/Applications/Tokease.app"

    def _script(self, run):
        run.assert_called_once()
        args = run.call_args.args[0]
        self.assertEqual(args[:2], ["/usr/bin/osascript", "-e"])
        return args[2]

    def test_rejects_unsafe_paths_without_running_osascript(self):
        # Mirrors the guard in tracker._set_login_item: '"', '\\' and '\n'.
        for bad in ('/Applications/Tok"ease.app',
                    "/Applications/Tok\\ease.app",
                    "/Applications/Tok\nease.app"):
            for enabled in (True, False):
                with self.subTest(path=bad, enabled=enabled), \
                        patch.object(tracker.subprocess, "run") as run:
                    self.assertIsNone(tracker._set_login_item(enabled, bad))
                    run.assert_not_called()

    def test_enable_builds_make_login_item_script(self):
        with patch.object(tracker.subprocess, "run") as run:
            tracker._set_login_item(True, self.APP)
        script = self._script(run)
        self.assertIn("make login item", script)
        self.assertIn(f'path:"{self.APP}"', script)

    def test_disable_builds_delete_login_item_script(self):
        with patch.object(tracker.subprocess, "run") as run:
            tracker._set_login_item(False, self.APP)
        script = self._script(run)
        self.assertIn(f'delete login item "{tracker.LOGIN_ITEM_NAME}"', script)
        self.assertNotIn(self.APP, script)

    def test_swallows_oserror(self):
        with patch.object(tracker.subprocess, "run", side_effect=OSError("boom")):
            tracker._set_login_item(True, self.APP)

    def test_swallows_timeout(self):
        exc = subprocess.TimeoutExpired(cmd="osascript", timeout=5)
        with patch.object(tracker.subprocess, "run", side_effect=exc):
            tracker._set_login_item(False, self.APP)


if __name__ == "__main__":
    unittest.main()
