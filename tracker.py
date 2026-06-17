#!/usr/bin/env python3
"""
Tokease — macOS menu bar app.

Source de données UNIQUE : le feed statusline de Claude Code
(voir docs/adr/0001-pivot-source-statusline.md). Claude Code (>= 2.1.x)
transmet `rate_limits.five_hour` / `.seven_day` à son script statusline.
Un script de capture (statusline/tokease-statusline.py) écrit ces fenêtres
dans ~/.tokease/usage.json ; cette app lit ce fichier. La donnée nous est
fournie PAR Claude Code, donc on reste dans le cadre "usage avec Claude Code" :
jamais de lecture du token OAuth, jamais d'appel à l'endpoint Anthropic.

Conséquence : seules les fenêtres 5h et hebdo sont disponibles (2 anneaux).
Le split par modèle (Sonnet/Opus) et l'overage payant ne sont pas dans ce feed.
"""

import json
import os
import subprocess
import sys
import tempfile
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

def _resolve_icon_path():
    """Chemin de l'icône menu bar — depuis les sources (assets/ à côté du script)
    OU depuis le bundle py2app gelé : py2app place DATA_FILES sous Resources/ et
    l'expose via $RESOURCEPATH (Path(__file__) n'y pointe pas une fois gelé)."""
    if getattr(sys, "frozen", False):
        res = os.environ.get("RESOURCEPATH")
        if res:
            return Path(res) / "assets" / "menubar-template.png"
    return Path(__file__).resolve().parent / "assets" / "menubar-template.png"


_ICON_PATH = _resolve_icon_path()

# Dynamic-icon rendering: rewritten on every refresh, lives in tempdir so it
# never mutates the bundled assets and gets cleaned by macOS periodically.
_DYNAMIC_ICON_PATH = Path(tempfile.gettempdir()) / "tokease-icon.png"

# Icon geometry — must stay consistent with assets/build-menubar-icon.py so
# the dynamic and fallback static icons have the same visual footprint.
_ICON_SIZE_FINAL = 44
_ICON_SCALE = 4
_ICON_SIZE = _ICON_SIZE_FINAL * _ICON_SCALE
_RING_RADII = (20, 14)         # externe (5h), interne (hebdo) — à l'échelle finale
_RING_STROKE = 3                # final-scale stroke width
_TRACK_ALPHA = 180              # background ring opacity so 0% reads as an empty "container", not a ghost


def _render_dynamic_icon(session_pct, weekly_pct):
    """
    Dessine l'icône à 2 anneaux remplis selon l'usage courant.

    Anneau externe = % session 5h, anneau interne = % hebdo. Chaque arc part de
    midi et tourne dans le sens horaire ; un anneau plein discret est tracé
    derrière pour que 0% garde un contour visible.

    Renvoie le chemin du PNG fraîchement écrit, ou None si Pillow est absent
    (l'appelant garde alors l'icône statique existante).
    """
    if not _PILLOW_AVAILABLE:
        return None
    img = Image.new("RGBA", (_ICON_SIZE, _ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    center = _ICON_SIZE // 2
    stroke = _RING_STROKE * _ICON_SCALE

    for radius, pct in zip(_RING_RADII, (session_pct, weekly_pct)):
        if pct is None:
            continue  # fenêtre absente/réinitialisée depuis la capture
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

# Tag de la donnée dans _meta — source unique désormais.
SOURCE_STATUSLINE = "statusline"

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
    except (ValueError, TypeError):
        return default


def _epoch_to_iso(value):
    """Normalise `resets_at` (statusline) en string ISO que fmt_reset lit.

    Le format varie selon la version de Claude Code (cf. anthropics/claude-code
    #40094) : soit un epoch en secondes, soit déjà une string ISO. On tolère les
    deux ; toute valeur ininterprétable → None (le compte à rebours affiche '--').
    """
    try:
        return datetime.fromtimestamp(float(value), timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        # Pas un epoch numérique → peut-être déjà une string ISO valide.
        if isinstance(value, str) and _parse_iso(value) is not None:
            return value.strip()
        return None

# ---------------------------------------------------------------------------
# Data fetching — lecture pure du fichier statusline (source unique)
# ---------------------------------------------------------------------------

def fetch_usage():
    """Lit l'usage capturé par le script statusline de Claude Code.

    Normalise vers la forme attendue par _update_display (used_percentage→
    utilization, epoch→ISO) et tague _meta. Codes d'erreur : 'nostatusline'
    (fichier absent → pas encore branché), 'waiting' (fichier présent mais aucun
    rate_limits capturé), 'error' (illisible / invalide).
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
    """Parse un timestamp ISO-8601 (issu de _epoch_to_iso) en datetime tz-aware.

    Renvoie None pour une entrée vide, non-str ou malformée — toutes les
    exceptions de parsing sont rattrapées, jamais propagées. Centralisé ici pour
    que les appelants qui ont besoin du datetime brut (planif. de reset) ne
    dupliquent pas la normalisation Python que `fmt_reset` fait déjà.
    """
    if not iso or not isinstance(iso, str):
        return None
    try:
        clean = iso.strip()
        # "Z" → offset UTC explicite (fromisoformat n'accepte "Z" qu'à partir de 3.11)
        if clean.endswith("Z"):
            clean = clean[:-1] + "+00:00"
        # Strippe les sous-secondes (3.10 est strict sur le nb de chiffres) en
        # préservant l'offset colon ±HH:MM, que 3.10 exige (et rejette ±HHMM).
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
        # Les états d'erreur affichent toujours leur texte quel que soit le mode
        # d'affichage — l'utilisateur doit voir *pourquoi* les chiffres ne bougent pas.
        if err or not data:
            # Efface toute icône d'anneau périmée pour qu'elle ne contredise pas
            # le glyphe d'erreur (en mode ICON le titre est vide → anneau figé trompeur).
            self.icon = None

        if err == "nostatusline":
            # Fichier de capture absent → statusline pas encore branchée. On guide pas-à-pas.
            self.title = "⚙"
            self.m5h.title = "1. lance statusline/install-statusline.sh"
            self.m7d.title = "2. ajoute le bloc à ~/.claude/settings.json"
            self.mupd.title = "3. envoie un message dans Claude Code"
            return

        if err == "waiting":
            # Fichier présent mais Claude Code n'a pas encore remonté rate_limits
            # (n'apparaît qu'après la 1re réponse API d'une session).
            self.title = "…"
            self.m5h.title = "Waiting for Claude Code activity…"
            self.m7d.title = WEEKLY_DEFAULT
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
        """Formate une ligne de fenêtre d'usage → (texte, pct_pour_anneau).

        pct_pour_anneau vaut None quand la fenêtre s'est déjà réinitialisée depuis
        la capture : le % stocké n'est plus valide, donc l'appelant saute cet
        anneau et affiche '—' plutôt qu'un chiffre périmé.
        """
        pct = _safe_int(section.get("utilization"))
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

    def _update_display(self, data):
        now = datetime.now(timezone.utc)
        meta = data.get("_meta", {})
        session_pct = weekly_pct = 0

        # Session 5h (pilote aussi le titre menu bar et les alertes de seuil)
        if h := data.get("five_hour"):
            self.m5h.title, session_pct = self._window_row("5-hour", h, now)
            if session_pct is not None:
                self._maybe_notify(session_pct)
        else:
            self.m5h.title = FIVE_HOUR_DEFAULT

        # Hebdo 7 jours
        if d := data.get("seven_day"):
            self.m7d.title, weekly_pct = self._window_row("Weekly", d, now)
        else:
            self.m7d.title = WEEKLY_DEFAULT

        self.mupd.title = self._freshness_label(meta.get("captured_at"), now)

        # Clamp 0..100 avant le titre et l'icône (le feed peut dépasser 100).
        session_clamped = min(100, session_pct) if session_pct is not None else None
        weekly_clamped = min(100, weekly_pct) if weekly_pct is not None else None
        icon_path = _render_dynamic_icon(session_clamped, weekly_clamped)
        title_pct = f"{session_clamped}%" if session_clamped is not None else "—"
        self._apply_display(title_pct, icon_path)

        self._schedule_reset_refresh(data)


if __name__ == "__main__":
    App().run()
