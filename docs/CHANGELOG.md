# Changelog

## v1.0.0 — Native App Release (2026-03-06)

### Core Tracker
- macOS menu bar app showing Claude Code usage in real time
- Tracks 5-hour session, weekly, Sonnet weekly, and extra (paid overage) limits
- Reads OAuth token from macOS Keychain — zero config needed
- Auto-refresh with configurable interval (1min / 5min / 30min / 1hr)
- Security: token cleared after use, HTTP redirects blocked, no data collection

### Native .app Bundle
- **New:** `setup.py` — py2app configuration to build a standalone macOS `.app`
- **New:** `build.sh` — one-command build script producing `Tokease.app`
- **New:** `assets/icon.icns` — app icon (purple gradient with usage meter bars)
- App runs as menu bar-only (no Dock icon) via `LSUIElement`
- Distributable as `.dmg` disk image (19MB)

### Distribution Model
- **Free:** open source repo — clone and run `tracker.py` from source
- **Paid (5-10 EUR):** pre-built `.app` download — drag to Applications, done

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
Single-file app (`tracker.py`, ~330 lines) with one dependency (`rumps`).

Key components:
- `get_usage()` — reads Keychain token, calls Anthropic OAuth usage API
- `App` class — rumps menu bar app with timer-based refresh
- `_NoRedirectHandler` — blocks HTTP redirects to prevent token leakage
- `fmt_reset()` — converts ISO timestamps to human-readable countdowns
