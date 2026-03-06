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
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone

import rumps

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

# Default menu item text (extracted to avoid string duplication)
FIVE_HOUR_DEFAULT = "5-hour: --"
WEEKLY_DEFAULT = "Weekly: --"
SONNET_DEFAULT = "Sonnet: --"
EXTRA_DEFAULT = "Extra: --"

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
                "User-Agent": "claude-code/2.1.34",
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
            return None, "rate"
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
        super().__init__("Claude", title="...", quit_button=None)
        self.interval = 300  # default: 5 minutes
        self._timer = None

        # Usage display items
        self.m5h  = rumps.MenuItem("5-hour: ...")
        self.m7d  = rumps.MenuItem("Weekly: ...")
        self.mson = rumps.MenuItem("Sonnet: ...")
        self.mext = rumps.MenuItem(EXTRA_DEFAULT)
        self.mupd = rumps.MenuItem("Updated: --")

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
            self.m5h, self.m7d, self.mson, None,
            self.mext, None,
            self.mupd,
            rumps.MenuItem("Refresh", callback=self._refresh),
            None,
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
            self.m5h.title  = "Run: claude login"
            self.m7d.title  = WEEKLY_DEFAULT
            self.mson.title = SONNET_DEFAULT
            self.mext.title = EXTRA_DEFAULT
            return

        if err == "rate":
            self.title = "⏳"
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
        # 5-hour session (also drives the menu bar title)
        if h := data.get("five_hour"):
            text, pct = self._fmt_utilization("5-hour", h)
            self.title = f"{pct}%"
            self.m5h.title = text
        else:
            self.title = "0%"
            self.m5h.title = FIVE_HOUR_DEFAULT

        # 7-day
        if d := data.get("seven_day"):
            self.m7d.title, _ = self._fmt_utilization("Weekly", d)
        else:
            self.m7d.title = WEEKLY_DEFAULT

        # Sonnet weekly
        if s := data.get("seven_day_sonnet"):
            self.mson.title, _ = self._fmt_utilization("Sonnet", s)
        else:
            self.mson.title = SONNET_DEFAULT

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
