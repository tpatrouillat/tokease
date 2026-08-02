#!/usr/bin/env python3
"""
Tokease — macOS menu bar app.

Two local data sources, merged by freshness:
1. the Claude Code statusline feed (docs/adr/0001-pivot-source-statusline.md),
   captured into ~/.tokease/usage.json by statusline/tokease-statusline.py.
   Primary source, the only one that provides reset times.
2. the quota history sampled by the Claude desktop app
   (docs/adr/0003-source-secondaire-plan-usage-desktop.md). Read-only,
   refreshed ~5 min while the app runs, whatever surface is being used.
In both cases the data is written locally by an official Claude client:
never a read of the OAuth token, never a call to the Anthropic endpoint.

Consequence: only the 5h and weekly windows are available (2 rings).
The per-model split (Sonnet/Opus) and the paid overage are not in this feed.
"""

import json
import os
import subprocess
import sys
import threading
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

# Menu bar app = no Dock icon. The py2app bundle sets LSUIElement in its
# Info.plist, but source and Homebrew installs run under plain Python, whose
# bundle doesn't — without this, a "Python" icon appears in the Dock.
try:
    from Foundation import NSBundle
    _bundle_info = NSBundle.mainBundle().infoDictionary()
    if _bundle_info is not None and not _bundle_info.get("LSUIElement"):
        _bundle_info["LSUIElement"] = "1"
except Exception as _exc:  # PyObjC absent (CI) or odd bundle: never block startup
    print(f"tokease: dock-icon suppression unavailable: {_exc!r}", file=sys.stderr)

def _resolve_icon_path():
    """Menu bar icon path, either from source (assets/ next to the script)
    OR from the frozen py2app bundle: py2app puts DATA_FILES under Resources/
    and exposes it via $RESOURCEPATH (Path(__file__) no longer points there
    once frozen)."""
    if getattr(sys, "frozen", False):
        res = os.environ.get("RESOURCEPATH")
        if res:
            return Path(res) / "assets" / "menubar-template.png"
    return Path(__file__).resolve().parent / "assets" / "menubar-template.png"


_ICON_PATH = _resolve_icon_path()

# Dynamic-icon rendering: rewritten on every refresh, kept inside ~/.tokease so
# every write stays confined to the app's own dir (privacy invariant) and never
# mutates the bundled assets.
_TOKEASE_DIR = Path.home() / ".tokease"
_DYNAMIC_ICON_PATH = _TOKEASE_DIR / "tokease-icon.png"

# Icon geometry — must stay consistent with assets/build-menubar-icon.py so
# the dynamic and fallback static icons have the same visual footprint.
_ICON_SIZE_FINAL = 44
_ICON_SCALE = 4
_ICON_SIZE = _ICON_SIZE_FINAL * _ICON_SCALE
_RING_RADII = (20, 14)         # outer (5h), inner (weekly), at final scale
_RING_STROKE = 3                # final-scale stroke width
_TRACK_ALPHA = 76               # ~30% opacity (macOS secondary-track norm) — faint container, filled arc pops


def _render_dynamic_icon(session_pct, weekly_pct):
    """
    Draw the 2-ring icon, filled according to current usage.

    Outer ring = 5h session %, inner ring = weekly %. Each arc starts at noon
    and sweeps clockwise. A faint full circle is drawn behind so that 0% keeps
    a visible outline.

    Returns the path of the freshly written PNG, or None when Pillow is absent
    (the caller then keeps the existing static icon).
    """
    if not _PILLOW_AVAILABLE:
        return None
    img = Image.new("RGBA", (_ICON_SIZE, _ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    center = _ICON_SIZE // 2
    stroke = _RING_STROKE * _ICON_SCALE

    for radius, pct in zip(_RING_RADII, (session_pct, weekly_pct)):
        r = radius * _ICON_SCALE
        bbox = (center - r, center - r, center + r, center + r)
        # the track is always drawn: absent/reset window = empty ring
        draw.ellipse(bbox, outline=(0, 0, 0, _TRACK_ALPHA), width=stroke)
        if pct is None:
            continue
        pct_clamped = max(0, min(100, int(pct)))
        if pct_clamped > 0:
            sweep = (pct_clamped / 100.0) * 360.0
            draw.arc(bbox, start=-90, end=-90 + sweep,
                     fill=(0, 0, 0, 255), width=stroke)

    img = img.resize((_ICON_SIZE_FINAL, _ICON_SIZE_FINAL), Image.LANCZOS)
    _TOKEASE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
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
_KEY_TITLE_WEEKLY = "title_weekly"

# File written by the Claude Code statusline capture script
# (statusline/tokease-statusline.py). Read on every refresh in statusline mode.
_STATUSLINE_FILE = _TOKEASE_DIR / "usage.json"

# Quota history sampled (~5 min) by the Claude desktop app. Read-only
# secondary source, undocumented internal format (see ADR 0003).
_DESKTOP_HISTORY_FILE = (
    Path.home() / "Library" / "Application Support" / "Claude" / "plan-usage-history.json"
)

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
# Helpers
# ---------------------------------------------------------------------------

def _safe_int(val, default=0):
    """Convert an API value to a clamped non-negative int, never crash."""
    try:
        return max(0, int(float(val))) if val is not None else default
    except (ValueError, TypeError, OverflowError):
        # OverflowError: a hostile feed can return an overflowing number
        # (e.g. 1e400 → inf); int(inf) would otherwise raise outside the
        # refresh's try block.
        return default


def _epoch_to_iso(value):
    """Normalize `resets_at` (statusline) into the ISO string fmt_reset reads.

    The format varies with the Claude Code version (see anthropics/claude-code
    #40094): either an epoch in seconds, or already an ISO string. We tolerate
    both; any uninterpretable value → None (the countdown shows '--').
    """
    try:
        return datetime.fromtimestamp(float(value), timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        # Not a numeric epoch → maybe already a valid ISO string.
        if isinstance(value, str) and _parse_iso(value) is not None:
            return value.strip()
        return None

# ---------------------------------------------------------------------------
# Data fetching — statusline (primary) + Claude desktop app (secondary)
# ---------------------------------------------------------------------------

def _read_statusline_usage():
    """Read the usage captured by the Claude Code statusline script.

    Normalizes into the shape _update_display expects (used_percentage→
    utilization, epoch→ISO) and tags _meta. Error codes: 'nostatusline'
    (file missing → not wired yet), 'waiting' (file present but no
    rate_limits captured), 'error' (unreadable / invalid).
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
    data["_meta"] = {"captured_at": payload.get("captured_at"), "source": "statusline"}
    return data, None


def _is_number(value):
    """Strict int/float — excludes bool (JSON true/false would pass isinstance int)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _desktop_sample_to_data(sample):
    """Normalize a desktop sample {t: epoch ms, u: {fh, sd}}; None when malformed."""
    if not isinstance(sample, dict):
        return None
    t, u = sample.get("t"), sample.get("u")
    if not _is_number(t) or not isinstance(u, dict):
        return None
    data = {}
    for src, dst in (("fh", "five_hour"), ("sd", "seven_day")):
        if _is_number(u.get(src)):
            data[dst] = {"utilization": u[src], "resets_at": None}
    if not data:
        return None
    data["_meta"] = {"captured_at": t / 1000.0, "source": "desktop"}
    return data


def _read_desktop_usage():
    """Read the latest quota sample written by the Claude desktop app.

    Undocumented internal format (ADR 0003) → ultra-defensive parsing: any
    anomaly (missing file, unknown version, malformed sample) returns None
    and we fall back to the statusline. This feed has no resets_at.
    """
    try:
        payload = json.loads(_DESKTOP_HISTORY_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("version") != 2:
        return None
    samples = payload.get("samples")
    if not isinstance(samples, list):
        return None
    for sample in reversed(samples):  # samples are in chronological order
        data = _desktop_sample_to_data(sample)
        if data is not None:
            return data
    return None


def _captured_at(data):
    """Capture epoch of a normalized source; 0.0 when absent/invalid."""
    try:
        return float(data.get("_meta", {}).get("captured_at") or 0)
    except (TypeError, ValueError):
        return 0.0


def _merge_window(sl_win, desk_win, desk_at, sl_fresh, now):
    """Merge ONE window: desktop % + statusline resets_at, honestly.

    - statusline resets_at kept only when it is still in the future;
    - reset happened AFTER the desktop sample → its % describes the old window:
      return the statusline version, which _window_row shows as "— (reset;
      awaiting Claude Code)" rather than a plausible old %;
    - window missing from the desktop feed → reuse the statusline one only if
      its capture is not stale (otherwise old data would show up under a
      perfectly fresh "Updated" line).
    """
    if desk_win is None:
        return sl_win if (sl_win and sl_fresh) else None
    win = dict(desk_win)
    reset = (sl_win or {}).get("resets_at")
    dt = _parse_iso(reset)
    if dt is not None:
        if dt > now:
            win["resets_at"] = reset
        elif desk_at <= dt.timestamp():
            return sl_win  # sample predates the reset → old window
    return win


def _merge_usage(statusline, desktop):
    """Merge the two sources: the fresher one's percentages win
    (per-window honesty guards: see _merge_window)."""
    sl_at = _captured_at(statusline)
    desk_at = _captured_at(desktop)
    if desk_at <= sl_at:
        return statusline
    now = datetime.now(timezone.utc)
    sl_fresh = (now.timestamp() - sl_at) <= _STALE_AFTER_SECS
    merged = {"_meta": desktop["_meta"]}
    for key in ("five_hour", "seven_day"):
        win = _merge_window(statusline.get(key), desktop.get(key), desk_at, sl_fresh, now)
        if win is not None:
            merged[key] = win
    return merged


def fetch_usage():
    """Primary source: statusline. Secondary: desktop app (ADR 0003).

    The desktop fills the statusline's gaps (VS Code extension, Claude.ai…)
    and removes any mandatory config: desktop app running = data displayed,
    even without a wired statusline.
    """
    statusline, err = _read_statusline_usage()
    desktop = _read_desktop_usage()
    if desktop is None:
        return statusline, err
    if statusline is None:
        return desktop, None
    return _merge_usage(statusline, desktop), None


# ---------------------------------------------------------------------------
# Time formatting
# ---------------------------------------------------------------------------

def _parse_iso(iso):
    """Parse an ISO-8601 timestamp (from _epoch_to_iso) into a tz-aware datetime.

    Returns None for an empty, non-str or malformed input — every parsing
    exception is caught, never propagated. Centralized here so callers that
    need the raw datetime (reset scheduling) don't duplicate the Python
    normalization `fmt_reset` already does.
    """
    if not iso or not isinstance(iso, str):
        return None
    try:
        clean = iso.strip()
        # "Z" → explicit UTC offset (fromisoformat only accepts "Z" from 3.11 on)
        if clean.endswith("Z"):
            clean = clean[:-1] + "+00:00"
        # Strip sub-seconds (3.10 is strict about the digit count) while
        # preserving the colon offset ±HH:MM, which 3.10 requires (it rejects ±HHMM).
        if "." in clean:
            head, _, tail = clean.partition(".")
            off = ""
            for sign in ("+", "-"):
                idx = tail.find(sign)
                if idx != -1:
                    off = tail[idx:]
                    break
            clean = head + off
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, OverflowError, TypeError):
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
        self.title_weekly = bool(_settings_get(_KEY_TITLE_WEEKLY, False))

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
        # Toggle independent from the radio group: composes with both/pct (no
        # visible effect in icon mode, whose 2 rings already show the weekly).
        self.m_weekly = rumps.MenuItem(
            "Add weekly % (5h / weekly)", callback=self._toggle_title_weekly,
        )
        self.m_weekly.state = 1 if self.title_weekly else 0
        display_menu.add(self.m_weekly)
        self._update_display_menu()

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
        settings_menu.add(self.m_alerts)
        settings_menu.add(interval_menu)

        # --- Support submenu --------------------------------------------
        support_menu = rumps.MenuItem("Support")
        support_menu.add(rumps.MenuItem("Star on GitHub", callback=self._open_star))
        support_menu.add(rumps.MenuItem("Sponsor / Donate", callback=self._open_donate))

        self.menu = [
            self.m5h, self.m7d, None,
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

    def _toggle_title_weekly(self, sender):
        self.title_weekly = not self.title_weekly
        _settings_set(_KEY_TITLE_WEEKLY, self.title_weekly)
        sender.state = 1 if self.title_weekly else 0
        # Immediate re-render, like _set_display_mode.
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
        for key in ("five_hour", "seven_day"):
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
            data, err = fetch_usage()
        except Exception as exc:  # worker thread must never die silently, else the menu freezes on "..."
            print(f"tokease: unexpected fetch error: {exc!r}", file=sys.stderr)
            data, err = None, "error"
        # Marshal back to the main thread before touching menu items or icon —
        # mutating NSStatusItem off the main thread eventually trips an AppKit
        # assertion and SIGABRTs the app (latent crash on long-running installs).
        _call_on_main(self._apply_usage, data, err)

    def _apply_usage(self, data, err):
        # Error states always display their text whatever the display mode —
        # the user must see *why* the numbers aren't moving.
        if err or not data:
            # Clear any stale ring icon so it doesn't contradict the error
            # glyph (in ICON mode the title is empty → a frozen ring misleads).
            self.icon = None

        if err == "nostatusline":
            # No source available (neither desktop nor statusline). Zero-config
            # path first, statusline wiring second.
            self.title = "⚙"
            self.m5h.title = "Easiest: open the Claude desktop app (auto-detected)"
            self.m7d.title = "Or wire the CLI: run statusline/install-statusline.sh"
            self.mupd.title = "then message in Claude Code (Pro or Max plan required)"
            return

        if err == "waiting":
            # File present but Claude Code hasn't reported rate_limits yet
            # (it only appears after the first API response of a session,
            # and never on Free or Team/Enterprise plans).
            self.title = "…"
            self.m5h.title = "Waiting for Claude Code activity…"
            self.m7d.title = "Quota data only exists on Pro or Max plans"
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
    def _window_row(label, section, now):
        """Format one usage-window line → (text, pct_for_ring).

        pct_for_ring is None when the window already reset since the capture:
        the stored % is no longer valid, so the caller skips that ring and
        shows '—' rather than a stale number.
        """
        # Clamp 0..100 at the source: the feed can return an aberrant % at
        # startup (Claude Code bug #52326) — otherwise it leaks into the
        # dropdown menu line and the notification (not just the title/icon).
        pct = min(100, _safe_int(section.get("utilization")))
        dt = _parse_iso(section.get("resets_at"))
        if dt is not None and dt <= now:
            return f"{label}: — (reset; awaiting Claude Code)", None
        return f"{label}: {pct}% (resets {fmt_reset(section.get('resets_at'))})", pct

    @staticmethod
    def _freshness_label(captured_at, now, source=None):
        """'Updated' line, flagging stale data (no Claude client refreshing it)."""
        if not captured_at:
            return UPDATED_DEFAULT
        try:
            cap = datetime.fromtimestamp(float(captured_at), timezone.utc)
            local = cap.astimezone().strftime("%H:%M")
        except (TypeError, ValueError, OverflowError, OSError):
            return UPDATED_DEFAULT
        age = (now - cap).total_seconds()
        via = "Claude app" if source == "desktop" else "Claude Code"
        if age > _STALE_AFTER_SECS:
            return f"⚠ {local} · stale {int(age // 60)}m ({via} idle?)"
        return f"Updated: {local} (via {via})"

    def _update_display(self, data):
        now = datetime.now(timezone.utc)
        meta = data.get("_meta", {})
        session_pct = weekly_pct = None  # None = window absent → "—" badge/ring, not "0%"

        # 5h session (also drives the menu bar title and the threshold alerts)
        if h := data.get("five_hour"):
            self.m5h.title, session_pct = self._window_row("5-hour", h, now)
            if session_pct is not None:
                self._maybe_notify(session_pct)
        else:
            self.m5h.title = FIVE_HOUR_DEFAULT

        # 7-day weekly window
        if d := data.get("seven_day"):
            self.m7d.title, weekly_pct = self._window_row("Weekly", d, now)
        else:
            self.m7d.title = WEEKLY_DEFAULT

        self.mupd.title = self._freshness_label(
            meta.get("captured_at"), now, meta.get("source")
        )

        # % already clamped 0..100 in _window_row (see bug #52326).
        icon_path = _render_dynamic_icon(session_pct, weekly_pct)
        title_pct = f"{session_pct}%" if session_pct is not None else "—"
        if self.title_weekly:
            weekly_txt = f"{weekly_pct}%" if weekly_pct is not None else "—"
            title_pct = f"{title_pct} / {weekly_txt}"
        self._apply_display(title_pct, icon_path)

        self._schedule_reset_refresh(data)


if __name__ == "__main__":
    App().run()
