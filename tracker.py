#!/usr/bin/env python3
"""
Tokease — macOS menu bar app.

Two data sources (see docs/adr/0001-pivot-source-statusline.md):

  statusline (DEFAULT, authorized) — Claude Code (>= 2.1.x) pipes
    rate_limits.five_hour / .seven_day into its statusline script. A capture
    script (statusline/tokease-statusline.py) writes those to
    ~/.tokease/usage.json; this app reads that file. The data is handed to us
    BY Claude Code, so it stays within the authorized "use with Claude Code"
    scope. No token read, no endpoint call, no User-Agent spoofing.

  endpoint (LEGACY, opt-in) — the v0.9 behaviour: read the OAuth token from
    the Keychain and call https://api.anthropic.com/api/oauth/usage. This
    likely violates Anthropic's Consumer Terms (the subscription token is
    authorized only for Claude Code / Claude.ai) and is kept off by default,
    behind a Settings toggle and a ToS warning.

Security notes (endpoint mode):
  - Token is read into a local variable, used once, then cleared — never
    stored as an instance attribute or logged anywhere. The full credentials
    blob (`creds`, `result.stdout`) is also deleted before the HTTP call.
  - HTTP redirects are blocked: a custom NoRedirectHandler prevents urllib
    from following 3xx responses, which would resend the Bearer token to
    an arbitrary domain.
  - Specific exception types are caught; bare `except:` is never used so
    KeyboardInterrupt / SystemExit propagate normally.
  - HTTP 401/403/429 are detected explicitly for clear user feedback.
  - The User-Agent is built lazily, only when endpoint mode is actually used.
"""

import json
import re
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

import rumps

# AppHelper.callAfter marshals a callable back onto the main runloop. Required
# because AppKit asserts when NSStatusItem / NSImage are mutated off-thread —
# without it, a background _fetch_and_update tick can SIGABRT the whole app.
try:
    from PyObjCTools.AppHelper import callAfter as _call_on_main
except ImportError:  # pragma: no cover — only hit on non-Mac dev installs
    def _call_on_main(fn, *args, **kwargs):
        fn(*args, **kwargs)

# Pillow is used for the dynamic ring icon; gracefully no-op when absent so
# a source install without Pillow still works (falls back to the static icon).
try:
    from PIL import Image, ImageDraw
    _PILLOW_AVAILABLE = True
except ImportError:
    _PILLOW_AVAILABLE = False

# NSUserDefaults persists settings across launches under the .app's bundle id.
# Optional so non-macOS test environments (no PyObjC) still import cleanly.
try:
    from Foundation import NSUserDefaults
    _DEFAULTS = NSUserDefaults.standardUserDefaults()
except ImportError:
    _DEFAULTS = None

# Resolves both from source (repo root + assets/) and from the py2app bundle
# (Resources/assets/) — DATA_FILES in setup.py places it under Resources/assets.
_ICON_PATH = Path(__file__).resolve().parent / "assets" / "menubar-template.png"

# Dynamic-icon rendering: rewritten on every refresh, lives in tempdir so it
# never mutates the bundled assets and gets cleaned by macOS periodically.
_DYNAMIC_ICON_PATH = Path(tempfile.gettempdir()) / "tokease-icon.png"

# Icon geometry — must stay consistent with assets/build-menubar-icon.py so
# the dynamic and fallback static icons have the same visual footprint.
_ICON_SIZE_FINAL = 44
_ICON_SCALE = 4
_ICON_SIZE = _ICON_SIZE_FINAL * _ICON_SCALE
_RING_RADII = (20, 14, 8)      # outer, middle, inner (at final scale)
_RING_STROKE = 3                # final-scale stroke width
_TRACK_ALPHA = 180              # background ring opacity so 0% reads as an empty "container", not a ghost


def _render_dynamic_icon(session_pct, weekly_pct, inner_pct):
    """
    Render the 3-ring icon with arcs filled per current usage metric.

    Outer ring = 5-hour session %, middle = weekly %, inner = max(sonnet, opus).
    Each arc starts at 12 o'clock and sweeps clockwise. A faint full ring is
    drawn behind each arc so 0% still has a visual outline.

    Returns the path to a freshly written PNG, or None if Pillow is missing
    (in which case the caller keeps the existing static icon).
    """
    if not _PILLOW_AVAILABLE:
        return None
    img = Image.new("RGBA", (_ICON_SIZE, _ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    center = _ICON_SIZE // 2
    stroke = _RING_STROKE * _ICON_SCALE

    for radius, pct in zip(_RING_RADII, (session_pct, weekly_pct, inner_pct)):
        if pct is None:
            continue  # window absent/stale (e.g. statusline mode has no inner ring)
        r = radius * _ICON_SCALE
        bbox = (center - r, center - r, center + r, center + r)
        draw.ellipse(bbox, outline=(0, 0, 0, _TRACK_ALPHA), width=stroke)
        pct_clamped = max(0, min(100, int(pct)))
        if pct_clamped > 0:
            sweep = (pct_clamped / 100.0) * 360.0
            draw.arc(bbox, start=-90, end=-90 + sweep,
                     fill=(0, 0, 0, 255), width=stroke)

    img = img.resize((_ICON_SIZE_FINAL, _ICON_SIZE_FINAL), Image.LANCZOS)
    img.save(_DYNAMIC_ICON_PATH)
    return _DYNAMIC_ICON_PATH

# ---------------------------------------------------------------------------
# Refresh interval options (label → seconds)
# ---------------------------------------------------------------------------
INTERVALS = {
    "Every 1 minute": 60,
    "Every 5 minutes": 300,
    "Every 30 minutes": 1800,
    "Every hour": 3600,
}

CENTS_PER_DOLLAR = 100
# Used only when `claude --version` cannot be found in PATH — the LaunchAgent
# ships with a minimal PATH so this fallback matters in practice.
_FALLBACK_UA = "claude-code/2.1.145"

# Notification thresholds (5-hour session %). Sorted ascending. Notifications
# fire when the pct CROSSES one upward — never on first observation, never
# repeatedly while sitting at/above the threshold.
NOTIFY_THRESHOLDS = (80, 95)

# Display mode: which combination of icon + text appears in the menu bar.
DISPLAY_BOTH = "both"
DISPLAY_PCT = "pct"
DISPLAY_ICON = "icon"

# Persisted-setting keys
_KEY_DISPLAY_MODE = "display_mode"
_KEY_ALERTS = "alerts_enabled"
_KEY_INTERVAL = "interval_secs"
_KEY_SOURCE = "data_source"

# Data source: authorized statusline feed (default) vs legacy direct-endpoint.
SOURCE_STATUSLINE = "statusline"
SOURCE_ENDPOINT = "endpoint"
_VALID_SOURCES = (SOURCE_STATUSLINE, SOURCE_ENDPOINT)

# File written by the Claude Code statusline capture script
# (statusline/tokease-statusline.py). Read on every refresh in statusline mode.
_STATUSLINE_FILE = Path.home() / ".tokease" / "usage.json"

# Captured statusline data older than this (seconds) is shown as stale —
# the signal that Claude Code isn't running to refresh it.
_STALE_AFTER_SECS = 15 * 60

# Two-space spacer between icon and percentage so the digits don't crowd the
# rings. Menu bar font renders one space at ~4 px; two = comfortable gap.
_TITLE_SPACER = "  "

# External links (Support submenu). Change DONATE_URL to BMC/Ko-fi/PayPal etc.
# if GitHub Sponsors isn't your preferred platform.
STAR_URL = "https://github.com/tpatrouillat/tokease"
DONATE_URL = "https://github.com/sponsors/tpatrouillat"

# Login-item registration uses the .app's CFBundleDisplayName — must match
# Info.plist exactly or `delete login item` won't find it.
LOGIN_ITEM_NAME = "Tokease"

# Default menu item text (extracted to avoid string duplication)
FIVE_HOUR_DEFAULT = "5-hour: --"
WEEKLY_DEFAULT = "Weekly: --"
SONNET_DEFAULT = "Sonnet: --"
OPUS_DEFAULT = "Opus: --"
EXTRA_DEFAULT = "Extra: --"
UPDATED_DEFAULT = "Updated: --"

# ---------------------------------------------------------------------------
# Settings persistence (NSUserDefaults)
# ---------------------------------------------------------------------------

def _settings_get(key, default):
    """Read a setting from NSUserDefaults; returns default if unset/unavailable."""
    if _DEFAULTS is None:
        return default
    try:
        val = _DEFAULTS.objectForKey_(key)
        return val if val is not None else default
    except Exception:
        return default


def _settings_set(key, value):
    if _DEFAULTS is None:
        return
    try:
        _DEFAULTS.setObject_forKey_(value, key)
        _DEFAULTS.synchronize()
    except Exception as exc:  # non-critical: setting just won't persist — log, don't mask
        print(f"tokease: settings write failed: {exc!r}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Login-item management (macOS System Events)
# ---------------------------------------------------------------------------

def _get_app_path():
    """Return the .app bundle path if running as a frozen bundle, else None."""
    if not getattr(sys, "frozen", None):
        return None
    try:
        p = Path(sys.executable).resolve()
        for parent in p.parents:
            if parent.suffix == ".app":
                return str(parent)
    except OSError:
        pass
    return None


def _is_login_item():
    try:
        result = subprocess.run(
            ["/usr/bin/osascript", "-e",
             'tell application "System Events" to get the name of every login item'],
            capture_output=True, text=True, timeout=5,
        )
        return LOGIN_ITEM_NAME in (result.stdout or "")
    except (OSError, subprocess.TimeoutExpired):
        return False


def _set_login_item(enabled, app_path):
    # Reject paths containing characters that would break out of the AppleScript
    # string literal (path comes from sys.executable so this is defence-in-depth).
    if any(c in app_path for c in '"\\\n'):
        return
    try:
        if enabled:
            script = (
                f'tell application "System Events" to make login item '
                f'at end with properties '
                f'{{path:"{app_path}", hidden:false}}'
            )
        else:
            script = (
                f'tell application "System Events" to '
                f'delete login item "{LOGIN_ITEM_NAME}"'
            )
        subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            capture_output=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


# ---------------------------------------------------------------------------
# User-Agent detection
# ---------------------------------------------------------------------------

def _detect_claude_code_ua():
    """Detect installed Claude Code version for the User-Agent header."""
    try:
        result = subprocess.run(
            ["claude", "--version"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            version = result.stdout.strip().split()[0]
            if re.fullmatch(r"\d+\.\d+\.\d+", version):
                return f"claude-code/{version}"
    except (OSError, subprocess.TimeoutExpired, IndexError):
        pass
    return _FALLBACK_UA

# Lazily detected: only legacy endpoint mode sends a User-Agent, so the default
# (statusline) path never even builds the claude-code/* string.
_user_agent = None


def _get_user_agent():
    global _user_agent
    if _user_agent is None:
        _user_agent = _detect_claude_code_ua()
    return _user_agent

# ---------------------------------------------------------------------------
# Security: block HTTP redirects to prevent Bearer token leaking to other
# domains if the API endpoint ever returns a 3xx.
# ---------------------------------------------------------------------------

class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject all HTTP redirects — prevents leaking the Bearer token."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(
            req.full_url, code, "Redirect blocked for security", headers, fp
        )

_opener = urllib.request.build_opener(_NoRedirectHandler)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_int(val, default=0):
    """Convert an API value to a clamped non-negative int, never crash."""
    try:
        return max(0, int(float(val))) if val is not None else default
    except (ValueError, TypeError):
        return default


def _epoch_to_iso(epoch):
    """Convert epoch seconds (statusline resets_at) into an ISO string fmt_reset reads."""
    try:
        return datetime.fromtimestamp(float(epoch), timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None

# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def _read_keychain_token():
    """
    Read the Claude Code OAuth token from the macOS Keychain.

    Returns:
        (str, None)      token on success
        (None, "auth")   when the token is missing or keychain entry not found
        (None, "error")  on timeout or OS-level failure
    """
    try:
        result = subprocess.run(
            ["/usr/bin/security", "find-generic-password",
             "-s", "Claude Code-credentials", "-w"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None, "auth"
        raw = result.stdout.strip()
        del result
        # Try full JSON parse first; fall back to regex if the keychain
        # CLI truncates the blob (macOS clips at ~2 KB).
        try:
            creds = json.loads(raw)
            token = creds.get("claudeAiOauth", {}).get("accessToken")
            del creds
        except json.JSONDecodeError:
            m = re.search(r'"accessToken"\s*:\s*"([^"]+)"', raw)
            token = m.group(1) if m else None
        del raw
        if not token:
            return None, "auth"
        return token, None
    except subprocess.TimeoutExpired:
        return None, "error"
    except OSError:
        return None, "error"


def get_usage():
    """
    Fetch subscription usage from the Anthropic OAuth usage endpoint.

    Returns:
        (dict, None)     on success
        (None, "auth")   when the token is missing or expired (HTTP 401)
        (None, "plan")   when the subscription plan lacks access (HTTP 403)
        (None, "rate")   when rate-limited (HTTP 429)
        (None, "error")  on any other failure
    """
    token, err = _read_keychain_token()
    if err:
        return None, err

    req = None
    try:
        req = urllib.request.Request(
            "https://api.anthropic.com/api/oauth/usage",
            headers={
                "Authorization": f"Bearer {token}",
                "anthropic-beta": "oauth-2025-04-20",
                "User-Agent": _get_user_agent(),
            },
        )
        with _opener.open(req, timeout=10) as resp:
            data = json.loads(resp.read())
            if not isinstance(data, dict):
                return None, "error"
            return data, None
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            return None, "auth"
        if exc.code == 429:
            retry_secs = _safe_int(exc.headers.get("Retry-After")) if exc.headers else 0
            return {"retry_after": retry_secs}, "rate"
        if exc.code == 403:
            return None, "plan"
        return None, "error"
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return None, "error"
    finally:
        token = None
        req = None


def fetch_usage(source):
    """Dispatch to the configured data source and tag the result with _meta.

    statusline (default, authorized): read the file the Claude Code statusline
    script writes. endpoint (legacy): the v0.9 direct-endpoint behaviour.
    Returns (data, err) — same contract as get_usage().
    """
    if source == SOURCE_ENDPOINT:
        data, err = get_usage()
        if data is not None and err is None:
            data["_meta"] = {"source": SOURCE_ENDPOINT, "captured_at": None}
        return data, err
    return _get_usage_statusline()


def _get_usage_statusline():
    """Read usage captured by the Claude Code statusline script.

    Normalises to the shape _update_display expects (used_percentage→utilization,
    epoch→ISO) and tags _meta. Error codes: 'nostatusline' (file missing → not
    wired yet), 'waiting' (file present but no rate_limits captured yet),
    'error' (unreadable / invalid).
    """
    try:
        raw = _STATUSLINE_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, "nostatusline"
    except OSError:
        return None, "error"
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, "error"
    if not isinstance(payload, dict):
        return None, "error"

    data = {}
    for key in ("five_hour", "seven_day"):
        win = payload.get(key)
        if isinstance(win, dict) and win.get("used_percentage") is not None:
            data[key] = {
                "utilization": win.get("used_percentage"),
                "resets_at": _epoch_to_iso(win.get("resets_at")),
            }
    if not data:
        return None, "waiting"
    data["_meta"] = {"source": SOURCE_STATUSLINE, "captured_at": payload.get("captured_at")}
    return data, None


# ---------------------------------------------------------------------------
# Time formatting
# ---------------------------------------------------------------------------

def _parse_iso(iso):
    """Parse an ISO-8601 timestamp from the API into a timezone-aware datetime.

    Returns None for empty / malformed input. Centralised here so callers that
    need the raw datetime (e.g. for reset-window scheduling) don't duplicate
    the Python-version normalisation that `fmt_reset` already does.
    """
    if not iso:
        return None
    try:
        # Normalise: strip sub-seconds, handle "Z" suffix, fix colon in offset
        clean = iso.replace("Z", "+00:00").split(".")[0]
        # Python <3.11 fromisoformat doesn't accept "+00:00", needs "+0000"
        if len(clean) >= 6 and clean[-3] == ":" and clean[-6] in ("+", "-"):
            clean = clean[:-3] + clean[-2:]
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, OverflowError, IndexError, AttributeError, TypeError):
        return None


def fmt_reset(iso):
    """Format an ISO timestamp into a human-readable countdown."""
    dt = _parse_iso(iso)
    if dt is None:
        return "--" if not iso else "?"
    diff = dt - datetime.now(timezone.utc)
    if diff.total_seconds() < 0:
        return "now"
    if diff.days == 0:
        h = diff.seconds // 3600
        m = (diff.seconds % 3600) // 60
        return f"{h}h {m}m" if h else f"{m}m"
    return dt.strftime("%b %d")


# ---------------------------------------------------------------------------
# Menu bar application
# ---------------------------------------------------------------------------

class App(rumps.App):

    def __init__(self):
        # Load persisted preferences (falls back to defaults if unset)
        # _safe_int + clamp: a corrupted or 0 persisted value must not crash startup nor yield Timer(0).
        self.interval = max(60, _safe_int(_settings_get(_KEY_INTERVAL, 300), 300))
        self.alerts_enabled = bool(_settings_get(_KEY_ALERTS, True))
        self.display_mode = str(_settings_get(_KEY_DISPLAY_MODE, DISPLAY_BOTH))
        if self.display_mode not in (DISPLAY_BOTH, DISPLAY_PCT, DISPLAY_ICON):
            self.display_mode = DISPLAY_BOTH

        # Data source: authorized statusline feed by default; endpoint is opt-in legacy.
        src = str(_settings_get(_KEY_SOURCE, SOURCE_STATUSLINE))
        self.data_source = src if src in _VALID_SOURCES else SOURCE_STATUSLINE

        # template=True lets macOS auto-invert the icon for dark mode.
        # Pass the icon path only if it exists — a missing asset shouldn't
        # crash the app, just fall back to text-only menu bar.
        icon = str(_ICON_PATH) if _ICON_PATH.exists() else None
        super().__init__(
            "Claude", title="...", icon=icon, template=True, quit_button=None,
        )
        self._timer = None
        self._reset_timer = None  # one-shot threading.Timer that fires just after a usage window rolls over
        self._app_path = _get_app_path()  # None when running from source

        # Notification state: None = no baseline yet (first observation).
        # Tracked in-memory only; resets on restart.
        self._last_pct = None

        # Usage display items
        self.m5h   = rumps.MenuItem("5-hour: ...")
        self.m7d   = rumps.MenuItem("Weekly: ...")
        self.mson  = rumps.MenuItem("Sonnet: ...")
        self.mopus = rumps.MenuItem("Opus: ...")
        self.mext  = rumps.MenuItem(EXTRA_DEFAULT)
        self.mupd  = rumps.MenuItem(UPDATED_DEFAULT)

        # --- Settings submenu --------------------------------------------
        # Launch at login (only meaningful when running as a .app bundle)
        if self._app_path:
            self.m_login = rumps.MenuItem(
                "Launch at login", callback=self._toggle_login,
            )
            self.m_login.state = 1 if _is_login_item() else 0
        else:
            self.m_login = rumps.MenuItem("Launch at login (install .app first)")
            # No callback → menu item appears greyed out

        # Display mode (radio group)
        display_menu = rumps.MenuItem("Display")
        self._display_items = {}
        for mode, label in (
            (DISPLAY_BOTH, "Icon + percentage"),
            (DISPLAY_PCT,  "Percentage only"),
            (DISPLAY_ICON, "Icon only"),
        ):
            item = rumps.MenuItem(label, callback=self._set_display_mode)
            item._mode = mode  # stash mode on the item for the callback
            self._display_items[mode] = item
            display_menu.add(item)
        self._update_display_menu()

        # Data source (radio group): authorized statusline vs legacy endpoint
        source_menu = rumps.MenuItem("Data source")
        self._source_items = {}
        for src_mode, label in (
            (SOURCE_STATUSLINE, "Claude Code statusline (recommended)"),
            (SOURCE_ENDPOINT, "Direct API — legacy, at your own risk"),
        ):
            item = rumps.MenuItem(label, callback=self._set_source)
            item._source = src_mode  # stash mode on the item for the callback
            self._source_items[src_mode] = item
            source_menu.add(item)
        self._update_source_menu()

        # Notification toggle
        self.m_alerts = rumps.MenuItem(
            f"Alert at {NOTIFY_THRESHOLDS[0]}% / {NOTIFY_THRESHOLDS[1]}%",
            callback=self._toggle_alerts,
        )
        self.m_alerts.state = 1 if self.alerts_enabled else 0

        # Refresh interval (radio submenu)
        interval_menu = rumps.MenuItem("Refresh Interval")
        self._interval_items = {}   # secs → MenuItem
        self._item_to_secs = {}     # MenuItem title → secs
        for label, secs in INTERVALS.items():
            item = rumps.MenuItem(label, callback=self._set_interval)
            self._interval_items[secs] = item
            self._item_to_secs[label] = secs
            interval_menu.add(item)

        settings_menu = rumps.MenuItem("Settings")
        settings_menu.add(self.m_login)
        settings_menu.add(display_menu)
        settings_menu.add(source_menu)
        settings_menu.add(self.m_alerts)
        settings_menu.add(interval_menu)

        # --- Support submenu --------------------------------------------
        support_menu = rumps.MenuItem("Support")
        support_menu.add(rumps.MenuItem("Star on GitHub", callback=self._open_star))
        support_menu.add(rumps.MenuItem("Sponsor / Donate", callback=self._open_donate))

        self.menu = [
            self.m5h, self.m7d, self.mson, self.mopus, None,
            self.mext, None,
            self.mupd,
            rumps.MenuItem("Refresh", callback=self._refresh),
            None,
            settings_menu,
            support_menu, None,
            rumps.MenuItem("Quit", callback=rumps.quit_application),
        ]

        self._update_interval_menu()
        self._refresh(None)
        self._start_timer()

    # ------------------------------------------------------------------
    # Interval management
    # ------------------------------------------------------------------

    def _update_interval_menu(self):
        for secs, item in self._interval_items.items():
            item.state = 1 if secs == self.interval else 0

    def _update_display_menu(self):
        for mode, item in self._display_items.items():
            item.state = 1 if mode == self.display_mode else 0

    def _update_source_menu(self):
        for src_mode, item in self._source_items.items():
            item.state = 1 if src_mode == self.data_source else 0

    def _set_source(self, sender):
        self.data_source = sender._source
        _settings_set(_KEY_SOURCE, self.data_source)
        self._update_source_menu()
        # Re-fetch immediately so the switch takes effect without waiting for the timer.
        self._refresh(None)

    def _set_interval(self, sender):
        self.interval = self._item_to_secs[sender.title]
        _settings_set(_KEY_INTERVAL, self.interval)
        self._update_interval_menu()
        self._start_timer()

    def _set_display_mode(self, sender):
        self.display_mode = sender._mode
        _settings_set(_KEY_DISPLAY_MODE, self.display_mode)
        self._update_display_menu()
        # Re-render immediately so the menu bar reflects the change without
        # waiting for the next poll.
        self._refresh(None)

    def _toggle_alerts(self, sender):
        self.alerts_enabled = not self.alerts_enabled
        _settings_set(_KEY_ALERTS, self.alerts_enabled)
        sender.state = 1 if self.alerts_enabled else 0

    def _toggle_login(self, sender):
        new_state = not bool(sender.state)
        _set_login_item(new_state, self._app_path)
        # Verify by querying System Events, since the user may have denied
        # the Automation permission prompt on first call.
        sender.state = 1 if _is_login_item() else 0

    def _open_star(self, _):
        webbrowser.open(STAR_URL)

    def _open_donate(self, _):
        webbrowser.open(DONATE_URL)

    def _maybe_notify(self, pct):
        """Fire a notification when pct crosses a threshold upward."""
        previous = self._last_pct
        self._last_pct = pct
        if not self.alerts_enabled or previous is None:
            return
        crossed = [t for t in NOTIFY_THRESHOLDS if previous < t <= pct]
        if not crossed:
            return
        threshold = max(crossed)
        try:
            rumps.notification(
                title="Tokease",
                subtitle=f"Session at {pct}%",
                message=f"You've passed {threshold}% of your 5-hour limit.",
            )
        except Exception as exc:
            # rumps.notification needs a signed bundle on recent macOS; from source
            # it can't fire — log rather than mask, but never crash the refresh.
            print(f"tokease: notification skipped: {exc!r}", file=sys.stderr)

    def _start_timer(self):
        if self._timer:
            self._timer.stop()
        self._timer = rumps.Timer(lambda _: self._refresh(None), self.interval)
        self._timer.start()

    def _schedule_reset_refresh(self, data):
        """Trigger a one-shot refresh shortly after the soonest usage window resets,
        so the rings clear out promptly even when the user picked a long refresh
        interval (e.g. 'Every hour'). Without this, the menu can show stale
        pre-reset numbers for up to a full interval after a window rolls over."""
        if self._reset_timer is not None:
            self._reset_timer.cancel()
            self._reset_timer = None

        now = datetime.now(timezone.utc)
        soonest = None
        for key in ("five_hour", "seven_day", "seven_day_sonnet", "seven_day_opus"):
            section = data.get(key)
            if not isinstance(section, dict):
                continue
            dt = _parse_iso(section.get("resets_at"))
            if dt is None or dt <= now:
                continue
            if soonest is None or dt < soonest:
                soonest = dt

        if soonest is None:
            return

        # +5s buffer so Anthropic's backend has rolled the window before we re-poll.
        # Marshal _refresh onto the main thread — it sets self.title and would
        # otherwise inherit the threading.Timer's background thread (crash risk).
        delay = (soonest - now).total_seconds() + 5
        timer = threading.Timer(delay, lambda: _call_on_main(self._refresh, None))
        timer.daemon = True
        timer.start()
        self._reset_timer = timer

    # ------------------------------------------------------------------
    # Data refresh
    # ------------------------------------------------------------------

    def _refresh(self, _):
        self.title = "..."
        threading.Thread(target=self._fetch_and_update, daemon=True).start()

    def _fetch_and_update(self):
        try:
            data, err = fetch_usage(self.data_source)
        except Exception as exc:  # worker thread must never die silently, else the menu freezes on "..."
            print(f"tokease: unexpected fetch error: {exc!r}", file=sys.stderr)
            data, err = None, "error"
        # Marshal back to the main thread before touching menu items or icon —
        # mutating NSStatusItem off the main thread eventually trips an AppKit
        # assertion and SIGABRTs the app (latent crash on long-running installs).
        _call_on_main(self._apply_usage, data, err)

    def _apply_usage(self, data, err):
        # Error states always show their text indicator regardless of display
        # mode — the user needs to see *why* numbers aren't updating.
        if err or not data:
            # Clear any stale ring icon so it can't contradict the error glyph;
            # in ICON mode the title is empty, so a frozen ring would mislead.
            self.icon = None
        if err == "auth":
            self.title = "↩ Login"
            self.m5h.title   = "Run: claude login"
            self.m7d.title   = WEEKLY_DEFAULT
            self.mson.title  = SONNET_DEFAULT
            self.mopus.title = OPUS_DEFAULT
            self.mext.title  = EXTRA_DEFAULT
            return

        if err == "rate":
            self.title = "⏳"
            retry_secs = data.get("retry_after", 0) if isinstance(data, dict) else 0
            if retry_secs > 0:
                mins = (retry_secs + 59) // 60
                self.m5h.title = f"Rate limited — retry in {mins}m"
            else:
                self.m5h.title = "Rate limited — will retry"
            return

        if err == "plan":
            self.title = "⛔"
            self.m5h.title = "Pro/Max plan required"
            return

        if err == "nostatusline":
            # statusline mode but the capture file doesn't exist yet — not wired.
            self.title = "⚙"
            self.m5h.title   = "Set up Claude Code statusline →"
            self.m7d.title   = WEEKLY_DEFAULT
            self.mson.title  = SONNET_DEFAULT
            self.mopus.title = OPUS_DEFAULT
            self.mext.title  = EXTRA_DEFAULT
            return

        if err == "waiting":
            # File exists but Claude Code hasn't surfaced rate_limits yet
            # (appears only after the first API response of a session).
            self.title = "…"
            self.m5h.title   = "Waiting for Claude Code activity…"
            self.m7d.title   = WEEKLY_DEFAULT
            self.mson.title  = SONNET_DEFAULT
            self.mopus.title = OPUS_DEFAULT
            self.mext.title  = EXTRA_DEFAULT
            return

        if err or not data:
            self.title = "?"
            return

        self._update_display(data)

    def _apply_display(self, pct_text, icon_path):
        """Apply the title + icon according to the user's display_mode preference."""
        if self.display_mode == DISPLAY_PCT:
            self.title = pct_text
            self.icon = None
        elif self.display_mode == DISPLAY_ICON:
            self.title = ""
            if icon_path:
                self.icon = str(icon_path)
        else:  # DISPLAY_BOTH
            self.title = f"{_TITLE_SPACER}{pct_text}"
            if icon_path:
                self.icon = str(icon_path)

    @staticmethod
    def _fmt_utilization(label, section):
        """Format a utilization section as 'Label: N% (resets ...)'."""
        pct = _safe_int(section.get("utilization"))
        return f"{label}: {pct}% (resets {fmt_reset(section.get('resets_at'))})", pct

    @staticmethod
    def _window_row(label, section, now, captured):
        """Format a usage window row → (text, pct_for_ring).

        pct_for_ring is None when the window has already reset since the data
        was captured (statusline mode only): the stored % is no longer valid,
        so the caller skips that ring and shows '—' instead of a stale number.
        """
        pct = _safe_int(section.get("utilization"))
        if captured:
            dt = _parse_iso(section.get("resets_at"))
            if dt is not None and dt <= now:
                return f"{label}: — (reset; awaiting Claude Code)", None
        return f"{label}: {pct}% (resets {fmt_reset(section.get('resets_at'))})", pct

    @staticmethod
    def _freshness_label(captured_at, now):
        """'Updated' line for statusline mode, flagging stale (Claude Code idle) data."""
        if not captured_at:
            return UPDATED_DEFAULT
        try:
            cap = datetime.fromtimestamp(float(captured_at), timezone.utc)
            local = datetime.fromtimestamp(float(captured_at)).strftime("%H:%M")
        except (TypeError, ValueError, OverflowError, OSError):
            return UPDATED_DEFAULT
        age = (now - cap).total_seconds()
        if age > _STALE_AFTER_SECS:
            return f"⚠ {local} · stale {int(age // 60)}m (Claude Code idle?)"
        return f"Updated: {local} (via Claude Code)"

    def _set_unsupported_rows(self):
        """Rows the statusline feed can't provide: per-model split and paid overage."""
        self.mson.title = "Sonnet: n/a"
        self.mopus.title = "Opus: n/a"
        self.mext.title = "Extra: n/a"

    def _update_endpoint_rows(self, data, now):
        """Per-model rows + paid overage (endpoint mode). Returns the inner-ring pct."""
        sonnet_pct = opus_pct = 0
        if s := data.get("seven_day_sonnet"):
            self.mson.title, sonnet_pct = self._window_row("Sonnet", s, now, False)
        else:
            self.mson.title = SONNET_DEFAULT
        if o := data.get("seven_day_opus"):
            self.mopus.title, opus_pct = self._window_row("Opus", o, now, False)
        else:
            self.mopus.title = OPUS_DEFAULT

        e = data.get("extra_usage")
        if isinstance(e, dict) and e.get("is_enabled"):
            used  = _safe_int(e.get("used_credits")) / CENTS_PER_DOLLAR
            limit = _safe_int(e.get("monthly_limit")) / CENTS_PER_DOLLAR
            pct   = _safe_int(e.get("utilization"))
            self.mext.title = f"Extra: ${used:.2f}/${limit:.0f} ({pct}%)"
        else:
            self.mext.title = EXTRA_DEFAULT

        # Surface the model the user is most at risk of capping out on.
        return max(sonnet_pct, opus_pct)

    def _update_display(self, data):
        now = datetime.now(timezone.utc)
        meta = data.get("_meta", {})
        is_statusline = meta.get("source") == SOURCE_STATUSLINE
        session_pct = weekly_pct = 0

        # 5-hour session (also drives the menu bar title and threshold alerts)
        if h := data.get("five_hour"):
            self.m5h.title, session_pct = self._window_row("5-hour", h, now, is_statusline)
            if session_pct is not None:
                self._maybe_notify(session_pct)
        else:
            self.m5h.title = FIVE_HOUR_DEFAULT

        # 7-day weekly
        if d := data.get("seven_day"):
            self.m7d.title, weekly_pct = self._window_row("Weekly", d, now, is_statusline)
        else:
            self.m7d.title = WEEKLY_DEFAULT

        # Inner ring = per-model saturation; the statusline feed has no such split.
        if is_statusline:
            self._set_unsupported_rows()
            inner_pct = None
            self.mupd.title = self._freshness_label(meta.get("captured_at"), now)
        else:
            inner_pct = self._update_endpoint_rows(data, now)
            self.mupd.title = f"Updated: {datetime.now().strftime('%H:%M')}"

        icon_path = _render_dynamic_icon(session_pct, weekly_pct, inner_pct)
        title_pct = f"{session_pct}%" if session_pct is not None else "—"
        self._apply_display(title_pct, icon_path)

        self._schedule_reset_refresh(data)


if __name__ == "__main__":
    App().run()
