#!/usr/bin/env python3
"""
Claude Usage Tracker — macOS menu bar app.

Data flow:
  1. Read Claude Code's OAuth token from macOS Keychain
     (entry "Claude Code-credentials", written by `claude login`)
  2. Call https://api.anthropic.com/api/oauth/usage with Bearer auth
  3. Display utilization % and reset countdowns in the menu bar

Security notes:
  - Token is read into a local variable, used once, then cleared — never
    stored as an instance attribute or logged anywhere. The full credentials
    blob (`creds`, `result.stdout`) is also deleted before the HTTP call.
  - HTTP redirects are blocked: a custom NoRedirectHandler prevents urllib
    from following 3xx responses, which would resend the Bearer token to
    an arbitrary domain.
  - Specific exception types are caught; bare `except:` is never used so
    KeyboardInterrupt / SystemExit propagate normally.
  - HTTP 401/403/429 are detected explicitly for clear user feedback.
  - No external dependencies beyond `rumps`; stdlib `urllib` handles HTTP.
  - The User-Agent matches what Claude Code itself sends because this
    undocumented beta endpoint appears to require it. Authentication is
    handled entirely by the Bearer token.
"""

import json
import re
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import rumps

# Pillow is used for the dynamic ring icon; gracefully no-op when absent so
# a source install without Pillow still works (falls back to the static icon).
try:
    from PIL import Image, ImageDraw
    _PILLOW_AVAILABLE = True
except ImportError:
    _PILLOW_AVAILABLE = False

# Resolves both from source (repo root + assets/) and from the py2app bundle
# (Resources/assets/) — DATA_FILES in setup.py places it under Resources/assets.
_ICON_PATH = Path(__file__).resolve().parent / "assets" / "menubar-template.png"

# Dynamic-icon rendering: rewritten on every refresh, lives in tempdir so it
# never mutates the bundled assets and gets cleaned by macOS periodically.
_DYNAMIC_ICON_PATH = Path(tempfile.gettempdir()) / "claude-usage-tracker-icon.png"

# Icon geometry — must stay consistent with assets/build-menubar-icon.py so
# the dynamic and fallback static icons have the same visual footprint.
_ICON_SIZE_FINAL = 44
_ICON_SCALE = 4
_ICON_SIZE = _ICON_SIZE_FINAL * _ICON_SCALE
_RING_RADII = (20, 14, 8)      # outer, middle, inner (at final scale)
_RING_STROKE = 3                # final-scale stroke width
_TRACK_ALPHA = 70               # faint background ring so 0% still shows


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

# Default menu item text (extracted to avoid string duplication)
FIVE_HOUR_DEFAULT = "5-hour: --"
WEEKLY_DEFAULT = "Weekly: --"
SONNET_DEFAULT = "Sonnet: --"
OPUS_DEFAULT = "Opus: --"
EXTRA_DEFAULT = "Extra: --"

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

_user_agent = _detect_claude_code_ua()

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
            ["security", "find-generic-password",
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
                "User-Agent": _user_agent,
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
    except (json.JSONDecodeError, OSError):
        return None, "error"
    finally:
        token = None
        req = None


# ---------------------------------------------------------------------------
# Time formatting
# ---------------------------------------------------------------------------

def fmt_reset(iso):
    """Format an ISO timestamp into a human-readable countdown."""
    if not iso:
        return "--"
    try:
        # Normalise: strip sub-seconds, handle "Z" suffix, fix colon in offset
        clean = iso.replace("Z", "+00:00").split(".")[0]
        # Python <3.11 fromisoformat doesn't accept "+00:00", needs "+0000"
        if len(clean) >= 6 and clean[-3] == ":" and clean[-6] in ("+", "-"):
            clean = clean[:-3] + clean[-2:]
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        diff = dt - datetime.now(timezone.utc)
        if diff.total_seconds() < 0:
            return "now"
        if diff.days == 0:
            h = diff.seconds // 3600
            m = (diff.seconds % 3600) // 60
            return f"{h}h {m}m" if h else f"{m}m"
        return dt.strftime("%b %d")
    except (ValueError, OverflowError, IndexError):
        return "?"


# ---------------------------------------------------------------------------
# Menu bar application
# ---------------------------------------------------------------------------

class App(rumps.App):

    def __init__(self):
        # template=True lets macOS auto-invert the icon for dark mode.
        # Pass the icon path only if it exists — a missing asset shouldn't
        # crash the app, just fall back to text-only menu bar.
        icon = str(_ICON_PATH) if _ICON_PATH.exists() else None
        super().__init__(
            "Claude", title="...", icon=icon, template=True, quit_button=None,
        )
        self.interval = 300  # default: 5 minutes
        self._timer = None

        # Notification state: None = no baseline yet (first observation).
        # Tracked in-memory only; resets on restart.
        self.alerts_enabled = True
        self._last_pct = None

        # Usage display items
        self.m5h   = rumps.MenuItem("5-hour: ...")
        self.m7d   = rumps.MenuItem("Weekly: ...")
        self.mson  = rumps.MenuItem("Sonnet: ...")
        self.mopus = rumps.MenuItem("Opus: ...")
        self.mext  = rumps.MenuItem(EXTRA_DEFAULT)
        self.mupd  = rumps.MenuItem("Updated: --")

        # Notification toggle
        self.m_alerts = rumps.MenuItem(
            f"Alert at {NOTIFY_THRESHOLDS[0]}% / {NOTIFY_THRESHOLDS[1]}%",
            callback=self._toggle_alerts,
        )
        self.m_alerts.state = 1 if self.alerts_enabled else 0

        # Interval submenu
        interval_menu = rumps.MenuItem("Refresh Interval")
        self._interval_items = {}   # secs → MenuItem
        self._item_to_secs = {}     # MenuItem title → secs
        for label, secs in INTERVALS.items():
            item = rumps.MenuItem(label, callback=self._set_interval)
            self._interval_items[secs] = item
            self._item_to_secs[label] = secs
            interval_menu.add(item)

        self.menu = [
            self.m5h, self.m7d, self.mson, self.mopus, None,
            self.mext, None,
            self.mupd,
            rumps.MenuItem("Refresh", callback=self._refresh),
            None,
            self.m_alerts,
            interval_menu, None,
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

    def _set_interval(self, sender):
        self.interval = self._item_to_secs[sender.title]
        self._update_interval_menu()
        self._start_timer()

    def _toggle_alerts(self, sender):
        self.alerts_enabled = not self.alerts_enabled
        sender.state = 1 if self.alerts_enabled else 0

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
                title="Claude Usage Tracker",
                subtitle=f"Session at {pct}%",
                message=f"You've passed {threshold}% of your 5-hour limit.",
            )
        except Exception:
            # rumps.notification requires a signed bundle on recent macOS —
            # silently no-op when running from source so dev never breaks.
            pass

    def _start_timer(self):
        if self._timer:
            self._timer.stop()
        self._timer = rumps.Timer(lambda _: self._refresh(None), self.interval)
        self._timer.start()

    # ------------------------------------------------------------------
    # Data refresh
    # ------------------------------------------------------------------

    def _refresh(self, _):
        self.title = "..."
        threading.Thread(target=self._fetch_and_update, daemon=True).start()

    def _fetch_and_update(self):
        data, err = get_usage()
        self._apply_usage(data, err)

    def _apply_usage(self, data, err):
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

        if err or not data:
            self.title = "?"
            return

        self._update_display(data)

    @staticmethod
    def _fmt_utilization(label, section):
        """Format a utilization section as 'Label: N% (resets ...)'."""
        pct = _safe_int(section.get("utilization"))
        return f"{label}: {pct}% (resets {fmt_reset(section.get('resets_at'))})", pct

    def _update_display(self, data):
        session_pct = weekly_pct = sonnet_pct = opus_pct = 0

        # 5-hour session (also drives the menu bar title and threshold alerts)
        if h := data.get("five_hour"):
            text, session_pct = self._fmt_utilization("5-hour", h)
            self.title = f"{session_pct}%"
            self.m5h.title = text
            self._maybe_notify(session_pct)
        else:
            self.title = "0%"
            self.m5h.title = FIVE_HOUR_DEFAULT

        # 7-day
        if d := data.get("seven_day"):
            self.m7d.title, weekly_pct = self._fmt_utilization("Weekly", d)
        else:
            self.m7d.title = WEEKLY_DEFAULT

        # Sonnet weekly
        if s := data.get("seven_day_sonnet"):
            self.mson.title, sonnet_pct = self._fmt_utilization("Sonnet", s)
        else:
            self.mson.title = SONNET_DEFAULT

        # Opus weekly
        if o := data.get("seven_day_opus"):
            self.mopus.title, opus_pct = self._fmt_utilization("Opus", o)
        else:
            self.mopus.title = OPUS_DEFAULT

        # Inner ring = whichever per-model metric is more saturated, so the
        # icon surfaces the model the user is most at risk of capping out on.
        dyn = _render_dynamic_icon(session_pct, weekly_pct, max(sonnet_pct, opus_pct))
        if dyn is not None:
            self.icon = str(dyn)

        # Extra (paid overage)
        e = data.get("extra_usage")
        if isinstance(e, dict) and e.get("is_enabled"):
            used  = _safe_int(e.get("used_credits")) / CENTS_PER_DOLLAR
            limit = _safe_int(e.get("monthly_limit")) / CENTS_PER_DOLLAR
            pct   = _safe_int(e.get("utilization"))
            self.mext.title = f"Extra: ${used:.2f}/${limit:.0f} ({pct}%)"
        else:
            self.mext.title = EXTRA_DEFAULT

        self.mupd.title = f"Updated: {datetime.now().strftime('%H:%M')}"


if __name__ == "__main__":
    App().run()
