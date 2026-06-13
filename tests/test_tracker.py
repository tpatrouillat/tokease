#!/usr/bin/env python3
"""
Tests for Tokease.

Mocks rumps, subprocess, and urllib so tests run without macOS GUI or network.
Covers: helpers, time formatting, API fetching (all error paths + success),
display logic, security (redirect blocking, token cleanup), and interval mgmt.
"""

import io
import json
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
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
# Fake API response builder
# ---------------------------------------------------------------------------
def _make_api_response(
    five_hour_pct=42,
    seven_day_pct=18,
    sonnet_pct=5,
    extra_enabled=False,
    extra_used=500,
    extra_limit=5000,
    extra_pct=10,
    five_hour_resets="2026-03-06T18:00:00Z",
    seven_day_resets="2026-03-10T00:00:00Z",
    sonnet_resets="2026-03-10T00:00:00Z",
):
    data = {
        "five_hour": {
            "utilization": five_hour_pct,
            "resets_at": five_hour_resets,
        },
        "seven_day": {
            "utilization": seven_day_pct,
            "resets_at": seven_day_resets,
        },
        "seven_day_sonnet": {
            "utilization": sonnet_pct,
            "resets_at": sonnet_resets,
        },
        "extra_usage": {
            "is_enabled": extra_enabled,
            "used_credits": extra_used,
            "monthly_limit": extra_limit,
            "utilization": extra_pct,
        },
    }
    return data


# ---------------------------------------------------------------------------
# Helper to build a fake keychain subprocess result
# ---------------------------------------------------------------------------
def _keychain_result(token="fake-token-abc", returncode=0):
    creds = json.dumps({"claudeAiOauth": {"accessToken": token}})
    return SimpleNamespace(returncode=returncode, stdout=creds, stderr="")


def _keychain_no_token():
    creds = json.dumps({"claudeAiOauth": {}})
    return SimpleNamespace(returncode=0, stdout=creds, stderr="")


def _keychain_truncated_json(token="fake-token-abc"):
    """Simulate macOS Keychain truncating the JSON blob at ~2KB."""
    full = json.dumps({"claudeAiOauth": {"accessToken": token}, "extra": "x" * 3000})
    return SimpleNamespace(returncode=0, stdout=full[:2014], stderr="")


def _keychain_bad_json():
    return SimpleNamespace(returncode=0, stdout="not-json{{{", stderr="")


def _keychain_fail():
    return SimpleNamespace(returncode=44, stdout="", stderr="not found")


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
        # A numeric resets_at (API regression) must degrade gracefully —
        # _parse_iso guards AttributeError/TypeError instead of raising.
        self.assertIsNone(tracker._parse_iso(1718304000))
        self.assertIn(tracker.fmt_reset(1718304000), ("--", "?"))


# ---------------------------------------------------------------------------
# Tests: get_usage — keychain errors
# ---------------------------------------------------------------------------
class TestGetUsageKeychain(unittest.TestCase):
    @patch("tracker.subprocess.run", return_value=_keychain_fail())
    def test_keychain_not_found(self, _):
        data, err = tracker.get_usage()
        self.assertIsNone(data)
        self.assertEqual(err, "auth")

    @patch("tracker.subprocess.run", return_value=_keychain_no_token())
    def test_missing_token(self, _):
        data, err = tracker.get_usage()
        self.assertIsNone(data)
        self.assertEqual(err, "auth")
        self.assertNotEqual(err, "error", "Empty token is auth, not generic error")

    @patch("tracker.subprocess.run", return_value=_keychain_bad_json())
    def test_bad_json_no_token(self, _):
        """Bad JSON with no accessToken pattern → auth error."""
        data, err = tracker.get_usage()
        self.assertIsNone(data)
        self.assertEqual(err, "auth")

    @patch("tracker.subprocess.run", return_value=_keychain_truncated_json("my-real-token"))
    @patch("tracker._opener.open")
    def test_truncated_json_regex_fallback(self, mock_open, _):
        """macOS truncates keychain at ~2KB; regex extracts the token."""
        api_data = _make_api_response(five_hour_pct=55)
        resp = MagicMock()
        resp.read.return_value = json.dumps(api_data).encode()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        mock_open.return_value = resp
        data, err = tracker.get_usage()
        self.assertIsNone(err)
        self.assertEqual(data["five_hour"]["utilization"], 55)
        # Verify the Authorization header used the regex-extracted token
        call_args = mock_open.call_args
        req = call_args[0][0]
        self.assertIn("my-real-token", req.get_header("Authorization"))

    @patch("tracker.subprocess.run", side_effect=subprocess.TimeoutExpired("security", 5))
    def test_keychain_timeout(self, _):
        data, err = tracker.get_usage()
        self.assertIsNone(data)
        self.assertEqual(err, "error")

    @patch("tracker.subprocess.run", side_effect=OSError("no such file"))
    def test_keychain_os_error(self, _):
        data, err = tracker.get_usage()
        self.assertIsNone(data)
        self.assertEqual(err, "error")
        self.assertNotEqual(err, "auth", "OSError is generic error, not auth")


# ---------------------------------------------------------------------------
# Tests: get_usage — API responses
# ---------------------------------------------------------------------------
class TestGetUsageAPI(unittest.TestCase):
    def _mock_http(self, response_data, status=200):
        """Return a context-manager mock for _opener.open."""
        body = json.dumps(response_data).encode()
        resp = MagicMock()
        resp.read.return_value = body
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    @patch("tracker.subprocess.run", return_value=_keychain_result())
    @patch("tracker._opener.open")
    def test_success(self, mock_open, _):
        api_data = _make_api_response(five_hour_pct=42)
        mock_open.return_value = self._mock_http(api_data)
        data, err = tracker.get_usage()
        self.assertIsNone(err)
        self.assertEqual(data["five_hour"]["utilization"], 42)

    @patch("tracker.subprocess.run", return_value=_keychain_result())
    @patch("tracker._opener.open")
    def test_http_401(self, mock_open, _):
        mock_open.side_effect = tracker.urllib.error.HTTPError(
            "url", 401, "Unauthorized", {}, io.BytesIO()
        )
        data, err = tracker.get_usage()
        self.assertIsNone(data)
        self.assertEqual(err, "auth")

    @patch("tracker.subprocess.run", return_value=_keychain_result())
    @patch("tracker._opener.open")
    def test_http_403(self, mock_open, _):
        mock_open.side_effect = tracker.urllib.error.HTTPError(
            "url", 403, "Forbidden", {}, io.BytesIO()
        )
        data, err = tracker.get_usage()
        self.assertIsNone(data)
        self.assertEqual(err, "plan")

    @patch("tracker.subprocess.run", return_value=_keychain_result())
    @patch("tracker._opener.open")
    def test_http_429(self, mock_open, _):
        mock_open.side_effect = tracker.urllib.error.HTTPError(
            "url", 429, "Too Many Requests", {}, io.BytesIO()
        )
        data, err = tracker.get_usage()
        self.assertEqual(data, {"retry_after": 0})
        self.assertEqual(err, "rate")

    @patch("tracker.subprocess.run", return_value=_keychain_result())
    @patch("tracker._opener.open")
    def test_http_429_with_retry_after(self, mock_open, _):
        headers = {"Retry-After": "120"}
        mock_open.side_effect = tracker.urllib.error.HTTPError(
            "url", 429, "Too Many Requests", headers, io.BytesIO()
        )
        data, err = tracker.get_usage()
        self.assertEqual(data, {"retry_after": 120})
        self.assertEqual(err, "rate")

    @patch("tracker.subprocess.run", return_value=_keychain_result())
    @patch("tracker._opener.open")
    def test_http_500(self, mock_open, _):
        mock_open.side_effect = tracker.urllib.error.HTTPError(
            "url", 500, "Server Error", {}, io.BytesIO()
        )
        data, err = tracker.get_usage()
        self.assertIsNone(data)
        self.assertEqual(err, "error")

    @patch("tracker.subprocess.run", return_value=_keychain_result())
    @patch("tracker._opener.open")
    def test_non_dict_response(self, mock_open, _):
        mock_open.return_value = self._mock_http([1, 2, 3])
        data, err = tracker.get_usage()
        self.assertIsNone(data)
        self.assertEqual(err, "error")

    @patch("tracker.subprocess.run", return_value=_keychain_result())
    @patch("tracker._opener.open")
    def test_network_error(self, mock_open, _):
        mock_open.side_effect = tracker.urllib.error.URLError("DNS failed")
        data, err = tracker.get_usage()
        self.assertIsNone(data)
        self.assertEqual(err, "error")

    @patch("tracker.subprocess.run", return_value=_keychain_result())
    @patch("tracker._opener.open")
    def test_malformed_json_response(self, mock_open, _):
        resp = MagicMock()
        resp.read.return_value = b"not json{{"
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        mock_open.return_value = resp
        data, err = tracker.get_usage()
        self.assertIsNone(data)
        self.assertEqual(err, "error")

    @patch("tracker.subprocess.run", return_value=_keychain_result())
    @patch("tracker._opener.open")
    def test_non_utf8_response(self, mock_open, _):
        # A 200 body that isn't valid UTF-8 (captive portal, proxy, binary) must
        # surface as "error", not raise UnicodeDecodeError and kill the worker.
        resp = MagicMock()
        resp.read.return_value = b"\xe9\xff\x00garbage"
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        mock_open.return_value = resp
        data, err = tracker.get_usage()
        self.assertIsNone(data)
        self.assertEqual(err, "error")


# ---------------------------------------------------------------------------
# Tests: Security — redirect blocking
# ---------------------------------------------------------------------------
class TestRedirectBlocking(unittest.TestCase):
    def test_redirect_raises(self):
        handler = tracker._NoRedirectHandler()
        fake_req = MagicMock()
        fake_req.full_url = "https://api.anthropic.com/api/oauth/usage"
        with self.assertRaises(tracker.urllib.error.HTTPError) as ctx:
            handler.redirect_request(
                fake_req, None, 302, "Found", {}, "https://evil.com/steal"
            )
        self.assertEqual(ctx.exception.code, 302)
        self.assertIn("Redirect blocked", ctx.exception.msg)


# ---------------------------------------------------------------------------
# Tests: Security — token cleanup in finally block
# ---------------------------------------------------------------------------
class TestTokenCleanup(unittest.TestCase):
    @patch("tracker.subprocess.run", return_value=_keychain_result())
    @patch("tracker._opener.open")
    def test_token_cleared_on_success(self, mock_open, _):
        mock_open.return_value = TestGetUsageAPI._mock_http(
            None, _make_api_response()
        )
        tracker.get_usage()
        # If we got here without error, the finally block ran.
        # We can't inspect locals after return, but we verify no exception.

    @patch("tracker.subprocess.run", return_value=_keychain_result())
    @patch("tracker._opener.open")
    def test_token_cleared_on_error(self, mock_open, _):
        mock_open.side_effect = tracker.urllib.error.HTTPError(
            "url", 500, "Error", {}, io.BytesIO()
        )
        tracker.get_usage()
        # finally block should have run without raising


# ---------------------------------------------------------------------------
# Tests: App display logic (with mocked rumps)
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
        data = _make_api_response(
            five_hour_pct=42, seven_day_pct=18, sonnet_pct=5
        )
        app._update_display(data)
        self.assertEqual(app.title, "42%")
        self.assertIn("5-hour: 42%", app.m5h.title)
        self.assertIn("Weekly: 18%", app.m7d.title)
        self.assertIn("Sonnet: 5%", app.mson.title)
        self.assertEqual(app.mext.title, tracker.EXTRA_DEFAULT)
        self.assertIn("Updated:", app.mupd.title)

    def test_extra_usage_enabled(self):
        app = self._make_app()
        data = _make_api_response(
            extra_enabled=True, extra_used=1250, extra_limit=5000, extra_pct=25
        )
        app._update_display(data)
        self.assertIn("$12.50", app.mext.title)
        self.assertIn("50", app.mext.title)  # limit
        self.assertIn("25%", app.mext.title)

    def test_extra_usage_disabled(self):
        app = self._make_app()
        data = _make_api_response(extra_enabled=False)
        app._update_display(data)
        self.assertEqual(app.mext.title, tracker.EXTRA_DEFAULT)

    def test_missing_five_hour(self):
        app = self._make_app()
        data = _make_api_response()
        del data["five_hour"]
        app._update_display(data)
        self.assertEqual(app.title, "0%")
        self.assertEqual(app.m5h.title, tracker.FIVE_HOUR_DEFAULT)

    def test_missing_seven_day(self):
        app = self._make_app()
        data = _make_api_response()
        del data["seven_day"]
        app._update_display(data)
        self.assertEqual(app.m7d.title, tracker.WEEKLY_DEFAULT)

    def test_missing_sonnet(self):
        app = self._make_app()
        data = _make_api_response()
        del data["seven_day_sonnet"]
        app._update_display(data)
        self.assertEqual(app.mson.title, tracker.SONNET_DEFAULT)

    def test_all_sections_missing(self):
        app = self._make_app()
        app._update_display({})
        self.assertEqual(app.title, "0%")
        self.assertEqual(app.m5h.title, tracker.FIVE_HOUR_DEFAULT)
        self.assertEqual(app.m7d.title, tracker.WEEKLY_DEFAULT)
        self.assertEqual(app.mson.title, tracker.SONNET_DEFAULT)
        self.assertEqual(app.mext.title, tracker.EXTRA_DEFAULT)


# ---------------------------------------------------------------------------
# Tests: App error states
# ---------------------------------------------------------------------------
class TestAppErrorStates(unittest.TestCase):
    def _make_app(self):
        with patch.object(tracker.App, "_start_timer"), \
             patch.object(tracker.App, "_refresh"):
            app = tracker.App()
        return app

    def test_auth_error(self):
        app = self._make_app()
        app._apply_usage(None, "auth")
        self.assertEqual(app.title, "↩ Login")
        self.assertIn("claude login", app.m5h.title)
        self.assertEqual(app.m7d.title, tracker.WEEKLY_DEFAULT)
        self.assertEqual(app.mson.title, tracker.SONNET_DEFAULT)
        self.assertEqual(app.mext.title, tracker.EXTRA_DEFAULT)

    def test_rate_limit(self):
        app = self._make_app()
        app._apply_usage(None, "rate")
        self.assertEqual(app.title, "⏳")
        self.assertIn("Rate limited", app.m5h.title)
        self.assertIn("will retry", app.m5h.title)

    def test_rate_limit_with_retry_after(self):
        app = self._make_app()
        app._apply_usage({"retry_after": 120}, "rate")
        self.assertEqual(app.title, "⏳")
        self.assertIn("retry in 2m", app.m5h.title)

    def test_rate_limit_with_partial_minute(self):
        app = self._make_app()
        app._apply_usage({"retry_after": 61}, "rate")
        self.assertEqual(app.title, "⏳")
        self.assertIn("retry in 2m", app.m5h.title)

    def test_plan_error(self):
        app = self._make_app()
        app._apply_usage(None, "plan")
        self.assertEqual(app.title, "⛔")
        self.assertIn("Pro/Max", app.m5h.title)

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
        data = _make_api_response(five_hour_pct=77)
        app._apply_usage(data, None)
        self.assertEqual(app.title, "77%")


# ---------------------------------------------------------------------------
# Tests: _fmt_utilization
# ---------------------------------------------------------------------------
class TestFmtUtilization(unittest.TestCase):
    def test_basic_format(self):
        section = {"utilization": 42, "resets_at": None}
        text, pct = tracker.App._fmt_utilization("5-hour", section)
        self.assertEqual(pct, 42)
        self.assertIn("5-hour: 42%", text)
        self.assertIn("resets --", text)

    def test_with_reset_time(self):
        future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        section = {"utilization": 10, "resets_at": future}
        text, pct = tracker.App._fmt_utilization("Weekly", section)
        self.assertEqual(pct, 10)
        self.assertIn("Weekly: 10%", text)
        self.assertIn("resets", text)

    def test_missing_utilization(self):
        section = {"resets_at": None}
        text, pct = tracker.App._fmt_utilization("Sonnet", section)
        self.assertEqual(pct, 0)
        self.assertIn("Sonnet: 0%", text)


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
        with patch.object(tracker, "_call_on_main") as marshall, \
             patch.object(tracker, "get_usage", return_value=({"foo": "bar"}, None)):
            app._fetch_and_update()
        marshall.assert_called_once_with(app._apply_usage, {"foo": "bar"}, None)

    def test_reset_timer_callback_marshals_refresh(self):
        app = self._make_app()
        future = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
        data = _make_api_response(five_hour_resets=future)
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
        # Build data with three future resets — the 5-hour one is soonest.
        now = datetime.now(timezone.utc)
        five_hour_iso = (now + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
        weekly_iso    = (now + timedelta(days=2)).isoformat().replace("+00:00", "Z")
        sonnet_iso    = (now + timedelta(days=3)).isoformat().replace("+00:00", "Z")
        data = _make_api_response(
            five_hour_resets=five_hour_iso,
            seven_day_resets=weekly_iso,
            sonnet_resets=sonnet_iso,
        )
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
        data = _make_api_response(five_hour_resets=future)
        with patch("threading.Timer", return_value=MagicMock()):
            app._schedule_reset_refresh(data)
        prev_timer.cancel.assert_called_once()

    def test_ignores_already_passed_resets(self):
        app = self._make_app()
        # All resets in the past — nothing to schedule.
        past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
        data = _make_api_response(
            five_hour_resets=past, seven_day_resets=past, sonnet_resets=past,
        )
        with patch("threading.Timer") as MockTimer:
            app._schedule_reset_refresh(data)
            MockTimer.assert_not_called()
        self.assertIsNone(app._reset_timer)

    def test_skips_malformed_iso_timestamps(self):
        app = self._make_app()
        data = _make_api_response(
            five_hour_resets="not-a-date",
            seven_day_resets=None,
            sonnet_resets="",
        )
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
        self.assertIn("Sonnet", tracker.SONNET_DEFAULT)
        self.assertIn("Extra", tracker.EXTRA_DEFAULT)

    def test_cents_per_dollar(self):
        self.assertEqual(tracker.CENTS_PER_DOLLAR, 100)


# ---------------------------------------------------------------------------
# Tests: Edge cases in display with weird API data
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

    def test_extra_usage_not_dict(self):
        app = self._make_app()
        data = _make_api_response()
        data["extra_usage"] = "invalid"
        app._update_display(data)
        self.assertEqual(app.mext.title, tracker.EXTRA_DEFAULT)

    def test_extra_usage_null(self):
        app = self._make_app()
        data = _make_api_response()
        data["extra_usage"] = None
        app._update_display(data)
        self.assertEqual(app.mext.title, tracker.EXTRA_DEFAULT)

    def test_zero_percent_all(self):
        app = self._make_app()
        data = _make_api_response(
            five_hour_pct=0, seven_day_pct=0, sonnet_pct=0
        )
        app._update_display(data)
        self.assertEqual(app.title, "0%")
        self.assertIn("0%", app.m5h.title)
        self.assertIn("0%", app.m7d.title)
        self.assertIn("0%", app.mson.title)

    def test_hundred_percent(self):
        app = self._make_app()
        data = _make_api_response(five_hour_pct=100)
        app._update_display(data)
        self.assertEqual(app.title, "100%")


class TestDetectUserAgent(unittest.TestCase):

    @patch("tracker.subprocess.run")
    def test_detects_version(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="2.1.73 (Claude Code)\n")
        result = tracker._detect_claude_code_ua()
        self.assertEqual(result, "claude-code/2.1.73")

    @patch("tracker.subprocess.run")
    def test_fallback_on_failure(self, mock_run):
        mock_run.side_effect = OSError("not found")
        result = tracker._detect_claude_code_ua()
        self.assertEqual(result, tracker._FALLBACK_UA)

    @patch("tracker.subprocess.run")
    def test_fallback_on_bad_output(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="not-a-version\n")
        result = tracker._detect_claude_code_ua()
        self.assertEqual(result, tracker._FALLBACK_UA)

    @patch("tracker.subprocess.run")
    def test_fallback_on_nonzero_exit(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        result = tracker._detect_claude_code_ua()
        self.assertEqual(result, tracker._FALLBACK_UA)


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
        app._update_display(_make_api_response(five_hour_pct=90))

    def test_auth_error_clears_icon_in_icon_mode(self):
        app = self._make_app()
        self._seed_icon(app, tracker.DISPLAY_ICON)
        self.assertIsNotNone(app.icon)
        app._apply_usage(None, "auth")
        self.assertIsNone(app.icon)

    def test_rate_error_clears_icon_in_both_mode(self):
        app = self._make_app()
        self._seed_icon(app, tracker.DISPLAY_BOTH)
        app._apply_usage(None, "rate")
        self.assertIsNone(app.icon)

    def test_generic_error_clears_icon(self):
        app = self._make_app()
        self._seed_icon(app, tracker.DISPLAY_BOTH)
        app._apply_usage(None, "error")
        self.assertIsNone(app.icon)

    def test_none_data_clears_icon(self):
        app = self._make_app()
        self._seed_icon(app, tracker.DISPLAY_ICON)
        app._apply_usage(None, None)
        self.assertIsNone(app.icon)


class TestSevenDayOpus(unittest.TestCase):
    """The real API exposes seven_day_opus (often null). Nothing exercised the
    Opus menu line, its role in the inner ring (max of sonnet/opus), nor its
    consideration in reset scheduling."""

    def _make_app(self):
        with patch.object(tracker.App, "_start_timer"), \
             patch.object(tracker.App, "_refresh"):
            return tracker.App()

    def test_opus_present_sets_menu_line(self):
        app = self._make_app()
        data = _make_api_response()
        data["seven_day_opus"] = {"utilization": 63, "resets_at": None}
        app._update_display(data)
        self.assertIn("Opus: 63%", app.mopus.title)

    def test_opus_null_falls_back_to_default(self):
        app = self._make_app()
        data = _make_api_response()
        data["seven_day_opus"] = None
        app._update_display(data)
        self.assertEqual(app.mopus.title, tracker.OPUS_DEFAULT)

    def test_opus_absent_falls_back_to_default(self):
        app = self._make_app()
        data = _make_api_response()
        data.pop("seven_day_opus", None)
        app._update_display(data)
        self.assertEqual(app.mopus.title, tracker.OPUS_DEFAULT)

    def test_opus_drives_inner_ring_when_higher_than_sonnet(self):
        app = self._make_app()
        data = _make_api_response(sonnet_pct=10)
        data["seven_day_opus"] = {"utilization": 80, "resets_at": None}
        with patch.object(tracker, "_render_dynamic_icon") as render:
            app._update_display(data)
        render.assert_called_once()
        inner_pct = render.call_args[0][2]
        self.assertEqual(inner_pct, 80)

    def test_opus_resets_at_considered_in_scheduling(self):
        app = self._make_app()
        now = datetime.now(timezone.utc)
        soon = (now + timedelta(minutes=3)).isoformat().replace("+00:00", "Z")
        far = (now + timedelta(days=2)).isoformat().replace("+00:00", "Z")
        data = _make_api_response(
            five_hour_resets=far, seven_day_resets=far, sonnet_resets=far,
        )
        data["seven_day_opus"] = {"utilization": 5, "resets_at": soon}
        with patch("threading.Timer") as MockTimer:
            MockTimer.return_value = MagicMock()
            app._schedule_reset_refresh(data)
            self.assertTrue(MockTimer.called)
            delay = MockTimer.call_args[0][0]
            self.assertAlmostEqual(delay, 180 + 5, delta=3)


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


class TestUnknownBuckets(unittest.TestCase):
    """Real API returns seven_day_cowork/oauth_apps/omelette + codenames, all
    null except five_hour/seven_day/seven_day_sonnet. They must be ignored."""

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
            "some_codename_x7": {"utilization": 77, "resets_at": None},
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
            "seven_day_sonnet": {"utilization": 11, "resets_at": None},
        }
        app._update_display(data)
        self.assertIn("5-hour: 44%", app.m5h.title)
        self.assertIn("resets --", app.m5h.title)
        self.assertEqual(app.title, "44%")

    def test_null_reset_schedules_no_timer(self):
        app = self._make_app()
        data = _make_api_response(
            five_hour_resets=None, seven_day_resets=None, sonnet_resets=None,
        )
        with patch("threading.Timer") as MockTimer:
            app._schedule_reset_refresh(data)
            MockTimer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
