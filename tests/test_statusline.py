"""
Unit tests for the error branches of statusline/tokease-statusline.py.

The script must never raise inside Claude Code's statusline, so its
last-resort handlers matter as much as its happy path. The end-to-end
subprocess tests live in test_tracker.py; these isolate each handler.
"""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "statusline" / "tokease-statusline.py"


def _load():
    """Import the script fresh (hyphenated filename, so not a plain import)."""
    spec = importlib.util.spec_from_file_location("tokease_statusline", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def statusline(tmp_path, monkeypatch):
    """The module with every path constant pointed inside tmp_path."""
    mod = _load()
    base = tmp_path / ".tokease"
    monkeypatch.setattr(mod, "_DIR", base)
    monkeypatch.setattr(mod, "_OUT", base / "usage.json")
    monkeypatch.setattr(mod, "_ERR", base / "statusline.err")
    return mod


def _raise_oserror(*_args, **_kwargs):
    raise OSError("simulated")


# ---------------------------------------------------------------------------
# Tests: _ensure_dir
# ---------------------------------------------------------------------------
class TestEnsureDir:
    def test_chmod_failure_is_swallowed(self, statusline, monkeypatch):
        monkeypatch.setattr(Path, "chmod", _raise_oserror)
        statusline._ensure_dir()  # must not raise
        assert statusline._DIR.is_dir()


# ---------------------------------------------------------------------------
# Tests: _log_error
# ---------------------------------------------------------------------------
class TestLogError:
    def test_unwritable_error_log_is_swallowed(self, statusline, monkeypatch):
        # A directory where the log file should be: open(..., "a") raises.
        statusline._DIR.mkdir()
        bad = statusline._DIR / "statusline.err"
        bad.mkdir()
        monkeypatch.setattr(statusline, "_ERR", bad)
        assert statusline._log_error("boom") is None

    def test_writes_when_possible(self, statusline):
        statusline._log_error("boom")
        assert "boom" in statusline._ERR.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests: _atomic_write
# ---------------------------------------------------------------------------
class TestAtomicWrite:
    def test_replace_failure_removes_temp_and_reraises(self, statusline, monkeypatch):
        err = OSError("replace failed")

        def _fail(*_args, **_kwargs):
            raise err

        monkeypatch.setattr(statusline.os, "replace", _fail)
        with pytest.raises(OSError) as caught:
            statusline._atomic_write({"schema": 1})
        assert caught.value is err
        assert list(statusline._DIR.glob(".usage.*.tmp")) == []
        assert not statusline._OUT.exists()


# ---------------------------------------------------------------------------
# Tests: the __main__ backstop
# ---------------------------------------------------------------------------
class TestMainBackstop:
    def test_unexpected_exception_is_logged_and_exits_zero(self, tmp_path):
        # Valid JSON that is not an object makes main() fail on data.get():
        # a generic exception only the top-level backstop catches.
        env = {**os.environ, "HOME": str(tmp_path), "TOKEASE_STATUSLINE_QUIET": "1"}
        proc = subprocess.run(
            [sys.executable, str(SCRIPT)],
            input=json.dumps([1]), capture_output=True, text=True, env=env, timeout=10,
        )
        assert proc.returncode == 0
        assert proc.stderr == ""
        err = tmp_path / ".tokease" / "statusline.err"
        assert "unexpected:" in err.read_text(encoding="utf-8")
        assert not (tmp_path / ".tokease" / "usage.json").exists()
