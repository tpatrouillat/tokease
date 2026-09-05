#!/usr/bin/env python3
"""
Tests for Tokease.

Mocks rumps to run without the macOS GUI. Two local data sources: the Claude
Code statusline feed and the Claude desktop app quota history (ADR 0003).
Covers: helpers, time formatting, both source readers (error paths + success),
the freshness merge, display logic (2 rings), empty states, and interval
management.
"""

import ast
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Mock rumps before importing tracker (rumps requires macOS PyObjC)
# ---------------------------------------------------------------------------
class FakeMenuItem:
    def __init__(self, title="", callback=None):
        self.title = title
        self._callback = callback
        self.state = 0
        self._items = {}

    def add(self, item):
        self._items[item.title] = item

    def __setitem__(self, key, val):
        self._items[key] = val

    def __getitem__(self, key):
        return self._items[key]


class FakeTimer:
    def __init__(self, callback, interval):
        self.callback = callback
        self.interval = interval
        self.is_alive = False

    def start(self):
        self.is_alive = True

    def stop(self):
        self.is_alive = False


class FakeApp:
    def __init__(self, name, title="", icon=None, template=False, quit_button=None):
        self.name = name
        self.title = title
        self.icon = icon
        self.template = template
        self.menu = {}

    def run(self):
        """No-op: tests never start the rumps event loop."""


fake_rumps = MagicMock()
fake_rumps.App = FakeApp
fake_rumps.MenuItem = FakeMenuItem
fake_rumps.Timer = FakeTimer
fake_rumps.quit_application = lambda: None
sys.modules["rumps"] = fake_rumps

import tracker  # noqa: E402 — must come after rumps mock

# Neutralise settings persistence so tests don't pick up stored UserDefaults
# values from prior runs (interval, alerts, display_mode).
tracker._DEFAULTS = None
# Drop the title spacer so existing assertions like `app.title == "42%"` keep
# working — the spacer is a pure cosmetic and not the unit under test here.
tracker._TITLE_SPACER = ""


# ---------------------------------------------------------------------------
# Fake usage data builder (shape normalized by fetch_usage, statusline source)
# ---------------------------------------------------------------------------
def _make_usage(
    five_hour_pct=42,
    seven_day_pct=18,
    five_hour_resets="2099-03-06T18:00:00Z",
    seven_day_resets="2099-03-10T00:00:00Z",
    captured_at=None,
):
    if captured_at is None:
        captured_at = datetime.now(timezone.utc).timestamp()
    return {
        "five_hour": {
            "utilization": five_hour_pct,
            "resets_at": five_hour_resets,
        },
        "seven_day": {
            "utilization": seven_day_pct,
            "resets_at": seven_day_resets,
        },
        "_meta": {"captured_at": captured_at},
    }


# ---------------------------------------------------------------------------
# Tests: _safe_int
# ---------------------------------------------------------------------------
class TestSafeInt(unittest.TestCase):
    def test_normal_int(self):
        self.assertEqual(tracker._safe_int(42), 42)

    def test_float_truncated(self):
        self.assertEqual(tracker._safe_int(3.9), 3)

    def test_string_number(self):
        self.assertEqual(tracker._safe_int("75"), 75)

    def test_string_float(self):
        self.assertEqual(tracker._safe_int("99.7"), 99)

    def test_none_returns_default(self):
        self.assertEqual(tracker._safe_int(None), 0)
        self.assertEqual(tracker._safe_int(None, 5), 5)

    def test_negative_clamped_to_zero(self):
        self.assertEqual(tracker._safe_int(-10), 0)

    def test_invalid_string(self):
        self.assertEqual(tracker._safe_int("abc"), 0)

    def test_empty_string(self):
        self.assertEqual(tracker._safe_int(""), 0)

    def test_bool_true(self):
        self.assertEqual(tracker._safe_int(True), 1)

    def test_zero(self):
        self.assertEqual(tracker._safe_int(0), 0)

    def test_large_value(self):
        self.assertEqual(tracker._safe_int(999999), 999999)

    def test_overflow_value_returns_default(self):
        # Hostile feed: an overflowing number (1e400 → inf) must not crash the
        # refresh (int(inf) raises OverflowError). See the _safe_int hardening.
        self.assertEqual(tracker._safe_int("1e400"), 0)
        self.assertEqual(tracker._safe_int(float("inf")), 0)


# ---------------------------------------------------------------------------
# Tests: fmt_reset
# ---------------------------------------------------------------------------
class TestFmtReset(unittest.TestCase):
    def test_none_returns_dashes(self):
        self.assertEqual(tracker.fmt_reset(None), "--")

    def test_empty_returns_dashes(self):
        self.assertEqual(tracker.fmt_reset(""), "--")

    def test_past_returns_now(self):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        self.assertEqual(tracker.fmt_reset(past), "now")

    def test_minutes_away(self):
        future = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
        result = tracker.fmt_reset(future)
        self.assertIn("m", result)
        self.assertNotIn("h", result)

    def test_hours_away(self):
        future = (datetime.now(timezone.utc) + timedelta(hours=2, minutes=15)).isoformat()
        result = tracker.fmt_reset(future)
        self.assertIn("h", result)
        self.assertIn("m", result)

    def test_days_away(self):
        future = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
        result = tracker.fmt_reset(future)
        # Should return date like "Mar 11"
        self.assertRegex(result, r"[A-Z][a-z]{2} \d{2}")

    def test_z_suffix(self):
        future = (datetime.now(timezone.utc) + timedelta(hours=1))
        iso = future.strftime("%Y-%m-%dT%H:%M:%SZ")
        result = tracker.fmt_reset(iso)
        self.assertNotEqual(result, "?")
        self.assertNotEqual(result, "--")

    def test_with_subseconds(self):
        future = (datetime.now(timezone.utc) + timedelta(hours=1))
        iso = future.strftime("%Y-%m-%dT%H:%M:%S.123456Z")
        result = tracker.fmt_reset(iso)
        self.assertNotEqual(result, "?")

    def test_invalid_iso(self):
        self.assertEqual(tracker.fmt_reset("not-a-date"), "?")

    def test_offset_with_colon(self):
        future = (datetime.now(timezone.utc) + timedelta(hours=1))
        iso = future.strftime("%Y-%m-%dT%H:%M:%S+00:00")
        result = tracker.fmt_reset(iso)
        self.assertNotEqual(result, "?")

    def test_non_string_input_does_not_crash(self):
        # A numeric resets_at (data regression) must degrade gracefully —
        # _parse_iso guards AttributeError/TypeError instead of raising.
        self.assertIsNone(tracker._parse_iso(1718304000))
        self.assertIn(tracker.fmt_reset(1718304000), ("--", "?"))


# ---------------------------------------------------------------------------
# Tests: App display logic (2 rings, statusline source)
# ---------------------------------------------------------------------------
class TestAppDisplay(unittest.TestCase):
    def _make_app(self):
        """Create App instance with mocked timer/refresh to avoid side effects."""
        with patch.object(tracker.App, "_start_timer"), \
             patch.object(tracker.App, "_refresh"):
            app = tracker.App()
        return app

    def test_full_data_display(self):
        app = self._make_app()
        data = _make_usage(five_hour_pct=42, seven_day_pct=18)
        app._update_display(data)
        self.assertEqual(app.title, "42%")
        self.assertIn("5-hour: 42%", app.m5h.title)
        self.assertIn("Weekly: 18%", app.m7d.title)
        self.assertIn("via Claude Code", app.mupd.title)

    def test_missing_five_hour(self):
        app = self._make_app()
        data = _make_usage()
        del data["five_hour"]
        app._update_display(data)
        self.assertEqual(app.title, "—")  # window absent → "—" badge, not "0%"
        self.assertEqual(app.m5h.title, tracker.FIVE_HOUR_DEFAULT)

    def test_missing_seven_day(self):
        app = self._make_app()
        data = _make_usage()
        del data["seven_day"]
        app._update_display(data)
        self.assertEqual(app.m7d.title, tracker.WEEKLY_DEFAULT)

    def test_all_sections_missing(self):
        app = self._make_app()
        app._update_display({})
        self.assertEqual(app.title, "—")  # no window at all → "—" badge, not "0%"
        self.assertEqual(app.m5h.title, tracker.FIVE_HOUR_DEFAULT)
        self.assertEqual(app.m7d.title, tracker.WEEKLY_DEFAULT)

    def test_only_two_rings_rendered(self):
        # _render_dynamic_icon only takes session + weekly (no more inner ring).
        app = self._make_app()
        with patch.object(tracker, "_render_dynamic_icon") as render:
            app._update_display(_make_usage(five_hour_pct=30, seven_day_pct=40))
        render.assert_called_once_with(30, 40)


# ---------------------------------------------------------------------------
# Tests: App error states (statusline-only: nostatusline, waiting, error)
# ---------------------------------------------------------------------------
class TestAppErrorStates(unittest.TestCase):
    def _make_app(self):
        with patch.object(tracker.App, "_start_timer"), \
             patch.object(tracker.App, "_refresh"):
            app = tracker.App()
        return app

    def test_generic_error(self):
        app = self._make_app()
        app._apply_usage(None, "error")
        self.assertEqual(app.title, "?")

    def test_none_data_no_error(self):
        app = self._make_app()
        app._apply_usage(None, None)
        self.assertEqual(app.title, "?")

    def test_success_calls_update_display(self):
        app = self._make_app()
        data = _make_usage(five_hour_pct=77)
        app._apply_usage(data, None)
        self.assertEqual(app.title, "77%")


# ---------------------------------------------------------------------------
# Tests: Interval management
# ---------------------------------------------------------------------------
class TestIntervalManagement(unittest.TestCase):
    def _make_app(self):
        with patch.object(tracker.App, "_start_timer"), \
             patch.object(tracker.App, "_refresh"):
            app = tracker.App()
        return app

    def test_default_interval(self):
        app = self._make_app()
        self.assertEqual(app.interval, 300)

    def test_interval_menu_checkmarks(self):
        app = self._make_app()
        app._update_interval_menu()
        for secs, item in app._interval_items.items():
            if secs == 300:
                self.assertEqual(item.state, 1)
            else:
                self.assertEqual(item.state, 0)

    def test_change_interval(self):
        app = self._make_app()
        sender = FakeMenuItem("Every 1 minute")
        with patch.object(app, "_start_timer"):
            app._set_interval(sender)
        self.assertEqual(app.interval, 60)
        self.assertEqual(app._interval_items[60].state, 1)
        self.assertEqual(app._interval_items[300].state, 0)

    def test_corrupted_interval_falls_back(self):
        # A non-numeric persisted value must not crash __init__ (startup).
        def fake_get(key, default=None):
            return "notanumber" if key == tracker._KEY_INTERVAL else default
        with patch("tracker._settings_get", side_effect=fake_get), \
             patch.object(tracker.App, "_start_timer"), \
             patch.object(tracker.App, "_refresh"):
            app = tracker.App()
        self.assertEqual(app.interval, 300)

    def test_zero_interval_clamped(self):
        # A persisted 0 must clamp to >= 60 so rumps.Timer is never given 0.
        def fake_get(key, default=None):
            return 0 if key == tracker._KEY_INTERVAL else default
        with patch("tracker._settings_get", side_effect=fake_get), \
             patch.object(tracker.App, "_start_timer"), \
             patch.object(tracker.App, "_refresh"):
            app = tracker.App()
        self.assertGreaterEqual(app.interval, 60)


# ---------------------------------------------------------------------------
# Tests: Main-thread marshalling (regression for SIGABRT crash)
# ---------------------------------------------------------------------------
class TestMainThreadMarshalling(unittest.TestCase):
    """Regression: AppKit assertion-fails and SIGABRTs the app if NSStatusItem
    is mutated off the main thread. _fetch_and_update runs on a worker thread,
    so _apply_usage MUST be marshalled via _call_on_main."""

    def _make_app(self):
        with patch.object(tracker.App, "_start_timer"), \
             patch.object(tracker.App, "_refresh"):
            app = tracker.App()
        return app

    def test_fetch_marshals_apply_usage_to_main_thread(self):
        app = self._make_app()
        # _fetch_and_update dispatches via fetch_usage(); mock at that boundary
        # so the test stays focused on the marshalling behaviour.
        with patch.object(tracker, "_call_on_main") as marshall, \
             patch.object(tracker, "fetch_usage", return_value=({"foo": "bar"}, None)):
            app._fetch_and_update()
        marshall.assert_called_once_with(app._apply_usage, {"foo": "bar"}, None)

    def test_reset_timer_callback_marshals_refresh(self):
        app = self._make_app()
        future = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
        data = _make_usage(five_hour_resets=future)
        with patch("threading.Timer") as MockTimer:
            MockTimer.return_value = MagicMock()
            app._schedule_reset_refresh(data)
            # Invoke the registered callback and confirm it goes through _call_on_main.
            callback = MockTimer.call_args[0][1]
            with patch.object(tracker, "_call_on_main") as marshall:
                callback()
            marshall.assert_called_once_with(app._refresh, None)


# ---------------------------------------------------------------------------
# Tests: Proactive reset-window refresh
# ---------------------------------------------------------------------------
class TestResetRefreshScheduling(unittest.TestCase):
    """Bug: if the user picks a long refresh interval, the menu would show
    pre-reset numbers for up to a full interval after a window rolls over.
    Fix schedules a one-shot timer to fire ~5s after the soonest reset."""

    def _make_app(self):
        with patch.object(tracker.App, "_start_timer"), \
             patch.object(tracker.App, "_refresh"):
            app = tracker.App()
        return app

    def test_schedules_timer_for_soonest_future_reset(self):
        app = self._make_app()
        now = datetime.now(timezone.utc)
        five_hour_iso = (now + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
        weekly_iso    = (now + timedelta(days=2)).isoformat().replace("+00:00", "Z")
        data = _make_usage(five_hour_resets=five_hour_iso, seven_day_resets=weekly_iso)
        with patch("threading.Timer") as MockTimer:
            mock_timer = MagicMock()
            MockTimer.return_value = mock_timer
            app._schedule_reset_refresh(data)
            self.assertTrue(MockTimer.called)
            delay = MockTimer.call_args[0][0]
            # Expect ~10 minutes + 5s buffer; allow 2s slack for clock drift.
            self.assertAlmostEqual(delay, 600 + 5, delta=2)
            mock_timer.start.assert_called_once()

    def test_cancels_previous_timer_when_rescheduling(self):
        app = self._make_app()
        prev_timer = MagicMock()
        app._reset_timer = prev_timer
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        data = _make_usage(five_hour_resets=future)
        with patch("threading.Timer", return_value=MagicMock()):
            app._schedule_reset_refresh(data)
        prev_timer.cancel.assert_called_once()

    def test_ignores_already_passed_resets(self):
        app = self._make_app()
        past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
        data = _make_usage(five_hour_resets=past, seven_day_resets=past)
        with patch("threading.Timer") as MockTimer:
            app._schedule_reset_refresh(data)
            MockTimer.assert_not_called()
        self.assertIsNone(app._reset_timer)

    def test_skips_malformed_iso_timestamps(self):
        app = self._make_app()
        data = _make_usage(five_hour_resets="not-a-date", seven_day_resets=None)
        with patch("threading.Timer") as MockTimer:
            app._schedule_reset_refresh(data)
            MockTimer.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: Constants integrity
# ---------------------------------------------------------------------------
class TestConstants(unittest.TestCase):
    def test_intervals_all_positive(self):
        for label, secs in tracker.INTERVALS.items():
            self.assertGreater(secs, 0, f"Interval '{label}' must be positive")

    def test_default_strings_consistent(self):
        self.assertIn("5-hour", tracker.FIVE_HOUR_DEFAULT)
        self.assertIn("Weekly", tracker.WEEKLY_DEFAULT)

    def test_two_rings_only(self):
        # Icon geometry = 2 rings (outer 5h, inner weekly).
        self.assertEqual(len(tracker._RING_RADII), 2)


# ---------------------------------------------------------------------------
# Tests: Edge cases in display with weird data
# ---------------------------------------------------------------------------
class TestEdgeCases(unittest.TestCase):
    def _make_app(self):
        with patch.object(tracker.App, "_start_timer"), \
             patch.object(tracker.App, "_refresh"):
            app = tracker.App()
        return app

    def test_negative_utilization(self):
        app = self._make_app()
        data = {"five_hour": {"utilization": -50, "resets_at": None},
                "_meta": {"captured_at": datetime.now(timezone.utc).timestamp()}}
        app._update_display(data)
        self.assertEqual(app.title, "0%")
        self.assertIn("0%", app.m5h.title)

    def test_string_utilization(self):
        app = self._make_app()
        data = {"five_hour": {"utilization": "85", "resets_at": None},
                "_meta": {"captured_at": datetime.now(timezone.utc).timestamp()}}
        app._update_display(data)
        self.assertEqual(app.title, "85%")

    def test_null_utilization(self):
        app = self._make_app()
        data = {"five_hour": {"utilization": None, "resets_at": None},
                "_meta": {"captured_at": datetime.now(timezone.utc).timestamp()}}
        app._update_display(data)
        self.assertEqual(app.title, "0%")

    def test_zero_percent_all(self):
        app = self._make_app()
        data = _make_usage(five_hour_pct=0, seven_day_pct=0)
        app._update_display(data)
        self.assertEqual(app.title, "0%")
        self.assertIn("0%", app.m5h.title)
        self.assertIn("0%", app.m7d.title)

    def test_hundred_percent(self):
        app = self._make_app()
        data = _make_usage(five_hour_pct=100)
        app._update_display(data)
        self.assertEqual(app.title, "100%")

    def test_over_hundred_clamped_in_title(self):
        # The feed can go above 100; the title and the icon must be clamped.
        app = self._make_app()
        with patch.object(tracker, "_render_dynamic_icon") as render:
            app._update_display(_make_usage(five_hour_pct=150, seven_day_pct=130))
        self.assertEqual(app.title, "100%")
        render.assert_called_once_with(100, 100)
        # the dropdown menu line must be clamped too (not just the title/icon)
        self.assertIn("5-hour: 100%", app.m5h.title)
        self.assertIn("Weekly: 100%", app.m7d.title)


# ---------------------------------------------------------------------------
# Tests: clear stale icon on error
# ---------------------------------------------------------------------------
class TestErrorClearsStaleIcon(unittest.TestCase):
    """Bug: after a successful render sets a ring icon, an error state left the
    stale icon visible — misleading in ICON mode (title is empty) and
    contradictory in BOTH mode (error glyph + full ring)."""

    def _make_app(self):
        with patch.object(tracker.App, "_start_timer"), \
             patch.object(tracker.App, "_refresh"):
            return tracker.App()

    def _seed_icon(self, app, mode):
        app.display_mode = mode
        app._update_display(_make_usage(five_hour_pct=90))

    def test_error_clears_icon_in_both_mode(self):
        app = self._make_app()
        self._seed_icon(app, tracker.DISPLAY_BOTH)
        app._apply_usage(None, "error")
        self.assertIsNone(app.icon)

    def test_none_data_clears_icon(self):
        app = self._make_app()
        self._seed_icon(app, tracker.DISPLAY_ICON)
        app._apply_usage(None, None)
        self.assertIsNone(app.icon)


# ---------------------------------------------------------------------------
# Tests: threshold-crossing notifications
# ---------------------------------------------------------------------------
class TestMaybeNotify(unittest.TestCase):
    """Threshold-crossing notifications: fire only on upward crossing, never on
    first observation, never repeatedly at a plateau, never when disabled."""

    def _make_app(self):
        with patch.object(tracker.App, "_start_timer"), \
             patch.object(tracker.App, "_refresh"):
            return tracker.App()

    def _fire(self, app, sequence):
        calls = []
        with patch.object(tracker.rumps, "notification",
                          side_effect=lambda **k: calls.append(k)):
            for pct in sequence:
                app._maybe_notify(pct)
        return calls

    def test_no_notify_on_first_observation(self):
        app = self._make_app()
        app.alerts_enabled = True
        app._last_pct = None
        calls = self._fire(app, [99])
        self.assertEqual(calls, [])
        self.assertEqual(app._last_pct, 99)

    def test_notify_on_crossing_80(self):
        app = self._make_app()
        app.alerts_enabled = True
        app._last_pct = 50
        calls = self._fire(app, [85])
        self.assertEqual(len(calls), 1)
        self.assertIn("80%", calls[0]["message"])

    def test_crossing_both_thresholds_at_once_picks_highest(self):
        app = self._make_app()
        app.alerts_enabled = True
        app._last_pct = 10
        calls = self._fire(app, [97])
        self.assertEqual(len(calls), 1)
        self.assertIn("95%", calls[0]["message"])

    def test_no_repeat_at_plateau(self):
        app = self._make_app()
        app.alerts_enabled = True
        app._last_pct = 50
        calls = self._fire(app, [85, 90, 88])
        self.assertEqual(len(calls), 1)

    def test_disabled_never_notifies(self):
        app = self._make_app()
        app.alerts_enabled = False
        app._last_pct = 50
        calls = self._fire(app, [99])
        self.assertEqual(calls, [])
        self.assertEqual(app._last_pct, 99)

    def test_notification_exception_swallowed(self):
        app = self._make_app()
        app.alerts_enabled = True
        app._last_pct = 50
        with patch.object(tracker.rumps, "notification",
                          side_effect=RuntimeError("unsigned bundle")):
            app._maybe_notify(85)

    def test_drop_below_then_recross_renotifies(self):
        app = self._make_app()
        app.alerts_enabled = True
        app._last_pct = 50
        calls = self._fire(app, [85, 50, 85])
        self.assertEqual(len(calls), 2)


# ---------------------------------------------------------------------------
# Tests: display modes (icon / pct / both)
# ---------------------------------------------------------------------------
class TestApplyDisplayModes(unittest.TestCase):
    def _make_app(self):
        with patch.object(tracker.App, "_start_timer"), \
             patch.object(tracker.App, "_refresh"):
            return tracker.App()

    def test_pct_mode_clears_icon_and_sets_bare_title(self):
        app = self._make_app()
        app.display_mode = tracker.DISPLAY_PCT
        app._apply_display("42%", "stub-icon-a.png")
        self.assertEqual(app.title, "42%")
        self.assertIsNone(app.icon)

    def test_icon_mode_empties_title_and_sets_icon(self):
        app = self._make_app()
        app.display_mode = tracker.DISPLAY_ICON
        app._apply_display("42%", "stub-icon-b.png")
        self.assertEqual(app.title, "")
        self.assertEqual(app.icon, "stub-icon-b.png")

    def test_both_mode_prefixes_spacer(self):
        app = self._make_app()
        app.display_mode = tracker.DISPLAY_BOTH
        with patch.object(tracker, "_TITLE_SPACER", "  "):
            app._apply_display("42%", "stub-icon-b.png")
        self.assertEqual(app.title, "  42%")
        self.assertEqual(app.icon, "stub-icon-b.png")

    def test_none_icon_path_leaves_icon_untouched(self):
        app = self._make_app()
        app.display_mode = tracker.DISPLAY_ICON
        app.icon = "stub-previous.png"
        app._apply_display("42%", None)
        self.assertEqual(app.icon, "stub-previous.png")

    def test_set_display_mode_persists_and_checks_radio(self):
        app = self._make_app()
        sender = SimpleNamespace(_mode=tracker.DISPLAY_ICON)
        with patch("tracker._settings_set") as save, \
             patch.object(app, "_refresh"):
            app._set_display_mode(sender)
        self.assertEqual(app.display_mode, tracker.DISPLAY_ICON)
        save.assert_called_once_with(tracker._KEY_DISPLAY_MODE, tracker.DISPLAY_ICON)
        self.assertEqual(app._display_items[tracker.DISPLAY_ICON].state, 1)
        self.assertEqual(app._display_items[tracker.DISPLAY_BOTH].state, 0)


# ---------------------------------------------------------------------------
# Tests: pre-reset guard (ADR 0004, scenario C7)
# ---------------------------------------------------------------------------
class TestPreResetGuard(unittest.TestCase):
    """A desktop sample taken before a reset the terminal already reported
    describes the window that ended. It used to show as fresh, often at 100 %,
    for up to one desktop cadence (p90 45 min)."""

    def _make_app(self):
        with patch.object(tracker.App, "_start_timer"), \
             patch.object(tracker.App, "_refresh"):
            app = tracker.App()
        app.display_mode = tracker.DISPLAY_PCT
        return app

    @staticmethod
    def _desktop_reading(pct, captured_at):
        """A desktop-filled 5h window: a percentage and no reset time."""
        return {
            "five_hour": {"utilization": pct},
            "seven_day": {"utilization": 18, "resets_at": "2099-03-10T00:00:00Z"},
            "_meta": {"captured_at": captured_at, "source": "desktop"},
        }

    def test_sample_predating_a_passed_reset_is_voided(self):
        now = datetime.now(timezone.utc)
        reset = now - timedelta(minutes=10)
        app = self._make_app()
        app._last_reset = reset.isoformat().replace("+00:00", "Z")
        app._last_pct = 100
        # measured before the reset the terminal already reported
        app._update_display(
            self._desktop_reading(100, (reset - timedelta(minutes=5)).timestamp()))
        self.assertEqual(app.title, "—")
        self.assertIn("—", app.m5h.title)

    def test_sample_taken_after_the_reset_is_shown(self):
        now = datetime.now(timezone.utc)
        reset = now - timedelta(minutes=10)
        app = self._make_app()
        app._last_reset = reset.isoformat().replace("+00:00", "Z")
        app._last_pct = 100
        app._update_display(
            self._desktop_reading(7, (reset + timedelta(minutes=1)).timestamp()))
        self.assertEqual(app.title, "7%")

    def test_no_known_reset_leaves_the_reading_alone(self):
        now = datetime.now(timezone.utc)
        app = self._make_app()
        app._last_reset = None
        app._update_display(self._desktop_reading(63, now.timestamp()))
        self.assertEqual(app.title, "63%")

    def test_reset_still_ahead_leaves_the_reading_alone(self):
        now = datetime.now(timezone.utc)
        app = self._make_app()
        app._last_reset = (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        app._update_display(self._desktop_reading(63, now.timestamp()))
        self.assertEqual(app.title, "63%")

    def test_voided_window_keeps_the_reset_on_file_for_the_next_render(self):
        """The guard reads _last_reset before _maybe_notify could clear it, and
        a voided window skips the notify path, so the evidence survives until a
        sample taken after the reset arrives. Pins that ordering."""
        now = datetime.now(timezone.utc)
        reset = now - timedelta(minutes=10)
        stamp = reset.isoformat().replace("+00:00", "Z")
        app = self._make_app()
        app._last_reset = stamp
        app._last_pct = 100
        app._update_display(
            self._desktop_reading(100, (reset - timedelta(minutes=5)).timestamp()))
        self.assertEqual(app._last_reset, stamp)
        # second render, same stale sample: still voided
        app._update_display(
            self._desktop_reading(100, (reset - timedelta(minutes=4)).timestamp()))
        self.assertEqual(app.title, "—")

    def test_a_voided_window_raises_no_alert(self):
        now = datetime.now(timezone.utc)
        reset = now - timedelta(minutes=10)
        app = self._make_app()
        app._last_reset = reset.isoformat().replace("+00:00", "Z")
        app._last_pct = 50
        app.alerts_enabled = True
        with patch.object(tracker.rumps, "notification") as notif:
            app._update_display(
                self._desktop_reading(100, (reset - timedelta(minutes=5)).timestamp()))
        notif.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: icon write failure must not break the title
# ---------------------------------------------------------------------------
@unittest.skipUnless(tracker._PILLOW_AVAILABLE, "Pillow absent: no PNG is written")
class TestIconWriteFailure(unittest.TestCase):
    """A full disk or a read-only ~/.tokease used to raise out of
    _update_display before _apply_display ran, leaving the title on '...'."""

    def _make_app(self):
        with patch.object(tracker.App, "_start_timer"), \
             patch.object(tracker.App, "_refresh"):
            return tracker.App()

    def test_oserror_on_save_keeps_title_and_previous_icon(self):
        app = self._make_app()
        app.display_mode = tracker.DISPLAY_BOTH
        app.icon = "stub-previous.png"
        with patch.object(tracker.Image.Image, "save", side_effect=OSError("disk full")):
            app._update_display(_make_usage(five_hour_pct=42))
        self.assertEqual(app.title, "42%")
        self.assertEqual(app.icon, "stub-previous.png")


# ---------------------------------------------------------------------------
# Tests: corrupted settings
# ---------------------------------------------------------------------------
class TestCorruptedSettings(unittest.TestCase):
    def test_invalid_display_mode_falls_back_to_both(self):
        def fake_get(key, default=None):
            return "garbage_mode" if key == tracker._KEY_DISPLAY_MODE else default
        with patch("tracker._settings_get", side_effect=fake_get), \
             patch.object(tracker.App, "_start_timer"), \
             patch.object(tracker.App, "_refresh"):
            app = tracker.App()
        self.assertEqual(app.display_mode, tracker.DISPLAY_BOTH)

    def test_falsy_alerts_setting_coerced_to_bool(self):
        def fake_get(key, default=None):
            return 0 if key == tracker._KEY_ALERTS else default
        with patch("tracker._settings_get", side_effect=fake_get), \
             patch.object(tracker.App, "_start_timer"), \
             patch.object(tracker.App, "_refresh"):
            app = tracker.App()
        self.assertIs(app.alerts_enabled, False)

    def test_toggle_alerts_persists_and_flips_state(self):
        with patch.object(tracker.App, "_start_timer"), \
             patch.object(tracker.App, "_refresh"):
            app = tracker.App()
        app.alerts_enabled = True
        sender = FakeMenuItem("Alert")
        sender.state = 1
        with patch("tracker._settings_set") as save:
            app._toggle_alerts(sender)
        self.assertFalse(app.alerts_enabled)
        self.assertEqual(sender.state, 0)
        save.assert_called_once_with(tracker._KEY_ALERTS, False)


# ---------------------------------------------------------------------------
# Tests: unknown buckets ignored
# ---------------------------------------------------------------------------
class TestUnknownBuckets(unittest.TestCase):
    """The feed could contain other keys (codenames) — they must be ignored,
    only five_hour/seven_day count."""

    def _make_app(self):
        with patch.object(tracker.App, "_start_timer"), \
             patch.object(tracker.App, "_refresh"):
            return tracker.App()

    def test_unknown_buckets_do_not_affect_display(self):
        app = self._make_app()
        data = {
            "five_hour": {"utilization": 30, "resets_at": None},
            "seven_day_cowork": {"utilization": 99, "resets_at": None},
            "oauth_apps": None,
            "omelette": {"utilization": 88, "resets_at": None},
            "_meta": {"captured_at": datetime.now(timezone.utc).timestamp()},
        }
        app._update_display(data)
        self.assertEqual(app.title, "30%")
        self.assertEqual(app.m7d.title, tracker.WEEKLY_DEFAULT)

    def test_unknown_bucket_reset_not_scheduled(self):
        app = self._make_app()
        now = datetime.now(timezone.utc)
        soon = (now + timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
        data = {
            "five_hour": {"utilization": 30, "resets_at": None},
            "seven_day_cowork": {"utilization": 50, "resets_at": soon},
        }
        with patch("threading.Timer") as MockTimer:
            app._schedule_reset_refresh(data)
            MockTimer.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: section present but resets_at null
# ---------------------------------------------------------------------------
class TestSectionPresentNullReset(unittest.TestCase):
    """A live section with utilization but resets_at: null must render the pct
    and show 'resets --' without scheduling a reset timer."""

    def _make_app(self):
        with patch.object(tracker.App, "_start_timer"), \
             patch.object(tracker.App, "_refresh"):
            return tracker.App()

    def test_null_reset_renders_pct_with_dashes(self):
        app = self._make_app()
        data = {
            "five_hour": {"utilization": 44, "resets_at": None},
            "seven_day": {"utilization": 22, "resets_at": None},
            "_meta": {"captured_at": datetime.now(timezone.utc).timestamp()},
        }
        app._update_display(data)
        self.assertIn("5-hour: 44%", app.m5h.title)
        self.assertIn("resets --", app.m5h.title)
        self.assertEqual(app.title, "44%")

    def test_null_reset_schedules_no_timer(self):
        app = self._make_app()
        data = _make_usage(five_hour_resets=None, seven_day_resets=None)
        with patch("threading.Timer") as MockTimer:
            app._schedule_reset_refresh(data)
            MockTimer.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: _epoch_to_iso
# ---------------------------------------------------------------------------
class TestEpochToIso(unittest.TestCase):
    def test_valid_epoch_round_trips(self):
        iso = tracker._epoch_to_iso(1800000000)
        self.assertIsNotNone(tracker._parse_iso(iso))

    def test_none(self):
        self.assertIsNone(tracker._epoch_to_iso(None))

    def test_non_numeric(self):
        self.assertIsNone(tracker._epoch_to_iso("not-a-number"))

    def test_iso_string_passes_through(self):
        # claude-code#40094: resets_at can already arrive as ISO, not epoch.
        out = tracker._epoch_to_iso("2026-03-28T15:00:00Z")
        self.assertIsNotNone(tracker._parse_iso(out))


# ---------------------------------------------------------------------------
# Tests: fetch_usage (pure read of the statusline file)
# ---------------------------------------------------------------------------
class TestStatuslineSource(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self._file = Path(self._td.name) / "usage.json"
        self._patcher = patch.object(tracker, "_STATUSLINE_FILE", self._file)
        self._patcher.start()
        # Isolate the desktop source: the dev machine may have the real file.
        self._desktop = Path(self._td.name) / "plan-usage-history.json"
        self._desktop_patcher = patch.object(
            tracker, "_DESKTOP_HISTORY_FILE", self._desktop
        )
        self._desktop_patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._desktop_patcher.stop()
        self._td.cleanup()

    def _write(self, payload):
        self._file.write_text(json.dumps(payload), encoding="utf-8")

    def test_nostatusline_when_file_missing(self):
        data, err = tracker.fetch_usage()
        self.assertIsNone(data)
        self.assertEqual(err, "nostatusline")

    def test_waiting_when_no_windows(self):
        self._write({"schema": 1, "captured_at": 100, "source": "x"})
        data, err = tracker.fetch_usage()
        self.assertIsNone(data)
        self.assertEqual(err, "waiting")

    def test_error_on_invalid_json(self):
        self._file.write_text("not json{{{", encoding="utf-8")
        _, err = tracker.fetch_usage()
        self.assertEqual(err, "error")

    def test_error_when_payload_not_dict(self):
        self._file.write_text("[1, 2, 3]", encoding="utf-8")
        _, err = tracker.fetch_usage()
        self.assertEqual(err, "error")

    def test_normalizes_both_windows(self):
        self._write({
            "schema": 1, "captured_at": 1799999000,
            "five_hour": {"used_percentage": 23.5, "resets_at": 1800000000},
            "seven_day": {"used_percentage": 41, "resets_at": 1800500000},
        })
        data, err = tracker.fetch_usage()
        self.assertIsNone(err)
        self.assertEqual(data["five_hour"]["utilization"], 23.5)
        self.assertIn("seven_day", data)
        self.assertEqual(data["_meta"]["captured_at"], 1799999000)
        self.assertIsNotNone(tracker._parse_iso(data["five_hour"]["resets_at"]))

    def test_partial_only_five_hour(self):
        self._write({"captured_at": 1, "five_hour": {"used_percentage": 10, "resets_at": 2}})
        data, err = tracker.fetch_usage()
        self.assertIsNone(err)
        self.assertIn("five_hour", data)
        self.assertNotIn("seven_day", data)

    def test_window_without_percentage_is_waiting(self):
        self._write({"captured_at": 1, "five_hour": {"resets_at": 2}})
        _, err = tracker.fetch_usage()
        self.assertEqual(err, "waiting")

    def test_resets_at_as_iso_string(self):
        # Contract #40094: if Claude Code passes resets_at as ISO (not epoch),
        # the countdown must not silently disappear.
        self._write({
            "captured_at": 1799999000,
            "five_hour": {"used_percentage": 12, "resets_at": "2099-01-01T00:00:00Z"},
        })
        data, err = tracker.fetch_usage()
        self.assertIsNone(err)
        self.assertIsNotNone(tracker._parse_iso(data["five_hour"]["resets_at"]))


# ---------------------------------------------------------------------------
# Tests: desktop app secondary source + merge (ADR 0003)
# ---------------------------------------------------------------------------
class TestDesktopSource(TestStatuslineSource):
    """Reuses TestStatuslineSource's file isolation (the parent tests re-run
    here on the same patches — benign and intentional redundancy: they must
    stay green with the desktop source wired but absent)."""

    def _write_desktop(self, payload):
        self._desktop.write_text(json.dumps(payload), encoding="utf-8")

    def _sample(self, t_ms, fh=None, sd=None):
        u = {}
        if fh is not None:
            u["fh"] = fh
        if sd is not None:
            u["sd"] = sd
        return {"t": t_ms, "org": "org-1", "u": u}

    def test_desktop_only_no_statusline(self):
        # Zero config: desktop app present, statusline never wired.
        self._write_desktop({"version": 2, "samples": [self._sample(1800000000000, fh=34, sd=24)]})
        data, err = tracker.fetch_usage()
        self.assertIsNone(err)
        self.assertEqual(data["five_hour"]["utilization"], 34)
        self.assertEqual(data["seven_day"]["utilization"], 24)
        self.assertIsNone(data["five_hour"]["resets_at"])
        self.assertEqual(data["_meta"]["captured_at"], 1800000000.0)
        self.assertEqual(data["_meta"]["source"], "desktop")

    def test_fresh_windowless_statusline_does_not_discard_desktop(self):
        # Claude Code renders the statusline before it has rate_limits (session
        # start). That capture is the freshest file on disk but carries no
        # window: it must not hide a usable desktop reading, or a dual-source
        # user sees "waiting" every time they open a session.
        now = datetime.now(timezone.utc).timestamp()
        self._write({"schema": 1, "captured_at": now, "source": "claude-code-statusline"})
        self._write_desktop({"version": 2, "samples": [
            self._sample(int((now - 120) * 1000), fh=55, sd=20),
        ]})
        data, err = tracker.fetch_usage()
        self.assertIsNone(err)
        self.assertEqual(data["five_hour"]["utilization"], 55)
        self.assertEqual(data["seven_day"]["utilization"], 20)
        # And the timestamp shown is the desktop's own, not the empty capture's:
        # an older reading is never displayed under a fresher "Updated" line.
        self.assertAlmostEqual(data["_meta"]["captured_at"], now - 120, delta=1)

    def test_last_valid_sample_wins_skipping_malformed(self):
        self._write_desktop({"version": 2, "samples": [
            self._sample(1000_000, fh=10),
            self._sample(2000_000, fh=20),
            {"t": "not-a-number", "u": {"fh": 99}},
            {"unexpected": "shape"},
        ]})
        data, _ = tracker.fetch_usage()
        self.assertEqual(data["five_hour"]["utilization"], 20)

    def test_unknown_version_is_ignored(self):
        self._write_desktop({"version": 3, "samples": [self._sample(1, fh=50)]})
        data, err = tracker.fetch_usage()
        self.assertIsNone(data)
        self.assertEqual(err, "nostatusline")  # behavior unchanged without desktop

    def test_invalid_desktop_file_is_ignored(self):
        self._desktop.write_text("not json{{{", encoding="utf-8")
        _, err = tracker.fetch_usage()
        self.assertEqual(err, "nostatusline")

    def test_samples_not_a_list_is_ignored(self):
        self._write_desktop({"version": 2, "samples": {"fh": 12}})
        _, err = tracker.fetch_usage()
        self.assertEqual(err, "nostatusline")

    def test_merge_fresher_desktop_keeps_future_reset(self):
        future = "2099-01-01T00:00:00+00:00"
        self._write({
            "captured_at": 1000,
            "five_hour": {"used_percentage": 10, "resets_at": future},
        })
        self._write_desktop({"version": 2, "samples": [self._sample(2000_000, fh=42, sd=7)]})
        data, err = tracker.fetch_usage()
        self.assertIsNone(err)
        self.assertEqual(data["five_hour"]["utilization"], 42)
        self.assertEqual(data["five_hour"]["resets_at"], future)  # statusline reset kept
        self.assertEqual(data["seven_day"]["utilization"], 7)
        self.assertEqual(data["_meta"]["source"], "desktop")

    def test_merge_desktop_sampled_after_reset_drops_past_reset(self):
        # Reset in the past but desktop sample after it → its % does describe
        # the current window: displayed without a countdown.
        self._write({
            "captured_at": 1000,
            "five_hour": {"used_percentage": 10, "resets_at": 2000},  # epoch 1970 → past
        })
        self._write_desktop({"version": 2, "samples": [self._sample(3000_000, fh=42)]})
        data, _ = tracker.fetch_usage()
        self.assertEqual(data["five_hour"]["utilization"], 42)
        self.assertIsNone(data["five_hour"]["resets_at"])

    def test_merge_desktop_sampled_before_reset_defers_to_statusline(self):
        # Desktop sample before the reset → its % describes the OLD window:
        # return the statusline version (which the display marks as
        # "reset; awaiting") rather than a plausible old %.
        now = datetime.now(timezone.utc).timestamp()
        self._write({
            "captured_at": int(now - 600),
            "five_hour": {"used_percentage": 80, "resets_at": int(now - 30)},
        })
        self._write_desktop({"version": 2,
                             "samples": [self._sample(int((now - 120) * 1000), fh=80)]})
        data, _ = tracker.fetch_usage()
        self.assertEqual(data["five_hour"]["utilization"], 80)
        # resets_at (past) kept → _window_row will render the "reset" state
        self.assertIsNotNone(data["five_hour"]["resets_at"])

    def test_merge_fresher_statusline_wins(self):
        self._write({
            "captured_at": 3000,
            "five_hour": {"used_percentage": 10, "resets_at": None},
        })
        self._write_desktop({"version": 2, "samples": [self._sample(2000_000, fh=42)]})
        data, _ = tracker.fetch_usage()
        self.assertEqual(data["five_hour"]["utilization"], 10)
        self.assertEqual(data["_meta"]["source"], "statusline")

    def test_merge_window_missing_from_desktop_kept_if_statusline_fresh(self):
        now = datetime.now(timezone.utc).timestamp()
        self._write({
            "captured_at": int(now - 300),  # fresh (< _STALE_AFTER_SECS)
            "seven_day": {"used_percentage": 55, "resets_at": None},
        })
        self._write_desktop({"version": 2,
                             "samples": [self._sample(int((now - 60) * 1000), fh=42)]})
        data, _ = tracker.fetch_usage()
        self.assertEqual(data["five_hour"]["utilization"], 42)
        self.assertEqual(data["seven_day"]["utilization"], 55)

    def test_merge_window_missing_from_desktop_dropped_if_statusline_stale(self):
        # A stale statusline window must not show up under the desktop's
        # perfectly fresh "Updated" line.
        now = datetime.now(timezone.utc).timestamp()
        self._write({
            "captured_at": int(now - 3600),  # stale (> _STALE_AFTER_SECS)
            "seven_day": {"used_percentage": 55, "resets_at": None},
        })
        self._write_desktop({"version": 2,
                             "samples": [self._sample(int((now - 60) * 1000), fh=42)]})
        data, _ = tracker.fetch_usage()
        self.assertEqual(data["five_hour"]["utilization"], 42)
        self.assertNotIn("seven_day", data)

    def test_desktop_sample_rejects_json_booleans(self):
        # bool is a subtype of int: true/false must not pass for numbers
        # (contract "any anomaly → reject").
        self.assertIsNone(tracker._desktop_sample_to_data({"t": True, "u": {"fh": 5}}))
        self.assertIsNone(tracker._desktop_sample_to_data({"t": 1000, "u": {"fh": True}}))
        partial = tracker._desktop_sample_to_data({"t": 1000, "u": {"fh": True, "sd": 7}})
        self.assertNotIn("five_hour", partial)
        self.assertEqual(partial["seven_day"]["utilization"], 7)

    def test_merge_fresher_partial_statusline_keeps_desktop_window(self):
        # Incident 2026-09-01: a capture carrying only the weekly window wiped
        # the desktop 5h reading, so the title showed "—" while quota burned.
        now = datetime.now(timezone.utc).timestamp()
        self._write({
            "captured_at": int(now - 60),
            "seven_day": {"used_percentage": 0, "resets_at": None},
        })
        self._write_desktop({"version": 2,
                             "samples": [self._sample(int((now - 300) * 1000), fh=100, sd=12)]})
        data, _ = tracker.fetch_usage()
        self.assertEqual(data["five_hour"]["utilization"], 100)
        self.assertEqual(data["seven_day"]["utilization"], 0)
        # The 5h window came from the desktop and the reading is dated from
        # that sample, so the freshness line must name the desktop too.
        self.assertEqual(data["_meta"]["source"], "desktop")
        self.assertAlmostEqual(data["_meta"]["captured_at"], now - 300, delta=1)

    def test_a_weekly_only_capture_older_than_the_desktop_lets_the_desktop_win(self):
        # Routing check, not a fix: once the reset-drop capture keeps the
        # measurement's time it is older than the desktop sample, so C6 and C7
        # go through the desktop-newer branch instead of the fill.
        now = datetime.now(timezone.utc).timestamp()
        self._write({
            "captured_at": int(now - 3600),
            "seven_day": {"used_percentage": 9, "resets_at": None},
        })
        self._write_desktop({"version": 2,
                             "samples": [self._sample(int((now - 300) * 1000), fh=12, sd=18)]})
        data, _ = tracker.fetch_usage()
        self.assertEqual(data["five_hour"]["utilization"], 12)
        self.assertEqual(data["seven_day"]["utilization"], 18)
        self.assertEqual(data["_meta"]["source"], "desktop")

    def test_merge_fresher_partial_statusline_ignores_stale_desktop(self):
        # Symmetric guard: an old desktop sample must not be shown under a
        # fresh "Updated" line.
        now = datetime.now(timezone.utc).timestamp()
        self._write({
            "captured_at": int(now - 60),
            "seven_day": {"used_percentage": 4, "resets_at": None},
        })
        self._write_desktop({"version": 2,
                             "samples": [self._sample(int((now - 7200) * 1000), fh=100)]})
        data, _ = tracker.fetch_usage()
        self.assertNotIn("five_hour", data)
        self.assertEqual(data["seven_day"]["utilization"], 4)

    def test_freshness_label_names_desktop_source(self):
        now = datetime.now(timezone.utc)
        self.assertIn("Claude app", tracker.App._freshness_label(now.timestamp(), now, "desktop"))
        self.assertIn("Claude Code", tracker.App._freshness_label(now.timestamp(), now, "statusline"))

    def test_missing_captured_at_treated_as_maximally_stale(self):
        # No captured_at at all in the statusline file: _captured_at falls
        # back to 0.0, so a fresh desktop sample must win the merge outright.
        now = datetime.now(timezone.utc).timestamp()
        self._write({"five_hour": {"used_percentage": 10, "resets_at": None}})
        self._write_desktop({"version": 2,
                             "samples": [self._sample(int(now * 1000), fh=77, sd=33)]})
        data, err = tracker.fetch_usage()
        self.assertIsNone(err)
        self.assertEqual(data["five_hour"]["utilization"], 77)
        self.assertEqual(data["_meta"]["source"], "desktop")

    def test_non_numeric_captured_at_treated_as_maximally_stale(self):
        # A garbled captured_at must not crash the merge — same fallback as
        # a missing one (float() raises, _captured_at catches it → 0.0).
        now = datetime.now(timezone.utc).timestamp()
        self._write({
            "captured_at": "unknown",
            "five_hour": {"used_percentage": 10, "resets_at": None},
        })
        self._write_desktop({"version": 2,
                             "samples": [self._sample(int(now * 1000), fh=77, sd=33)]})
        data, err = tracker.fetch_usage()
        self.assertIsNone(err)
        self.assertEqual(data["five_hour"]["utilization"], 77)
        self.assertEqual(data["_meta"]["source"], "desktop")

    def test_merge_window_desktop_without_resets_at_and_no_statusline_window(self):
        # Desktop windows never carry resets_at — direct unit check of the
        # base case _merge_window falls back to when sl_win is absent.
        now = datetime.now(timezone.utc)
        desk_win = {"utilization": 55, "resets_at": None}
        win = tracker._merge_window(None, desk_win, now.timestamp(), False, now)
        self.assertEqual(win, {"utilization": 55, "resets_at": None})

    def test_merge_desktop_sampled_exactly_at_reset_boundary_defers_to_statusline(self):
        # Boundary of the desk_at <= reset check: sampled in the very same
        # instant as the reset must still be treated as "before" it (old
        # window), not "after" (which would show a bogus fresh %).
        now = datetime.now(timezone.utc).timestamp()
        reset_epoch = int(now - 120)
        self._write({
            "captured_at": int(now - 600),
            "five_hour": {"used_percentage": 80, "resets_at": reset_epoch},
        })
        self._write_desktop({"version": 2,
                             "samples": [self._sample(reset_epoch * 1000, fh=80)]})
        data, _ = tracker.fetch_usage()
        self.assertIsNotNone(data["five_hour"]["resets_at"])

    def test_merge_fresher_statusline_also_stale_still_wins_over_older_desktop(self):
        # "Fresher" is relative: a 30-min-old statusline capture is itself
        # stale (> _STALE_AFTER_SECS) but still beats a 60-min-old desktop
        # sample, which in turn is too old to backfill the missing window.
        now = datetime.now(timezone.utc).timestamp()
        self._write({
            "captured_at": int(now - 1800),
            "seven_day": {"used_percentage": 9, "resets_at": None},
        })
        self._write_desktop({"version": 2,
                             "samples": [self._sample(int((now - 3600) * 1000), fh=70, sd=50)]})
        data, _ = tracker.fetch_usage()
        self.assertEqual(data["seven_day"]["utilization"], 9)
        self.assertNotIn("five_hour", data)
        self.assertEqual(data["_meta"]["source"], "statusline")


# ---------------------------------------------------------------------------
# Tests: statusline display (2 anneaux, freshness, reset-aware)
# ---------------------------------------------------------------------------
class TestStatuslineDisplay(unittest.TestCase):
    def _make_app(self):
        with patch.object(tracker.App, "_start_timer"), \
             patch.object(tracker.App, "_refresh"):
            return tracker.App()

    def _data(self, five=30, week=40, captured_at=None, five_reset=None):
        now = datetime.now(timezone.utc)
        future = (now + timedelta(hours=2)).isoformat()
        if captured_at is None:
            captured_at = now.timestamp()
        return {
            "five_hour": {"utilization": five, "resets_at": five_reset or future},
            "seven_day": {"utilization": week, "resets_at": future},
            "_meta": {"captured_at": captured_at},
        }

    def test_two_rings_passed_to_icon(self):
        app = self._make_app()
        with patch.object(tracker, "_render_dynamic_icon") as render:
            app._update_display(self._data(five=30, week=40))
        # 2 arguments only (no more inner ring).
        self.assertEqual(render.call_args[0], (30, 40))

    def test_title_and_row_show_five_hour(self):
        app = self._make_app()
        app._update_display(self._data(five=30))
        self.assertEqual(app.title, "30%")
        self.assertIn("5-hour: 30%", app.m5h.title)

    def test_freshness_label_when_fresh(self):
        app = self._make_app()
        app._update_display(self._data())
        self.assertIn("via Claude Code", app.mupd.title)

    def test_title_weekly_off_by_default(self):
        app = self._make_app()
        app._update_display(self._data(five=43, week=25))
        self.assertNotIn("/", app.title)

    def test_title_weekly_appends_weekly_pct(self):
        app = self._make_app()
        app.title_weekly = True
        app._update_display(self._data(five=43, week=25))
        self.assertIn("43% / 25%", app.title)

    def test_title_weekly_dash_when_window_absent(self):
        app = self._make_app()
        app.title_weekly = True
        data = self._data(five=43)
        del data["seven_day"]
        app._update_display(data)
        self.assertIn("43% / —", app.title)

    def test_stale_when_capture_is_old(self):
        app = self._make_app()
        old = (datetime.now(timezone.utc) - timedelta(hours=1)).timestamp()
        app._update_display(self._data(captured_at=old))
        self.assertIn("stale", app.mupd.title)

    def test_window_reset_since_capture_blanks_pct_and_ring(self):
        app = self._make_app()
        past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        with patch.object(tracker, "_render_dynamic_icon") as render:
            app._update_display(self._data(five=90, five_reset=past))
        self.assertEqual(app.title, "—")
        self.assertIn("reset", app.m5h.title)
        self.assertIsNone(render.call_args[0][0])


# ---------------------------------------------------------------------------
# Tests: statusline error states in _apply_usage
# ---------------------------------------------------------------------------
class TestStatuslineErrorStates(unittest.TestCase):
    def _make_app(self):
        with patch.object(tracker.App, "_start_timer"), \
             patch.object(tracker.App, "_refresh"):
            return tracker.App()

    def test_nostatusline_state_guides_step_by_step(self):
        app = self._make_app()
        app._apply_usage(None, "nostatusline")
        self.assertEqual(app.title, "⚙")
        # Onboarding: zero-config path (desktop app) first, statusline second.
        self.assertIn("desktop app", app.m5h.title)
        self.assertIn("install-statusline.sh", app.m7d.title)
        self.assertIn("Claude Code", app.mupd.title)
        # A Free/Team/Enterprise user must learn why nothing will ever show up.
        self.assertIn("Pro or Max plan", app.mupd.title)

    def test_waiting_state(self):
        app = self._make_app()
        app._apply_usage(None, "waiting")
        self.assertEqual(app.title, "…")
        self.assertIn("Waiting", app.m5h.title)
        # Free accounts stay in this state forever: say why, don't show "--".
        self.assertIn("Pro or Max plan", app.m7d.title)

    def test_nostatusline_clears_stale_icon(self):
        app = self._make_app()
        app.display_mode = tracker.DISPLAY_ICON
        app._update_display(_make_usage(five_hour_pct=70))
        app._apply_usage(None, "nostatusline")
        self.assertIsNone(app.icon)


# ---------------------------------------------------------------------------
# Tests: the statusline capture script (subprocess, isolated HOME)
# ---------------------------------------------------------------------------
class TestStatuslineScript(unittest.TestCase):
    """End-to-end: run statusline/tokease-statusline.py with mock stdin and a
    throwaway HOME, then assert what it wrote to ~/.tokease/usage.json."""

    SCRIPT = Path(__file__).resolve().parent.parent / "statusline" / "tokease-statusline.py"

    def _run(self, stdin_text):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        env = {**os.environ, "HOME": td.name, "TOKEASE_STATUSLINE_QUIET": "1"}
        proc = subprocess.run(
            [sys.executable, str(self.SCRIPT)],
            input=stdin_text, capture_output=True, text=True, env=env, timeout=10,
        )
        out_file = Path(td.name) / ".tokease" / "usage.json"
        payload = json.loads(out_file.read_text(encoding="utf-8")) if out_file.exists() else None
        return proc, out_file, payload

    def test_captures_rate_limits(self):
        stdin = json.dumps({"rate_limits": {
            "five_hour": {"used_percentage": 23.5, "resets_at": 1800000000},
            "seven_day": {"used_percentage": 41, "resets_at": 1800500000},
        }})
        proc, _, payload = self._run(stdin)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(payload["five_hour"]["used_percentage"], 23.5)
        self.assertEqual(payload["seven_day"]["used_percentage"], 41)
        self.assertEqual(payload["source"], "claude-code-statusline")
        self.assertIn("captured_at", payload)

    def _run_in(self, home, stdin_text):
        """Same as _run but against a HOME that persists across calls."""
        env = {**os.environ, "HOME": home, "TOKEASE_STATUSLINE_QUIET": "1"}
        proc = subprocess.run(
            [sys.executable, str(self.SCRIPT)],
            input=stdin_text, capture_output=True, text=True, env=env, timeout=10,
        )
        out_file = Path(home) / ".tokease" / "usage.json"
        payload = json.loads(out_file.read_text(encoding="utf-8")) if out_file.exists() else None
        return proc, payload

    def test_identical_windows_keep_the_first_timestamp(self):
        # A re-run with no new measurement must not make an old reading look
        # current: it would outrank a truer desktop sample and could fire one
        # threshold alert twice.
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        stdin = json.dumps({"rate_limits": {
            "five_hour": {"used_percentage": 42, "resets_at": 1800000000},
        }})
        _, first = self._run_in(td.name, stdin)
        time.sleep(1.1)
        _, second = self._run_in(td.name, stdin)
        self.assertEqual(second["captured_at"], first["captured_at"])

    def test_a_changed_percentage_restamps_the_capture(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        def payload(pct):
            return json.dumps({"rate_limits": {
                "five_hour": {"used_percentage": pct, "resets_at": 1800000000},
            }})
        _, first = self._run_in(td.name, payload(42))
        time.sleep(1.1)
        _, second = self._run_in(td.name, payload(43))
        self.assertGreater(second["captured_at"], first["captured_at"])

    def test_a_capture_that_lost_a_window_keeps_the_timestamp(self):
        # Claude Code drops a window once its resets_at passes and re-runs the
        # script with the other window unchanged. That is not a new
        # measurement of the window that remains.
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        both = json.dumps({"rate_limits": {
            "five_hour": {"used_percentage": 42, "resets_at": 1800000000},
            "seven_day": {"used_percentage": 8, "resets_at": 1800500000},
        }})
        weekly_only = json.dumps({"rate_limits": {
            "seven_day": {"used_percentage": 8, "resets_at": 1800500000},
        }})
        _, first = self._run_in(td.name, both)
        time.sleep(1.1)
        _, second = self._run_in(td.name, weekly_only)
        self.assertEqual(second["captured_at"], first["captured_at"])
        self.assertNotIn("five_hour", second)
        self.assertEqual(second["seven_day"], first["seven_day"])

    def test_a_window_that_reappears_restamps_the_capture(self):
        # Guard, green before and after: a window that appears is a new
        # measurement, whatever the other window did.
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        weekly_only = json.dumps({"rate_limits": {
            "seven_day": {"used_percentage": 8, "resets_at": 1800500000},
        }})
        both = json.dumps({"rate_limits": {
            "five_hour": {"used_percentage": 12, "resets_at": 1800000000},
            "seven_day": {"used_percentage": 8, "resets_at": 1800500000},
        }})
        _, first = self._run_in(td.name, weekly_only)
        time.sleep(1.1)
        _, second = self._run_in(td.name, both)
        self.assertGreater(second["captured_at"], first["captured_at"])

    def test_a_changed_weekly_in_a_partial_capture_restamps(self):
        # Guard: keeping the timestamp must need every window present to be
        # equal, not just one of them.
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        both = json.dumps({"rate_limits": {
            "five_hour": {"used_percentage": 42, "resets_at": 1800000000},
            "seven_day": {"used_percentage": 8, "resets_at": 1800500000},
        }})
        moved = json.dumps({"rate_limits": {
            "seven_day": {"used_percentage": 9, "resets_at": 1800500000},
        }})
        _, first = self._run_in(td.name, both)
        time.sleep(1.1)
        _, second = self._run_in(td.name, moved)
        self.assertGreater(second["captured_at"], first["captured_at"])

    def test_a_windowless_re_run_restamps_a_windowless_file(self):
        # Deliberate side effect of the rule: with no window present there is
        # no measurement to repeat. Harmless, the app reads such a file as
        # "waiting" and never reaches its timestamp.
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        stdin = json.dumps({"model": {"id": "x"}})
        _, first = self._run_in(td.name, stdin)
        time.sleep(1.1)
        _, second = self._run_in(td.name, stdin)
        self.assertGreater(second["captured_at"], first["captured_at"])

    def test_a_non_dict_usage_file_does_not_block_the_capture(self):
        # Valid JSON that is not an object used to raise AttributeError on the
        # timestamp comparison, so the file was never rewritten again and the
        # capture stayed dead while statusline.err grew on every render.
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        out = Path(td.name) / ".tokease" / "usage.json"
        out.parent.mkdir(parents=True)
        out.write_text("[1, 2]", encoding="utf-8")
        _, payload = self._run_in(td.name, json.dumps({"rate_limits": {
            "five_hour": {"used_percentage": 42, "resets_at": 1800000000},
        }}))
        self.assertIn("five_hour", payload)
        err = Path(td.name) / ".tokease" / "statusline.err"
        self.assertNotIn("AttributeError", err.read_text(encoding="utf-8") if err.exists() else "")

    def test_no_rate_limits_writes_windowless_file_when_none_existed(self):
        # First capture of a session: nothing to preserve, so a windowless
        # file is written (the app then shows "waiting", which is accurate).
        proc, _, payload = self._run(json.dumps({"model": {"id": "x"}}))
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("five_hour", payload)
        self.assertIn("captured_at", payload)

    def test_no_rate_limits_preserves_previously_captured_windows(self):
        # Claude Code renders the statusline before it has rate_limits (session
        # start, /clear, resume). That must NOT wipe good windows: the app would
        # drop to "Waiting" mid-session for CLI-only users.
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        good = Path(td.name) / ".tokease" / "usage.json"
        good.parent.mkdir(parents=True)
        good.write_text(json.dumps({
            "schema": 1, "captured_at": 1800000000,
            "five_hour": {"used_percentage": 42, "resets_at": 1800001000},
            "seven_day": {"used_percentage": 8, "resets_at": 1800500000},
        }), encoding="utf-8")
        env = {**os.environ, "HOME": td.name, "TOKEASE_STATUSLINE_QUIET": "1"}
        proc = subprocess.run(
            [sys.executable, str(self.SCRIPT)], input=json.dumps({"model": {"id": "x"}}),
            capture_output=True, text=True, env=env, timeout=10,
        )
        self.assertEqual(proc.returncode, 0)
        kept = json.loads(good.read_text(encoding="utf-8"))
        self.assertEqual(kept["five_hour"]["used_percentage"], 42)
        self.assertEqual(kept["seven_day"]["used_percentage"], 8)
        self.assertEqual(kept["captured_at"], 1800000000)  # untouched, so staleness stays honest

    def test_invalid_json_does_not_write_file(self):
        proc, out_file, _ = self._run("not json {{{")
        self.assertEqual(proc.returncode, 0)  # must never crash the statusline
        self.assertFalse(out_file.exists())

    def test_partial_window_only(self):
        stdin = json.dumps({"rate_limits": {"five_hour": {"used_percentage": 10, "resets_at": 1}}})
        _, _, payload = self._run(stdin)
        self.assertIn("five_hour", payload)
        self.assertNotIn("seven_day", payload)

    def test_empty_stdin_is_safe(self):
        proc, _, payload = self._run("")
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("five_hour", payload)
        self.assertIn("captured_at", payload)

    def test_garbage_stdin_preserves_existing_good_file(self):
        # Core guarantee: a corrupted tick must NOT overwrite a good usage.json.
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        good = Path(td.name) / ".tokease" / "usage.json"
        good.parent.mkdir(parents=True)
        good.write_text('{"five_hour": {"used_percentage": 42}}', encoding="utf-8")
        env = {**os.environ, "HOME": td.name, "TOKEASE_STATUSLINE_QUIET": "1"}
        proc = subprocess.run(
            [sys.executable, str(self.SCRIPT)], input="not json {{{",
            capture_output=True, text=True, env=env, timeout=10,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(json.loads(good.read_text())["five_hour"]["used_percentage"], 42)


# ---------------------------------------------------------------------------
# Tests: statusline line rendering (pure helper, no subprocess)
# ---------------------------------------------------------------------------
class TestStatuslineRenderLine(unittest.TestCase):
    """_render_line formats the captured windows; it must never raise, whatever
    the payload holds — it runs inside Claude Code's statusline."""

    @staticmethod
    def _render(payload):
        import importlib.util
        path = Path(__file__).resolve().parent.parent / "statusline" / "tokease-statusline.py"
        spec = importlib.util.spec_from_file_location("tokease_statusline", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod._render_line(payload)

    def test_both_windows(self):
        line = self._render({
            "five_hour": {"used_percentage": 42.7},
            "seven_day": {"used_percentage": 7},
        })
        self.assertEqual(line, "⛁ 5h 42% · 7d 7%")

    def test_single_window(self):
        self.assertEqual(self._render({"five_hour": {"used_percentage": 10}}), "⛁ 5h 10%")

    def test_no_window_renders_nothing(self):
        self.assertEqual(self._render({"captured_at": 1}), "")

    def test_non_numeric_percentage_is_skipped_not_fatal(self):
        line = self._render({
            "five_hour": {"used_percentage": "boom"},
            "seven_day": {"used_percentage": 5},
        })
        self.assertEqual(line, "⛁ 7d 5%")

    def test_missing_percentage_key_is_skipped(self):
        self.assertEqual(self._render({"five_hour": {"resets_at": 1}}), "")


# ---------------------------------------------------------------------------
# Tests: real icon rendering (Pillow) — otherwise this prod code never runs
# ---------------------------------------------------------------------------
@unittest.skipUnless(tracker._PILLOW_AVAILABLE, "Pillow required")
class TestRenderIcon(unittest.TestCase):
    def test_renders_real_png_at_final_size(self):
        p = tracker._render_dynamic_icon(50, 30)
        self.assertIsNotNone(p)
        self.assertTrue(Path(p).exists())
        with tracker.Image.open(p) as im:
            size = im.size
        self.assertEqual(size, (tracker._ICON_SIZE_FINAL, tracker._ICON_SIZE_FINAL))

    def test_renders_with_none_pcts(self):
        # absent/reset window (pct None) → BOTH tracks stay visible (empty rings)
        p = tracker._render_dynamic_icon(None, None)
        self.assertTrue(Path(p).exists())
        center = tracker._ICON_SIZE_FINAL // 2
        with tracker.Image.open(p) as im:
            for radius in tracker._RING_RADII:
                alpha = im.getpixel((center, center - radius))[3]
                self.assertGreater(alpha, 0, f"missing track at radius {radius}")

    def test_renders_clamps_over_100(self):
        p = tracker._render_dynamic_icon(150, 999)
        self.assertTrue(Path(p).exists())


# ---------------------------------------------------------------------------
# Tests: freshness label with a malformed captured_at
# ---------------------------------------------------------------------------
class TestFreshnessLabel(unittest.TestCase):
    def test_malformed_captured_at_says_unknown(self):
        # There is a reading on screen, so "Updated: --" claimed there was
        # nothing to say about its age. The line now says the time is unknown.
        now = datetime.now(timezone.utc)
        self.assertEqual(tracker.App._freshness_label("garbage", now), tracker.UPDATED_UNKNOWN)
        self.assertEqual(tracker.App._freshness_label(None, now), tracker.UPDATED_UNKNOWN)


# ---------------------------------------------------------------------------
# Tests: staleness surfaced in the menu bar title (spec honest-freshness)
# ---------------------------------------------------------------------------
class TestStaleTitleMarker(unittest.TestCase):
    def _make_app(self):
        with patch.object(tracker.App, "_start_timer"), \
             patch.object(tracker.App, "_refresh"):
            return tracker.App()

    def test_fresh_title_has_no_marker(self):
        app = self._make_app()
        app._update_display(_make_usage(five_hour_pct=42))
        self.assertEqual(app.title, "42%")

    def test_stale_title_is_marked(self):
        app = self._make_app()
        stale = datetime.now(timezone.utc).timestamp() - 3600
        app._update_display(_make_usage(five_hour_pct=26, captured_at=stale))
        self.assertEqual(app.title, "~26%")

    def test_stale_marker_prefixes_the_weekly_variant_once(self):
        app = self._make_app()
        app.title_weekly = True
        stale = datetime.now(timezone.utc).timestamp() - 3600
        app._update_display(_make_usage(five_hour_pct=26, seven_day_pct=4, captured_at=stale))
        self.assertEqual(app.title, "~26% / 4%")

    def test_no_marker_when_no_window_at_all(self):
        app = self._make_app()
        app._update_display({"_meta": {"captured_at": 1}})
        self.assertEqual(app.title, "—")

    def test_threshold_tolerates_the_desktop_15min_cadence(self):
        # Desktop samples every 5 to 15 min: a 17 min old reading is still
        # normal operation, not a dead client.
        now = datetime.now(timezone.utc)
        label = tracker.App._freshness_label((now.timestamp() - 17 * 60), now, "desktop")
        self.assertTrue(label.startswith("Updated"), label)

    def test_threshold_still_flags_a_missed_sample(self):
        now = datetime.now(timezone.utc)
        label = tracker.App._freshness_label((now.timestamp() - 25 * 60), now, "desktop")
        self.assertIn("stale", label)

    def test_freshness_label_exact_threshold_boundary(self):
        # age > _STALE_AFTER_SECS is the actual condition: exactly at the
        # threshold must still read as fresh, one second past must not.
        now = datetime.now(timezone.utc)
        at_threshold = tracker.App._freshness_label(
            now.timestamp() - tracker._STALE_AFTER_SECS, now, "desktop"
        )
        self.assertTrue(at_threshold.startswith("Updated"), at_threshold)
        past_threshold = tracker.App._freshness_label(
            now.timestamp() - tracker._STALE_AFTER_SECS - 1, now, "desktop"
        )
        self.assertIn("stale", past_threshold)

    def test_stale_marker_in_pct_only_mode(self):
        app = self._make_app()
        app.display_mode = tracker.DISPLAY_PCT
        stale = datetime.now(timezone.utc).timestamp() - 3600
        app._update_display(_make_usage(five_hour_pct=26, captured_at=stale))
        self.assertEqual(app.title, "~26%")

    def test_stale_marker_absent_from_icon_only_title(self):
        # Decided: leave as is. Icon mode blanks the title, so the tilde is
        # computed but not rendered. The dropdown still carries the stale
        # line in every display mode, so the signal stays one click away,
        # like the number the user chose to hide. The icon is a macOS
        # template image, so it has no tint to spare, and a dimmed ring
        # reads as lower usage rather than as older data.
        app = self._make_app()
        app.display_mode = tracker.DISPLAY_ICON
        stale = datetime.now(timezone.utc).timestamp() - 3600
        app._update_display(_make_usage(five_hour_pct=26, captured_at=stale))
        self.assertEqual(app.title, "")

    def test_stale_marker_applies_even_when_five_hour_absent(self):
        app = self._make_app()
        app.title_weekly = True
        stale = datetime.now(timezone.utc).timestamp() - 3600
        data = _make_usage(seven_day_pct=12, captured_at=stale)
        del data["five_hour"]
        app._update_display(data)
        self.assertEqual(app.title, "~— / 12%")

    def test_no_marker_when_no_window_at_all_weekly_variant(self):
        app = self._make_app()
        app.title_weekly = True
        app._update_display({"_meta": {"captured_at": 1}})
        self.assertEqual(app.title, "— / —")

    def test_notification_fires_even_when_data_is_stale(self):
        # Decided: leave as is. _maybe_notify only fires on an upward crossing
        # between two refreshes, so a frozen reading never notifies at all. A
        # late reading that does cross is still true, since usage only grows
        # within a window, and gating it would drop the one alert the user
        # gets when the desktop feed is the only source (see ADR 0003).
        app = self._make_app()
        app.alerts_enabled = True
        app._last_pct = 50
        stale = datetime.now(timezone.utc).timestamp() - 3600
        calls = []
        with patch.object(tracker.rumps, "notification",
                          side_effect=lambda **k: calls.append(k)):
            app._update_display(_make_usage(five_hour_pct=85, captured_at=stale))
        self.assertEqual(len(calls), 1)
        self.assertEqual(app.title, "~85%")

    def test_notification_survives_a_window_reset(self):
        # A reset refresh reports no percentage, so _maybe_notify is skipped
        # and _last_pct would keep the pre-reset value. The next reading opens
        # a new cycle, and anything below that stale anchor would not look
        # like a crossing, silently dropping the new window's alert.
        app = self._make_app()
        app.alerts_enabled = True
        app._last_pct = 98
        calls = []
        with patch.object(tracker.rumps, "notification",
                          side_effect=lambda **k: calls.append(k)):
            past = (datetime.now(timezone.utc) - timedelta(minutes=1)).strftime(
                "%Y-%m-%dT%H:%M:%SZ")
            app._update_display(_make_usage(five_hour_resets=past))
            self.assertEqual(app._last_pct, 0)
            app._update_display(_make_usage(five_hour_pct=85))
        self.assertEqual(len(calls), 1, "new window crossing 80% must still alert")


class TestStrategyGaps(unittest.TestCase):
    """Scenarios from docs/specs/display-strategy.md."""

    def _make_app(self):
        return TestStaleTitleMarker._make_app(self)

    def test_reading_older_than_the_five_hour_window_is_void(self):
        # A 5h window cannot still hold a reading taken six hours ago.
        app = self._make_app()
        app.display_mode = tracker.DISPLAY_PCT
        old = datetime.now(timezone.utc).timestamp() - 6 * 3600
        app._update_display(_make_usage(five_hour_pct=42, captured_at=old))
        self.assertEqual(app.title, "—")
        self.assertIn("older than the window", app.m5h.title)

    def test_reading_inside_the_five_hour_window_still_counts(self):
        app = self._make_app()
        app.display_mode = tracker.DISPLAY_PCT
        recent = datetime.now(timezone.utc).timestamp() - 3 * 3600
        app._update_display(_make_usage(five_hour_pct=42, captured_at=recent))
        self.assertEqual(app.title, "~42%")

    def test_weekly_survives_an_age_that_voids_the_five_hour(self):
        # The two windows have their own spans, so one voids well before the
        # other on the very same reading.
        app = self._make_app()
        app.display_mode = tracker.DISPLAY_PCT
        app.title_weekly = True
        old = datetime.now(timezone.utc).timestamp() - 6 * 3600
        app._update_display(_make_usage(five_hour_pct=42, seven_day_pct=18,
                                        captured_at=old))
        self.assertEqual(app.title, "~— / 18%")

    def test_reading_older_than_the_weekly_window_is_void(self):
        app = self._make_app()
        app.display_mode = tracker.DISPLAY_PCT
        app.title_weekly = True
        old = datetime.now(timezone.utc).timestamp() - 8 * 24 * 3600
        app._update_display(_make_usage(captured_at=old))
        # Nothing numeric is left on screen, so there is nothing to mark stale.
        self.assertEqual(app.title, "— / —")

    def test_a_new_window_alerts_even_below_the_previous_peak(self):
        # The old window ended at 98 %. The new one opens at 85 %, under that
        # peak, and must still raise its own 80 % alert.
        app = self._make_app()
        app.alerts_enabled = True
        app._last_pct = 50  # a first observation never alerts, by design
        calls = []
        with patch.object(tracker.rumps, "notification",
                          side_effect=lambda **k: calls.append(k)):
            app._update_display(_make_usage(
                five_hour_pct=98, five_hour_resets="2099-03-06T18:00:00Z"))
            app._update_display(_make_usage(
                five_hour_pct=85, five_hour_resets="2099-03-06T23:00:00Z"))
        self.assertEqual(len(calls), 2)
        self.assertIn("85%", calls[1]["subtitle"])

    def test_same_window_does_not_realert_on_a_dip(self):
        # Guard against the naive "any drop is a new window" rule: source
        # noise inside one window must stay silent.
        app = self._make_app()
        app.alerts_enabled = True
        app._last_pct = 50
        calls = []
        with patch.object(tracker.rumps, "notification",
                          side_effect=lambda **k: calls.append(k)):
            for pct in (85, 90, 88):
                app._update_display(_make_usage(five_hour_pct=pct))
        self.assertEqual(len(calls), 1)

    def test_no_second_alert_when_the_new_window_reset_finally_arrives(self):
        # Desktop readings carry no reset time, so after a reset the app still
        # names the old window while tracking the new one. It alerts, correctly.
        # The reset time that arrives later with the next capture must not make
        # that same window look brand new and raise the alert a second time.
        app = self._make_app()
        app.alerts_enabled = True
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        later = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
        calls = []
        with patch.object(tracker.rumps, "notification",
                          side_effect=lambda **k: calls.append(k)):
            app._maybe_notify(60, past)    # old window, ended but still on file
            app._maybe_notify(85, None)    # desktop tracks the new one, alert
            app._maybe_notify(85, later)   # capture brings the new reset time
        self.assertEqual(len(calls), 1)

    def test_a_jittery_reset_time_does_not_realert(self):
        # Only a later reset time means a new window. One that moves by a
        # second is the same window still running.
        app = self._make_app()
        app.alerts_enabled = True
        base = datetime.now(timezone.utc) + timedelta(hours=4)
        calls = []
        with patch.object(tracker.rumps, "notification",
                          side_effect=lambda **k: calls.append(k)):
            app._maybe_notify(50, base.isoformat())
            app._maybe_notify(85, base.isoformat())
            app._maybe_notify(85, (base - timedelta(seconds=1)).isoformat())
        self.assertEqual(len(calls), 1)

    def test_no_stale_marker_on_a_title_showing_no_number(self):
        # The 5h window is void by age and the weekly one is not on the title,
        # so the title is just a dash. Marking a dash as stale says nothing.
        app = self._make_app()
        app.display_mode = tracker.DISPLAY_PCT
        old = datetime.now(timezone.utc).timestamp() - 6 * 3600
        app._update_display(_make_usage(captured_at=old))
        self.assertEqual(app.title, "—")

    def test_a_long_stale_age_reads_in_hours_or_days(self):
        now = datetime.now(timezone.utc)
        row = tracker.App._freshness_label((now - timedelta(days=3)).timestamp(),
                                           now, "desktop")
        self.assertIn("stale 3d", row)
        row = tracker.App._freshness_label((now - timedelta(hours=4)).timestamp(),
                                           now, "desktop")
        self.assertIn("stale 4h", row)

    def test_a_filled_window_dates_the_display_from_the_desktop(self):
        # The capture is fresher but carries only the weekly window. The 5h
        # window comes from an older desktop sample, so the whole display must
        # date itself from that sample rather than from the capture.
        now = datetime.now(timezone.utc).timestamp()
        statusline = {"seven_day": {"utilization": 18},
                      "_meta": {"captured_at": now - 10}}
        desktop = {"five_hour": {"utilization": 42},
                   "_meta": {"captured_at": now - 600}}
        merged = tracker._merge_usage(statusline, desktop)
        self.assertEqual(merged["five_hour"]["utilization"], 42)
        self.assertAlmostEqual(merged["_meta"]["captured_at"], now - 600, delta=1)

    def test_an_unfilled_capture_keeps_its_own_timestamp(self):
        now = datetime.now(timezone.utc).timestamp()
        statusline = {"five_hour": {"utilization": 42},
                      "seven_day": {"utilization": 18},
                      "_meta": {"captured_at": now - 10}}
        desktop = {"five_hour": {"utilization": 99},
                   "_meta": {"captured_at": now - 600}}
        merged = tracker._merge_usage(statusline, desktop)
        self.assertAlmostEqual(merged["_meta"]["captured_at"], now - 10, delta=1)

    def test_a_reading_with_no_capture_time_is_marked_stale(self):
        # R1 has no exception: an age nobody can compute is not a fresh one.
        app = self._make_app()
        app.display_mode = tracker.DISPLAY_PCT
        data = _make_usage(five_hour_pct=42)
        data["_meta"] = {}
        app._update_display(data)
        self.assertEqual(app.title, "~42%")
        self.assertIn("unknown", app.mupd.title)

    def test_a_garbled_capture_time_is_marked_stale(self):
        app = self._make_app()
        app.display_mode = tracker.DISPLAY_PCT
        app._update_display(_make_usage(five_hour_pct=42, captured_at="unknown"))
        self.assertEqual(app.title, "~42%")
        self.assertIn("unknown", app.mupd.title)

    def test_an_unknown_age_does_not_void_the_window(self):
        # Guard: the age ceiling states that a window has ended. An unknown
        # age states nothing, so the reading is marked, not voided.
        app = self._make_app()
        app.display_mode = tracker.DISPLAY_PCT
        data = _make_usage(five_hour_pct=42)
        data["_meta"] = {}
        with patch.object(tracker, "_render_dynamic_icon") as render:
            app._update_display(data)
        self.assertIn("5-hour: 42%", app.m5h.title)
        self.assertEqual(render.call_args[0][0], 42)


class TokenFreeInvariantTest(unittest.TestCase):
    """The product's public promise, enforced instead of documented.

    README, AGENTS.md and ADR 0002 state that Tokease never reads an
    authentication token and never opens a network connection. Nothing
    checked it, so the claim held only as long as everyone remembered it.

    This is a regression tripwire, not a proof: it stops the v0.9 endpoint
    code (or an equivalent) from being pasted back in. A contributor
    determined to reach the network could still do it through PyObjC or a
    shell command, which is why the reviewable-in-a-minute file size stays
    the real argument.

    The checks read the AST, not the raw text, so a comment or docstring
    that merely *mentions* the Keychain never trips them.
    """

    FORBIDDEN_IMPORTS = frozenset({
        "urllib", "requests", "httpx", "http", "socket", "aiohttp",
        "ftplib", "smtplib", "telnetlib", "xmlrpc", "asyncio", "ssl",
        "keyring", "secretstorage",
        # PyObjC bridge to the Keychain. objc/Quartz/CoreGraphics stay
        # allowed: the roadmap plans to draw the icon with them.
        "Security",
    })
    # Reading a credential back, whether through the CLI or the Security
    # framework that PyObjC puts within reach.
    FORBIDDEN_STRINGS = ("find-generic-password", "SecItemCopyMatching",
                         "NSURLSession", "Claude Code-credentials")

    @staticmethod
    def _shipped():
        root = Path(__file__).resolve().parent.parent
        return {
            "tracker.py",
            "statusline/tokease-statusline.py",
            "assets/build-logos.py",
            "assets/build-menubar-icon.py",
        }, root

    def _trees(self):
        names, root = self._shipped()
        for name in sorted(names):
            path = root / name
            self.assertTrue(path.is_file(), f"{name} is missing")
            source = path.read_text()
            yield name, source, ast.parse(source)

    def test_the_guard_covers_every_shipped_python_file(self):
        # A closed list silently stops guarding the day code moves into a
        # new module, so the list itself is checked against the repo.
        names, root = self._shipped()
        tracked = subprocess.run(
            ["git", "ls-files", "*.py"], cwd=root,
            capture_output=True, text=True, check=True,
        ).stdout.split()
        shipped = {
            f for f in tracked
            if not f.startswith(("tests/", "build/")) and f != "setup.py"
        }
        self.assertEqual(
            shipped, names,
            "a shipped .py file is not covered by the token-free guard; "
            "add it to _shipped().",
        )

    def test_no_shipped_file_imports_a_network_client(self):
        for name, _source, tree in self._trees():
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    roots = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    roots = [(node.module or "").split(".")[0]]
                else:
                    continue
                for root_name in roots:
                    self.assertNotIn(
                        root_name, self.FORBIDDEN_IMPORTS,
                        f"{name} imports {root_name!r}: Tokease must not be "
                        f"able to reach the network (ADR 0002).",
                    )

    def test_no_shipped_file_names_a_credential_api(self):
        for name, _source, tree in self._trees():
            docstrings = {
                id(n.body[0].value)
                for n in ast.walk(tree)
                if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                  ast.AsyncFunctionDef))
                and n.body and isinstance(n.body[0], ast.Expr)
                and isinstance(n.body[0].value, ast.Constant)
                and isinstance(n.body[0].value.value, str)
            }
            literals = [
                n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and id(n) not in docstrings
            ]
            attributes = [
                n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
            ]
            for needle in self.FORBIDDEN_STRINGS:
                for text in literals:
                    self.assertNotIn(
                        needle, text,
                        f"{name} contains {needle!r}: Tokease must never read "
                        f"a credential (ADR 0002).",
                    )
                self.assertNotIn(needle, attributes, f"{name} calls {needle}.")

    def test_the_only_binary_tracker_spawns_is_osascript(self):
        # Scope: the binaries tracker.py itself passes to subprocess. It does
        # not cover webbrowser.open(), which reaches /usr/bin/osascript inside
        # the standard library -- the same binary, but not visible from here.
        _names, root = self._shipped()
        tree = ast.parse((root / "tracker.py").read_text())
        spawned = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr in {"run", "Popen", "call"}):
                continue
            if not node.args or not isinstance(node.args[0], ast.List):
                continue
            head = node.args[0].elts[0] if node.args[0].elts else None
            if isinstance(head, ast.Constant) and isinstance(head.value, str):
                spawned.add(head.value)
        self.assertEqual(
            spawned, {"/usr/bin/osascript"},
            "tracker.py spawns a binary other than osascript.",
        )
        # Catches the same thing through an aliased or renamed call.
        paths = {
            n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and n.value.startswith(("/usr/bin/", "/usr/sbin/", "/bin/"))
        }
        self.assertEqual(
            paths, {"/usr/bin/osascript"},
            "tracker.py names a system binary other than osascript.",
        )


if __name__ == "__main__":
    unittest.main()
