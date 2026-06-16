# Changelog

## v1.0.0 — Token-free, statusline-only

### Breaking
- **Removed the legacy endpoint mode entirely.** v1.0 no longer reads the OAuth token from the Keychain and no longer calls Anthropic's usage endpoint. The full endpoint implementation is preserved at the git tag `v0.9.0-endpoint` for reference.

### The only data source is now the Claude Code statusline
- Tokease reads the `rate_limits` data Claude Code itself publishes to its statusline (a documented field), written locally to `~/.tokease/usage.json` by the capture script.
- **Reads no token, makes no API call of its own** — compliant with Anthropic's Terms by construction (other trackers read the Keychain; Tokease never does).

### UI
- **Two rings** — 5-hour session (outer) + weekly (inner), with reset countdowns. Amber at 80%, red at 95%.
- Removed the Sonnet/Opus per-model split and the paid-overage line (those were endpoint-only data).
- **Honest freshness** — flags data *stale* when Claude Code isn't running, and detects reset windows that have already rolled over.

### Requirements
- Claude Code ≥ 2.1.x (statusline `rate_limits`), Claude Pro or Max (Free / Team / Enterprise not supported).

### Notes
- A small single-file menu bar app, MIT, no telemetry, no account. Two dependencies: `rumps` + `Pillow`.

---

## v0.9.0 — Endpoint mode (legacy, frozen at tag `v0.9.0-endpoint`)

> This release read the OAuth token and called the usage endpoint directly. It is no
> longer shipped (see v1.0.0 above) and is kept only for historical reference.

### Core Tracker
- macOS menu bar app showing Claude Code usage in real time
- Tracks 5-hour session, weekly, Sonnet weekly, and extra (paid overage) limits
- Reads OAuth token from macOS Keychain
- Auto-refresh with configurable interval (1min / 5min / 30min / 1hr)
- Security: token cleared after use, HTTP redirects blocked, no data collection

### Native .app Bundle
- **New:** `setup.py` — py2app configuration to build a standalone macOS `.app`
- **New:** `build.sh` — one-command build script producing `Tokease.app`
- **New:** `assets/icon.icns` — app icon (purple gradient with usage meter bars)
- App runs as menu bar-only (no Dock icon) via `LSUIElement`
- Distributable as `.dmg` disk image (19MB)

### Distribution Model
- Free and open source (MIT) — clone and run `tracker.py`, or install via Homebrew
- No paid tier, no premium features held back: the Homebrew build is identical to the source

### Landing Page
- `docs/index.html` — dark-themed landing page with features, install steps, privacy section
- macOS menu bar mockup in the hero section
- Copy-to-clipboard install command

### Project Infrastructure
- `install.sh` — automated setup with venv, dependencies, optional LaunchAgent
- `tests/` — unit tests covering token retrieval, API parsing, time formatting, display logic
- MIT License
- SonarCloud integration for code quality

### Architecture
Single-file app (`tracker.py`) with two small dependencies (`rumps` + `Pillow`).

Key components:
- `get_usage()` — reads Keychain token, calls Anthropic OAuth usage API
- `App` class — rumps menu bar app with timer-based refresh
- `_NoRedirectHandler` — blocks HTTP redirects to prevent token leakage
- `fmt_reset()` — converts ISO timestamps to human-readable countdowns
