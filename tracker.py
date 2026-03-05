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
    # --- Step 1: read token from Keychain -----------------------------------
    token = None
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
        creds = json.loads(result.stdout.strip())
        token = creds.get("claudeAiOauth", {}).get("accessToken")
        # Immediately clear the full credentials blob from this frame
        del result, creds
        if not token:
            return None, "auth"
    except subprocess.TimeoutExpired:
        return None, "error"
    except (OSError, json.JSONDecodeError):
        return None, "error"

    # --- Step 2: call the usage API ----------------------------------------
    req = None
    try:
        req = urllib.request.Request(
            "https://api.anthropic.com/api/oauth/usage",
            headers={
                "Authorization": f"Bearer {token}",
                # Required header for this beta endpoint
                "anthropic-beta": "oauth-2025-04-20",
                # Matches Claude Code's own UA; required by the undocumented endpoint
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
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        return None, "error"
    finally:
        # Clear token and request object (which holds the Authorization header)
        # from the local frame so they can't leak through tracebacks.
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
        rumps.Timer(lambda _: self._apply_usage(data, err), 0).start()

    def _apply_usage(self, data, err):
        if err == "auth":
            self.title = "↩ Login"
            self.m5h.title  = "Run: claude login"
            self.m7d.title  = "Weekly: --"
            self.mson.title = "Sonnet: --"
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

    def _update_display(self, data):
        # 5-hour session
        if h := data.get("five_hour"):
            p = _safe_int(h.get("utilization"))
            self.title     = f"{p}%"
            self.m5h.title = f"5-hour: {p}% (resets {fmt_reset(h.get('resets_at'))})"
        else:
            self.title     = "0%"
            self.m5h.title = "5-hour: --"

        # 7-day
        if d := data.get("seven_day"):
            self.m7d.title = (
                f"Weekly: {_safe_int(d.get('utilization'))}%"
                f" (resets {fmt_reset(d.get('resets_at'))})"
            )
        else:
            self.m7d.title = "Weekly: --"

        # Sonnet weekly
        if s := data.get("seven_day_sonnet"):
            self.mson.title = (
                f"Sonnet: {_safe_int(s.get('utilization'))}%"
                f" (resets {fmt_reset(s.get('resets_at'))})"
            )
        else:
            self.mson.title = "Sonnet: --"

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
