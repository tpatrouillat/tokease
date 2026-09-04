# Changelog

## Unreleased

### Fixed

- A stale reading no longer looks live in the menu bar: past the freshness threshold the percentage is prefixed with `~` (`~26%`). Before this, only the dropdown flagged it, and the number is what you actually read.
- The freshness threshold moves from 15 to 20 minutes. Measured over a month of desktop samples the app's cadence is 5 or 15 minutes, so 15 flagged normal operation as stale about 15 % of the time.
- A partial statusline capture no longer wipes a window it doesn't carry. A capture with only the weekly window used to blank the 5-hour reading until the next desktop sample. The desktop value now fills the gap, unless it is itself stale.
- A reading is now void once it outlives the window it describes. A 5-hour percentage older than 5 hours, or a weekly one older than 7 days, describes a window that has certainly ended, so the app shows `—` instead of a number nothing supports. This is what an app left running over a weekend used to get wrong.
- A new window raises its own alert again. A window carries its own reset time, so a reset time never seen before starts the alert baseline back at 0. Before this, a window opening below the previous window's peak never looked like a threshold crossing and its alert was lost.
- A merged reading dates itself from its oldest part. When a partial capture is completed from the desktop feed, the freshness line and the `~` marker now describe the filled window rather than the capture that triggered the merge.
- A threshold no longer alerts twice around a reset. Desktop readings carry no reset time, so after a reset the app tracked the new window while still naming the old one, and the reset time arriving later with the next capture made that same window look brand new. Only a reset time later than the one on file now marks a new window.
- The freshness line reads in hours and days rather than `stale 4320m`, and names the desktop when the time shown is a desktop sample.
- A title showing no number is no longer marked stale. Marking a lone dash said nothing.
- The capture script no longer re-dates an unchanged reading. Claude Code re-runs the statusline on events that carry no new measurement, and each re-run used to look like a fresh one, which let old values outrank a truer desktop sample and could fire the same threshold alert twice.
- The capture script keeps the measurement's timestamp when a window vanished at its reset. Claude Code drops a window once its reset time passes and re-runs the statusline with the other window unchanged. That capture used to be dated anew, so a weekly value hours old looked fresh and outranked a truer desktop sample.
- A reading whose capture time is missing or unreadable is marked stale rather than shown as live. The dropdown says the time is unknown. Only a hand-edited file could produce this, and an unknown age is not a fresh one.
- A failure to write the ring icon (full disk, read-only or deleted `~/.tokease`) no longer leaves the menu bar stuck on "...". The percentage is still shown and the previous icon is kept.

### Docs

- README and ADR 0003 state the real desktop cadence (5 to 15 minutes, not 5) and the resulting worst-case lag.

## v1.0.2 — Launch-day polish

### Fixed

- `install.sh` no longer starts two copies: the LaunchAgent already launches Tokease on load, so the "Start the tracker now?" prompt is only offered when auto-start was declined. Two running copies meant two identical menu bar icons, and the second survived Quit.
- Removed the "Sponsor / Donate" menu item: GitHub Sponsors isn't set up, so it opened a redirect to a bare profile.
- The Support submenu now shows the version, so a bug report can state which build it is.

### Docs

- `CONTRIBUTING.md` and the PR template no longer ask for `ruff format .`, which would have reformatted the whole codebase on a contributor's first PR. Lint stays `ruff check`.
- Version is consistent across the app bundle, the landing page and the tag.

## v1.0.1 — Reliable statusline capture

### Fixed

- The statusline capture no longer wipes good readings. Claude Code renders the statusline before it has any `rate_limits` to hand over (session start, `/clear`, resume); the script wrote anyway, replacing captured windows with an empty payload, and the app dropped to "Waiting" mid-session. It now keeps the previous reading and lets the app flag it stale on its own schedule. Mainly affected CLI-only users, who don't have the Claude desktop app as a backstop.
- Threshold notifications at 80% / 95% are no longer promised where they can't fire: macOS only delivers notifications for a signed `.app` bundle, so they never appear on a Homebrew or source install. Docs, landing page and the Settings label say so now. The feature stays in the code for the signed `.app` build.

### Docs

- ROADMAP no longer contradicts itself on the zero-network rule and on signed `.app` builds.
- The landing page no longer names other trackers: the argument stands at category level.
- `brew services start tokease` added to every install path — without it the app installs and nothing appears.

## v1.0.0 — Token-free: two local read-only sources

### Breaking

- **Removed the legacy endpoint mode entirely.** v1.0 no longer reads the OAuth token from the Keychain and no longer calls Anthropic's usage endpoint. The full endpoint implementation is preserved at the git tag `v0.9.0-endpoint` for reference.

### Data sources

- **Claude Desktop quota history (zero config).** Reads the local `plan-usage-history.json` the desktop app refreshes about every 5 minutes. Covers every surface (claude.ai, Cowork, VS Code extension, CLI). Defensive parsing pinned to the observed `version: 2`, with the statusline feed as fallback.
- **Claude Code statusline (adds reset countdowns).** A capture script writes the documented `rate_limits` fields to `~/.tokease/usage.json`. This is the only feed with reset times.
- The freshest source wins, with per-window honesty guards: a pre-reset desktop sample never masquerades as the current window, and stale windows are never shown under a fresh "Updated" line.
- **Reads no token, makes no API call of its own.** Compliant by construction (other trackers read the Keychain, Tokease never does).

### UI

- **Two rings**: 5-hour session (outer) and weekly (inner), with reset countdowns. Notification alerts at 80% and 95% (on by default, toggleable in Settings).
- New display option: show both percentages in the menu bar title (`5h / weekly`), off by default.
- Provenance in the dropdown ("via Claude app" / "via Claude Code") and a *stale* flag after 15 minutes without a refresh. Reset windows that already rolled over are detected.
- Removed the Sonnet/Opus per-model split and the paid-overage line (those were endpoint-only data).

### Requirements

- Claude Pro or Max (Free / Team / Enterprise not supported). Claude Desktop running and/or Claude Code ≥ 2.1.x with the statusline wired.

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
