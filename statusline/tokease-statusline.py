#!/usr/bin/env python3
"""
Tokease — Claude Code statusline capture script.

Claude Code (>= 2.1.x) pipes session JSON on stdin to whatever command is
configured as `statusLine.command` in settings.json. For Pro/Max subscribers
that JSON includes `rate_limits.five_hour` / `.seven_day` (used_percentage +
resets_at, epoch seconds). This script captures those windows to
~/.tokease/usage.json so the Tokease menu bar app can render them — without
ever reading the OAuth token or calling Anthropic's endpoint itself.

The data is handed to us BY Claude Code, so this stays within the authorized
"use with Claude Code" scope (see docs/adr/0001-pivot-source-statusline.md).

Wiring:
  - No existing statusline → point settings.json statusLine.command here:
        python3 ~/.tokease/tokease-statusline.py
  - Existing statusline → paste the 3-line snippet from statusline/README.md
    at the top of your own script instead.

This script must NEVER raise: a crash would garble Claude Code's status bar.
Errors are logged to ~/.tokease/statusline.err (never silently masked) and the
script still exits 0.
"""

import json
import os
import sys
import time
from pathlib import Path

_DIR = Path.home() / ".tokease"
_OUT = _DIR / "usage.json"
_ERR = _DIR / "statusline.err"
_SCHEMA = 1


def _ensure_dir():
    """Create ~/.tokease with mode 0700 — usage is private data, not readable
    by other local accounts (chmod tightens it even if the dir pre-existed)."""
    _DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        _DIR.chmod(0o700)
    except OSError:
        pass


def _log_error(msg):
    """Record an error without crashing Claude Code's statusline."""
    try:
        _ensure_dir()
        with open(_ERR, "a", encoding="utf-8") as fh:
            fh.write(f"{int(time.time())} {msg}\n")
    except OSError:
        pass  # last-resort: even logging failed; nothing safe left to do


def _extract_window(rate_limits, key):
    """Return {'used_percentage', 'resets_at'} for a window, or None if absent/invalid."""
    win = rate_limits.get(key)
    if not isinstance(win, dict):
        return None
    pct = win.get("used_percentage")
    if pct is None:
        return None
    out = {"used_percentage": pct}
    if win.get("resets_at") is not None:
        out["resets_at"] = win.get("resets_at")
    return out


def _has_window(payload):
    """True when the payload carries at least one usable usage window."""
    return isinstance(payload, dict) and any(
        payload.get(key) for key in ("five_hour", "seven_day")
    )


def _read_current():
    """Current usage.json, or {} when absent/unreadable. Never raises."""
    try:
        with open(_OUT, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _atomic_write(payload):
    """Write JSON atomically (temp in same dir + os.replace) so the reader
    never sees a partially-written file. Cleans up the temp file on failure
    instead of leaking a .usage.<pid>.tmp behind."""
    _ensure_dir()
    tmp = _DIR / f".usage.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        os.replace(tmp, _OUT)
    except (OSError, TypeError, ValueError):
        tmp.unlink(missing_ok=True)
        raise


def _render_line(payload):
    """Minimal statusline text for the captured windows ("" when none is usable)."""
    bits = []
    for key, lbl in (("five_hour", "5h"), ("seven_day", "7d")):
        win = payload.get(key)
        if not win:
            continue
        try:  # a non-numeric % must not wipe out the whole output
            bits.append(f"{lbl} {int(float(win['used_percentage']))}%")
        except (KeyError, TypeError, ValueError):
            pass
    return "⛁ " + " · ".join(bits) if bits else ""


def main():
    raw = sys.stdin.read()
    try:
        data = json.loads(raw) if raw.strip() else {}
    except ValueError as exc:  # JSONDecodeError derives from ValueError
        _log_error(f"stdin not JSON: {exc!r}")
        return  # don't overwrite a good file with garbage

    rate_limits = data.get("rate_limits")
    payload = {
        "schema": _SCHEMA,
        "captured_at": int(time.time()),
        "source": "claude-code-statusline",
    }
    if isinstance(rate_limits, dict):
        for key in ("five_hour", "seven_day"):
            win = _extract_window(rate_limits, key)
            if win is not None:
                payload[key] = win

    # Claude Code renders the statusline before it has any rate_limits to hand
    # over (session start, /clear, resume). Writing then would replace good
    # windows with an empty capture and the app would fall back to "Waiting".
    # Keep the previous reading instead — the app already flags it as stale.
    if _has_window(payload) or not _has_window(_read_current()):
        try:
            _atomic_write(payload)
        except OSError as exc:
            _log_error(f"write failed: {exc!r}")

    # Minimal statusline output (suppressed when used as a snippet, or via env).
    if os.environ.get("TOKEASE_STATUSLINE_QUIET"):
        return
    sys.stdout.write(_render_line(payload))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # absolute backstop: never crash Claude Code's statusline
        _log_error(f"unexpected: {exc!r}")
    sys.exit(0)
