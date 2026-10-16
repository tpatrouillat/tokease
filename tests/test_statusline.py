#!/usr/bin/env python3
"""
In-process unit tests for statusline/tokease-statusline.py.

tests/test_tracker.py drives the script end to end through a subprocess. These
tests import its functions directly and redirect ~/.tokease to a temp dir, so
they cover what a subprocess cannot reach cheaply: directory mode, the failure
paths of the atomic write, and the dedup rule under a controlled clock (no
sleeps). No rumps/PyObjC needed: the script only uses the standard library.
"""

import importlib.util
import io
import json
import os
import runpy
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parent.parent / "statusline" / "tokease-statusline.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("tokease_statusline", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _StatuslineTestCase(unittest.TestCase):
    """Loads a fresh copy of the script with _DIR/_OUT/_ERR pointed at a temp dir."""

    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.home = Path(td.name)
        self.dir = self.home / ".tokease"
        self.out = self.dir / "usage.json"
        self.mod = _load_script()
        for name, value in (("_DIR", self.dir), ("_OUT", self.out),
                            ("_ERR", self.dir / "statusline.err")):
            p = patch.object(self.mod, name, value)
            p.start()
            self.addCleanup(p.stop)

    def _write_current(self, payload):
        self.dir.mkdir(parents=True, exist_ok=True)
        self.out.write_text(json.dumps(payload), encoding="utf-8")

    def _run_main(self, stdin_text, now=1_800_000_100, quiet=True):
        """Run main() with the given stdin and a fixed clock; return stdout."""
        env = {"TOKEASE_STATUSLINE_QUIET": "1"} if quiet else {}
        stdout = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO(stdin_text)), \
             patch.object(sys, "stdout", stdout), \
             patch.object(self.mod.time, "time", return_value=now), \
             patch.dict(os.environ, env, clear=False):
            if not quiet:
                os.environ.pop("TOKEASE_STATUSLINE_QUIET", None)
            self.mod.main()
        return stdout.getvalue()

    def _stored(self):
        return json.loads(self.out.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# _ensure_dir
# ---------------------------------------------------------------------------
class TestEnsureDir(_StatuslineTestCase):

    def test_creates_dir_with_mode_0700(self):
        self.mod._ensure_dir()
        self.assertTrue(self.dir.is_dir())
        self.assertEqual(stat.S_IMODE(self.dir.stat().st_mode), 0o700)

    def test_tightens_a_pre_existing_looser_dir(self):
        self.dir.mkdir()
        self.dir.chmod(0o755)
        self.mod._ensure_dir()
        self.assertEqual(stat.S_IMODE(self.dir.stat().st_mode), 0o700)

    def test_is_idempotent_and_keeps_contents(self):
        self._write_current({"captured_at": 1})
        self.mod._ensure_dir()
        self.mod._ensure_dir()
        self.assertEqual(self._stored(), {"captured_at": 1})


# ---------------------------------------------------------------------------
# _atomic_write
# ---------------------------------------------------------------------------
class TestAtomicWrite(_StatuslineTestCase):

    def _tmp_leftovers(self):
        return [p.name for p in self.dir.iterdir() if p.name.endswith(".tmp")]

    def test_writes_parseable_json_and_leaves_no_temp_file(self):
        payload = {"schema": 1, "captured_at": 5, "five_hour": {"used_percentage": 12}}
        self.mod._atomic_write(payload)
        self.assertEqual(self._stored(), payload)
        self.assertEqual(self._tmp_leftovers(), [])

    def test_creates_the_private_dir_when_missing(self):
        self.mod._atomic_write({"captured_at": 1})
        self.assertEqual(stat.S_IMODE(self.dir.stat().st_mode), 0o700)

    def test_goes_through_os_replace_from_a_temp_in_the_same_dir(self):
        calls = []
        real_replace = os.replace

        def spy(src, dst):
            calls.append((Path(src), Path(dst)))
            real_replace(src, dst)

        with patch.object(self.mod.os, "replace", side_effect=spy):
            self.mod._atomic_write({"captured_at": 1})
        self.assertEqual(len(calls), 1)
        src, dst = calls[0]
        self.assertEqual(dst, self.out)
        self.assertEqual(src.parent, self.dir)  # same filesystem, so the rename is atomic

    def test_serialization_failure_midway_keeps_the_previous_file(self):
        # json.dump streams: a non-serializable value fails after part of the
        # object is already written to the temp file.
        good = {"captured_at": 1, "five_hour": {"used_percentage": 42}}
        self._write_current(good)
        with self.assertRaises(TypeError):
            self.mod._atomic_write({"captured_at": 2, "bad": object()})
        self.assertEqual(self._stored(), good)
        self.assertEqual(self._tmp_leftovers(), [])

    def test_failed_rename_keeps_the_previous_file(self):
        good = {"captured_at": 1, "seven_day": {"used_percentage": 8}}
        self._write_current(good)
        with patch.object(self.mod.os, "replace", side_effect=OSError("disk full")), \
             self.assertRaises(OSError):
            self.mod._atomic_write({"captured_at": 2})
        self.assertEqual(self._stored(), good)
        self.assertEqual(self._tmp_leftovers(), [])


# ---------------------------------------------------------------------------
# _read_current / _render_line
# ---------------------------------------------------------------------------
class TestReadCurrent(_StatuslineTestCase):

    def test_missing_file_reads_as_empty(self):
        self.assertEqual(self.mod._read_current(), {})

    def test_malformed_json_reads_as_empty(self):
        self.dir.mkdir()
        self.out.write_text('{"five_hour": ', encoding="utf-8")
        self.assertEqual(self.mod._read_current(), {})

    def test_non_object_json_reads_as_empty(self):
        for text in ("[1, 2]", "42", '"x"', "null"):
            with self.subTest(text=text):
                self.dir.mkdir(exist_ok=True)
                self.out.write_text(text, encoding="utf-8")
                self.assertEqual(self.mod._read_current(), {})

    def test_valid_object_round_trips(self):
        good = {"captured_at": 3, "five_hour": {"used_percentage": 1, "resets_at": 9}}
        self._write_current(good)
        self.assertEqual(self.mod._read_current(), good)


class TestRenderFromStoredFile(_StatuslineTestCase):
    """_render_line fed by _read_current, as the snippet path would chain them.
    Pure formatting cases already live in test_tracker.TestStatuslineRenderLine."""

    def test_existing_file_renders_its_windows(self):
        self._write_current({
            "five_hour": {"used_percentage": 42.9},
            "seven_day": {"used_percentage": 7},
        })
        self.assertEqual(self.mod._render_line(self.mod._read_current()), "⛁ 5h 42% · 7d 7%")

    def test_missing_file_renders_nothing(self):
        self.assertEqual(self.mod._render_line(self.mod._read_current()), "")

    def test_malformed_file_renders_nothing(self):
        self.dir.mkdir()
        self.out.write_text("not json", encoding="utf-8")
        self.assertEqual(self.mod._render_line(self.mod._read_current()), "")

    def test_null_window_renders_nothing(self):
        self._write_current({"five_hour": None, "seven_day": {}})
        self.assertEqual(self.mod._render_line(self.mod._read_current()), "")


# ---------------------------------------------------------------------------
# main(): dedup / keep-previous rule, under a fixed clock
# ---------------------------------------------------------------------------
STORED_AT = 1_800_000_000
STORED = {
    "schema": 1, "captured_at": STORED_AT, "source": "claude-code-statusline",
    "five_hour": {"used_percentage": 42, "resets_at": 1_800_001_000},
    "seven_day": {"used_percentage": 8, "resets_at": 1_800_500_000},
}


def _stdin(five=None, seven=None, **extra):
    rl = {}
    if five is not None:
        rl["five_hour"] = five
    if seven is not None:
        rl["seven_day"] = seven
    return json.dumps({"rate_limits": rl, **extra})


class TestMainDedup(_StatuslineTestCase):

    NOW = STORED_AT + 100

    # (a) rate_limits present ------------------------------------------------
    def test_newer_measurement_overwrites_and_restamps(self):
        self._write_current(STORED)
        self._run_main(_stdin(five={"used_percentage": 43, "resets_at": 1_800_001_000},
                              seven=STORED["seven_day"]), now=self.NOW)
        stored = self._stored()
        self.assertEqual(stored["captured_at"], self.NOW)
        self.assertEqual(stored["five_hour"]["used_percentage"], 43)

    def test_identical_measurement_keeps_the_previous_timestamp(self):
        self._write_current(STORED)
        self._run_main(_stdin(five=STORED["five_hour"], seven=STORED["seven_day"]),
                       now=self.NOW)
        self.assertEqual(self._stored()["captured_at"], STORED_AT)

    def test_changed_reset_alone_counts_as_a_new_measurement(self):
        self._write_current(STORED)
        self._run_main(_stdin(five={"used_percentage": 42, "resets_at": 1_800_019_000},
                              seven=STORED["seven_day"]), now=self.NOW)
        self.assertEqual(self._stored()["captured_at"], self.NOW)

    def test_non_numeric_stored_timestamp_is_not_reused(self):
        self._write_current({**STORED, "captured_at": "yesterday"})
        self._run_main(_stdin(five=STORED["five_hour"], seven=STORED["seven_day"]),
                       now=self.NOW)
        self.assertEqual(self._stored()["captured_at"], self.NOW)

    def test_float_stored_timestamp_is_kept_as_int(self):
        self._write_current({**STORED, "captured_at": STORED_AT + 0.7})
        self._run_main(_stdin(five=STORED["five_hour"], seven=STORED["seven_day"]),
                       now=self.NOW)
        self.assertEqual(self._stored()["captured_at"], STORED_AT)

    # (b) no rate_limits -----------------------------------------------------
    def test_no_rate_limits_leaves_good_file_byte_identical(self):
        self._write_current(STORED)
        before = self.out.read_bytes()
        self._run_main(json.dumps({"model": {"id": "x"}}), now=self.NOW)
        self.assertEqual(self.out.read_bytes(), before)

    def test_rate_limits_with_only_unusable_windows_is_treated_as_none(self):
        self._write_current(STORED)
        before = self.out.read_bytes()
        self._run_main(_stdin(five={"resets_at": 1}, seven="garbage"), now=self.NOW)
        self.assertEqual(self.out.read_bytes(), before)

    def test_non_dict_rate_limits_is_treated_as_none(self):
        self._write_current(STORED)
        before = self.out.read_bytes()
        self._run_main(json.dumps({"rate_limits": [1, 2]}), now=self.NOW)
        self.assertEqual(self.out.read_bytes(), before)

    # (c) malformed / missing stdin -------------------------------------------
    def test_garbage_stdin_returns_cleanly_and_logs(self):
        self._write_current(STORED)
        before = self.out.read_bytes()
        self._run_main("not json {{{", now=self.NOW)  # must not raise
        self.assertEqual(self.out.read_bytes(), before)
        err = (self.dir / "statusline.err").read_text(encoding="utf-8")
        self.assertIn("stdin not JSON", err)

    def test_empty_stdin_keeps_good_file(self):
        self._write_current(STORED)
        before = self.out.read_bytes()
        self._run_main("   \n", now=self.NOW)
        self.assertEqual(self.out.read_bytes(), before)

    def test_write_failure_is_logged_not_raised(self):
        with patch.object(self.mod.os, "replace", side_effect=OSError("ro fs")):
            self._run_main(_stdin(five={"used_percentage": 1}), now=self.NOW)
        self.assertFalse(self.out.exists())
        err = (self.dir / "statusline.err").read_text(encoding="utf-8")
        self.assertIn("write failed", err)

    # stdout ------------------------------------------------------------------
    def test_prints_the_line_when_not_quiet(self):
        out = self._run_main(_stdin(five={"used_percentage": 42.5},
                                    seven={"used_percentage": 7}), quiet=False)
        self.assertEqual(out, "⛁ 5h 42% · 7d 7%")

    def test_quiet_env_suppresses_output(self):
        out = self._run_main(_stdin(five={"used_percentage": 42}), quiet=True)
        self.assertEqual(out, "")


class TestMainBackstop(unittest.TestCase):
    """The module docstring says the script must NEVER raise and always exits 0.
    main() itself raises on valid-but-non-object stdin; the __main__ guard is
    what holds the contract, so exercise it as Claude Code would run it."""

    def _run_as_script(self, stdin_text):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        with patch.dict(os.environ, {"HOME": td.name, "TOKEASE_STATUSLINE_QUIET": "1"}), \
             patch.object(sys, "stdin", io.StringIO(stdin_text)), \
             self.assertRaises(SystemExit) as cm:
            runpy.run_path(str(SCRIPT), run_name="__main__")
        return cm.exception.code, Path(td.name) / ".tokease"

    def test_non_object_stdin_exits_zero_and_logs(self):
        for text in ("[1, 2]", "42", '"x"'):
            with self.subTest(text=text):
                code, tokease_dir = self._run_as_script(text)
                self.assertEqual(code, 0)
                self.assertFalse((tokease_dir / "usage.json").exists())
                err = (tokease_dir / "statusline.err").read_text(encoding="utf-8")
                self.assertIn("unexpected", err)

    def test_garbage_stdin_exits_zero(self):
        code, tokease_dir = self._run_as_script("not json {{{")
        self.assertEqual(code, 0)
        self.assertFalse((tokease_dir / "usage.json").exists())


if __name__ == "__main__":
    unittest.main()
