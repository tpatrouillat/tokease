#!/usr/bin/env python3
"""
Tests for Tokease.

Mocks rumps to run without the macOS GUI. Two local data sources: the Claude
Code statusline feed and the Claude desktop app quota history (ADR 0003).
Covers: helpers, time formatting, both source readers (error paths + success),
the freshness merge, display logic (2 rings), empty states, and interval
management.
"""

import json
import os
import subprocess
import sys
import tempfile
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
        data = {"five_hour": {"utilization": -50, "resets_at": None}}
        app._update_display(data)
        self.assertEqual(app.title, "0%")
        self.assertIn("0%", app.m5h.title)

    def test_string_utilization(self):
        app = self._make_app()
        data = {"five_hour": {"utilization": "85", "resets_at": None}}
        app._update_display(data)
        self.assertEqual(app.title, "85%")

    def test_null_utilization(self):
        app = self._make_app()
        data = {"five_hour": {"utilization": None, "resets_at": None}}
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

    def test_last_valid_sample_wins_skipping_malformed(self):
        self._write_desktop({"version": 2, "samples": [
            self._sample(1000_000, fh=10),
            self._sample(2000_000, fh=20),
            {"t": "corrompu", "u": {"fh": 99}},
            {"pas": "un sample"},
        ]})
        data, _ = tracker.fetch_usage()
        self.assertEqual(data["five_hour"]["utilization"], 20)

    def test_unknown_version_is_ignored(self):
        self._write_desktop({"version": 3, "samples": [self._sample(1, fh=50)]})
        data, err = tracker.fetch_usage()
        self.assertIsNone(data)
        self.assertEqual(err, "nostatusline")  # behavior unchanged without desktop

    def test_invalid_desktop_file_is_ignored(self):
        self._desktop.write_text("pas du json{{{", encoding="utf-8")
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

    def test_freshness_label_names_desktop_source(self):
        now = datetime.now(timezone.utc)
        self.assertIn("Claude app", tracker.App._freshness_label(now.timestamp(), now, "desktop"))
        self.assertIn("Claude Code", tracker.App._freshness_label(now.timestamp(), now, "statusline"))


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

    def test_no_rate_limits_writes_windowless_file(self):
        proc, _, payload = self._run(json.dumps({"model": {"id": "x"}}))
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("five_hour", payload)
        self.assertIn("captured_at", payload)

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
    def test_malformed_captured_at_returns_default(self):
        now = datetime.now(timezone.utc)
        self.assertEqual(tracker.App._freshness_label("garbage", now), tracker.UPDATED_DEFAULT)
        self.assertEqual(tracker.App._freshness_label(None, now), tracker.UPDATED_DEFAULT)


if __name__ == "__main__":
    unittest.main()
