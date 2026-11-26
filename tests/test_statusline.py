#!/usr/bin/env python3
"""
In-process unit tests for statusline/tokease-statusline.py.

tests/test_tracker.py already drives the script end to end through a
subprocess (TestStatuslineScript) and checks _render_line on its own
(TestStatuslineRenderLine). This file loads the script as a module and tests
its helpers and main() directly, with ~/.tokease redirected to a throwaway
directory and the clock patched, so the paths a subprocess cannot reach
cheaply are covered too: temp-file cleanup on a failed write, the directory
mode, logged (never raised) write failures, and timestamp dedup without
sleeping.
"""

import importlib.util
import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_SCRIPT = Path(__file__).resolve().parent.parent / "statusline" / "tokease-statusline.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("tokease_statusline_under_test", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sl = _load_script()


class _TempHomeMixin:
    """Point the script's ~/.tokease paths at a fresh temp directory."""

    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.dir = Path(td.name) / ".tokease"
        self.out = self.dir / "usage.json"
        self.err = self.dir / "statusline.err"
        for name, value in (("_DIR", self.dir), ("_OUT", self.out), ("_ERR", self.err)):
            patcher = patch.object(sl, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _write_current(self, obj):
        self.dir.mkdir(parents=True, exist_ok=True)
        self.out.write_text(json.dumps(obj), encoding="utf-8")

    def _read_out(self):
        return json.loads(self.out.read_text(encoding="utf-8"))

    def _err_text(self):
        return self.err.read_text(encoding="utf-8") if self.err.exists() else ""


# ---------------------------------------------------------------------------
# _extract_window
# ---------------------------------------------------------------------------
class TestExtractWindow(unittest.TestCase):
    def test_full_window(self):
        rl = {"five_hour": {"used_percentage": 23.5, "resets_at": 1800000000}}
        self.assertEqual(
            sl._extract_window(rl, "five_hour"),
            {"used_percentage": 23.5, "resets_at": 1800000000},
        )

    def test_missing_key(self):
        self.assertIsNone(sl._extract_window({}, "seven_day"))

    def test_non_dict_window(self):
        for bad in (None, 42, "x", [1, 2]):
            with self.subTest(bad=bad):
                self.assertIsNone(sl._extract_window({"five_hour": bad}, "five_hour"))

    def test_missing_or_null_percentage(self):
        self.assertIsNone(sl._extract_window({"five_hour": {"resets_at": 1}}, "five_hour"))
        self.assertIsNone(
            sl._extract_window({"five_hour": {"used_percentage": None}}, "five_hour")
        )

    def test_zero_percentage_is_kept(self):
        # 0 % is a real reading (fresh window), not an absent one.
        self.assertEqual(
            sl._extract_window({"five_hour": {"used_percentage": 0}}, "five_hour"),
            {"used_percentage": 0},
        )

    def test_null_resets_at_is_omitted(self):
        rl = {"seven_day": {"used_percentage": 8, "resets_at": None}}
        self.assertEqual(sl._extract_window(rl, "seven_day"), {"used_percentage": 8})

    def test_extra_fields_are_dropped(self):
        rl = {"five_hour": {"used_percentage": 1, "resets_at": 2, "other": "x"}}
        self.assertEqual(
            sl._extract_window(rl, "five_hour"), {"used_percentage": 1, "resets_at": 2}
        )


# ---------------------------------------------------------------------------
# _has_window
# ---------------------------------------------------------------------------
class TestHasWindow(unittest.TestCase):
    def test_non_dict(self):
        for bad in (None, [], "x", 1):
            with self.subTest(bad=bad):
                self.assertFalse(sl._has_window(bad))

    def test_no_window(self):
        self.assertFalse(sl._has_window({"schema": 1, "captured_at": 1}))
        self.assertFalse(sl._has_window({"five_hour": {}, "seven_day": None}))

    def test_either_window(self):
        self.assertTrue(sl._has_window({"five_hour": {"used_percentage": 0}}))
        self.assertTrue(sl._has_window({"seven_day": {"used_percentage": 5}}))


# ---------------------------------------------------------------------------
# _read_current
# ---------------------------------------------------------------------------
class TestReadCurrent(_TempHomeMixin, unittest.TestCase):
    def test_missing_file(self):
        self.assertEqual(sl._read_current(), {})

    def test_invalid_json(self):
        self.dir.mkdir(parents=True)
        self.out.write_text("not json {{{", encoding="utf-8")
        self.assertEqual(sl._read_current(), {})

    def test_non_dict_json(self):
        for raw in ("[1, 2]", "42", '"x"', "null"):
            with self.subTest(raw=raw):
                self.dir.mkdir(parents=True, exist_ok=True)
                self.out.write_text(raw, encoding="utf-8")
                self.assertEqual(sl._read_current(), {})

    def test_dict_is_returned(self):
        self._write_current({"captured_at": 5, "five_hour": {"used_percentage": 1}})
        self.assertEqual(
            sl._read_current(), {"captured_at": 5, "five_hour": {"used_percentage": 1}}
        )


# ---------------------------------------------------------------------------
# _atomic_write / _ensure_dir
# ---------------------------------------------------------------------------
class TestAtomicWrite(_TempHomeMixin, unittest.TestCase):
    def _leftover_temps(self):
        return sorted(p.name for p in self.dir.glob(".usage.*.tmp"))

    def test_writes_payload_and_leaves_no_temp(self):
        sl._atomic_write({"schema": 1, "five_hour": {"used_percentage": 3}})
        self.assertEqual(self._read_out(), {"schema": 1, "five_hour": {"used_percentage": 3}})
        self.assertEqual(self._leftover_temps(), [])

    def test_replaces_existing_file(self):
        self._write_current({"old": True})
        sl._atomic_write({"new": True})
        self.assertEqual(self._read_out(), {"new": True})

    def test_unserializable_payload_cleans_temp_and_keeps_old_file(self):
        self._write_current({"good": 1})
        with self.assertRaises(TypeError):
            sl._atomic_write({"bad": object()})
        self.assertEqual(self._leftover_temps(), [])
        self.assertEqual(self._read_out(), {"good": 1})

    def test_failed_replace_cleans_temp(self):
        with patch.object(sl.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                sl._atomic_write({"x": 1})
        self.assertEqual(self._leftover_temps(), [])
        self.assertFalse(self.out.exists())

    @unittest.skipIf(os.name == "nt", "POSIX permissions")
    def test_creates_private_dir(self):
        sl._atomic_write({"x": 1})
        self.assertEqual(stat.S_IMODE(self.dir.stat().st_mode), 0o700)

    @unittest.skipIf(os.name == "nt", "POSIX permissions")
    def test_tightens_existing_dir(self):
        self.dir.mkdir(mode=0o755)
        self.dir.chmod(0o755)
        sl._atomic_write({"x": 1})
        self.assertEqual(stat.S_IMODE(self.dir.stat().st_mode), 0o700)


# ---------------------------------------------------------------------------
# _render_line (edge cases not already in test_tracker.py)
# ---------------------------------------------------------------------------
class TestRenderLineEdges(unittest.TestCase):
    def test_zero_percent_is_rendered(self):
        self.assertEqual(sl._render_line({"five_hour": {"used_percentage": 0}}), "⛁ 5h 0%")

    def test_percentage_is_truncated_not_rounded(self):
        self.assertEqual(sl._render_line({"seven_day": {"used_percentage": 99.9}}), "⛁ 7d 99%")

    def test_numeric_string_percentage(self):
        self.assertEqual(sl._render_line({"five_hour": {"used_percentage": "12.5"}}), "⛁ 5h 12%")

    def test_order_is_five_hour_then_seven_day(self):
        line = sl._render_line({
            "seven_day": {"used_percentage": 2},
            "five_hour": {"used_percentage": 1},
        })
        self.assertEqual(line, "⛁ 5h 1% · 7d 2%")


# ---------------------------------------------------------------------------
# main(): guard, dedup, output, error logging
# ---------------------------------------------------------------------------
class TestMain(_TempHomeMixin, unittest.TestCase):
    def _main(self, stdin_text, now=1_800_000_000, quiet=True):
        env = {k: v for k, v in os.environ.items() if k != "TOKEASE_STATUSLINE_QUIET"}
        if quiet:
            env["TOKEASE_STATUSLINE_QUIET"] = "1"
        stdout = io.StringIO()
        with patch.object(sl.sys, "stdin", io.StringIO(stdin_text)), \
             patch.object(sl.sys, "stdout", stdout), \
             patch.object(sl.time, "time", return_value=now), \
             patch.dict(os.environ, env, clear=True):
            sl.main()
        return stdout.getvalue()

    @staticmethod
    def _stdin(five=None, seven=None, **extra):
        rl = {}
        if five is not None:
            rl["five_hour"] = five
        if seven is not None:
            rl["seven_day"] = seven
        return json.dumps({"rate_limits": rl, **extra})

    def test_payload_shape(self):
        self._main(self._stdin(five={"used_percentage": 4, "resets_at": 9}), now=1234)
        self.assertEqual(self._read_out(), {
            "schema": sl._SCHEMA,
            "captured_at": 1234,
            "source": "claude-code-statusline",
            "five_hour": {"used_percentage": 4, "resets_at": 9},
        })

    def test_non_dict_rate_limits_is_ignored(self):
        self._main(json.dumps({"rate_limits": [1, 2]}))
        payload = self._read_out()
        self.assertNotIn("five_hour", payload)
        self.assertNotIn("seven_day", payload)

    # -- timestamp dedup ----------------------------------------------------
    def test_identical_windows_keep_first_timestamp(self):
        stdin = self._stdin(five={"used_percentage": 42, "resets_at": 1})
        self._main(stdin, now=1000)
        self._main(stdin, now=2000)
        self.assertEqual(self._read_out()["captured_at"], 1000)

    def test_changed_reset_time_restamps(self):
        self._main(self._stdin(five={"used_percentage": 42, "resets_at": 1}), now=1000)
        self._main(self._stdin(five={"used_percentage": 42, "resets_at": 2}), now=2000)
        self.assertEqual(self._read_out()["captured_at"], 2000)

    def test_float_previous_timestamp_is_kept_as_int(self):
        self._write_current({"captured_at": 1000.7, "five_hour": {"used_percentage": 42}})
        self._main(self._stdin(five={"used_percentage": 42}), now=2000)
        self.assertEqual(self._read_out()["captured_at"], 1000)

    def test_non_numeric_previous_timestamp_is_not_reused(self):
        for seen in ("1000", None, [1000]):
            with self.subTest(seen=seen):
                self._write_current({"captured_at": seen, "five_hour": {"used_percentage": 42}})
                self._main(self._stdin(five={"used_percentage": 42}), now=2000)
                self.assertEqual(self._read_out()["captured_at"], 2000)

    # -- guard against wiping good data -------------------------------------
    def test_windowless_capture_keeps_good_file_byte_for_byte(self):
        good = {"schema": 1, "captured_at": 1000, "five_hour": {"used_percentage": 42}}
        self._write_current(good)
        before = self.out.read_bytes()
        self._main(self._stdin(), now=2000)
        self.assertEqual(self.out.read_bytes(), before)

    def test_windowless_capture_replaces_windowless_file(self):
        self._write_current({"schema": 1, "captured_at": 1000})
        self._main(self._stdin(), now=2000)
        self.assertEqual(self._read_out()["captured_at"], 2000)

    def test_invalid_json_is_logged_and_writes_nothing(self):
        self._main("not json {{{")
        self.assertFalse(self.out.exists())
        self.assertIn("stdin not JSON", self._err_text())

    def test_write_failure_is_logged_not_raised(self):
        with patch.object(sl, "_atomic_write", side_effect=OSError("read-only")):
            self._main(self._stdin(five={"used_percentage": 1}))
        self.assertIn("write failed", self._err_text())
        self.assertIn("read-only", self._err_text())

    # -- stdout -------------------------------------------------------------
    def test_prints_line_when_not_quiet(self):
        out = self._main(
            self._stdin(five={"used_percentage": 42.9}, seven={"used_percentage": 7}),
            quiet=False,
        )
        self.assertEqual(out, "⛁ 5h 42% · 7d 7%")

    def test_quiet_env_suppresses_output(self):
        out = self._main(self._stdin(five={"used_percentage": 42}), quiet=True)
        self.assertEqual(out, "")
        self.assertTrue(self.out.exists())  # capture still happens

    def test_windowless_capture_prints_nothing(self):
        self.assertEqual(self._main(self._stdin(), quiet=False), "")


if __name__ == "__main__":
    unittest.main()
