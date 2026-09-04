<div align="center">
  <img src="assets/logo-256-demo.png" alt="Tokease" width="200" height="200">
  <h1>Tokease</h1>
  <p>A lightweight macOS menu bar app showing your Claude 5-hour and weekly limits<br/><strong>One 967-line Python file, plus a 178-line script. No HTTP client is imported anywhere in it, so you can check what it does before you run it.</strong></p>
  <p>
    <a href="https://github.com/tpatrouillat/tokease/actions/workflows/ci.yml"><img src="https://github.com/tpatrouillat/tokease/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
    <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT">
    <img src="https://img.shields.io/badge/platform-macOS-lightgrey.svg" alt="Platform: macOS">
    <img src="https://img.shields.io/badge/telemetry-none-success.svg" alt="No telemetry">
  </p>
</div>

![Tokease menu bar dropdown showing the Claude 5-hour and weekly limits with reset times](docs/screenshot.png)

```bash
brew install tpatrouillat/tap/tokease
brew services start tokease      # starts it now, and at every login
```

Requires macOS 12 Monterey or later and a Claude Pro or Max plan. Zero config if the Claude desktop app is running. [Other install paths below.](#install-from-source)

## Why Tokease

Tokease reads only two local files: the quota history the Claude desktop app writes on your Mac, and the `rate_limits` data Claude Code hands to its statusline, which the 178-line capture script saves to `~/.tokease`. No OAuth token read from the Keychain, no hidden API call, no User-Agent spoofing.

That is a sentence any tracker can write. What you can actually check is the size. The app is one 967-line Python file, plus a 178-line capture script if you want reset countdowns. The import block at the top of [`tracker.py`](tracker.py) is the whole dependency story, and there is no HTTP client in it, so there is no update check, no telemetry and no crash reporter. The only subprocess it spawns is `osascript`, for launch-at-login. Open the file, search for `urllib`, and you have your answer in a minute.

Three things it does:

1. **Small enough to read before you run it.** One 967-line file plus a 178-line optional capture script. No HTTP client imported, so no update check, no telemetry, no crash reporter.
2. **Shows the limit you have left, not the history you spent.** Your 5-hour and weekly remaining capacity, with reset countdowns. (Threshold notifications at 80% and 95% only appear when Tokease runs as the `.app` bundle, which has its own bundle identifier. Homebrew and source installs run under the Python interpreter's identity, and macOS shows nothing. Verified on macOS 26: the call raises no error either way, so there is nothing in the log to tell you — see the roadmap.)
3. **Token-free by construction.** The only data sources are files official Claude clients write locally for their own use. No token read, no endpoint call, nothing to sign up for. MIT.

## Features

- **Two usage rings**: 5-hour session (outer) and weekly (inner) gauges, right in the menu bar
- **Reset countdowns**: see when each window rolls over
- **Honest freshness**: shows when a Claude client last refreshed the data (desktop app or Claude Code), and marks the number `~42%` in the menu bar once it goes stale
- **Customizable display**: icon + percentage, icon only, or percentage only, plus an option to show both percentages (`5h / weekly`)
- **Settings menu**: display modes, refresh interval, alert thresholds (80% / 95%, `.app` build only), launch at login (`.app` build; use `brew services` or the LaunchAgent otherwise)
- **Lightweight**: pure Python, two small dependencies (`rumps` + `Pillow`)
- **No telemetry**: no account, no tracking, nothing phones home

## Prerequisites

- **macOS** (menu bar app using `rumps`)
- **Python 3.10+** (Homebrew installs bring their own, this only matters for source installs. Note: Apple's built-in python3 can be 3.9, which is too old)
- **Claude Desktop** running (zero-config source), and/or **Claude Code ≥ 2.1.x** with the statusline wired up (adds reset countdowns)
- **Claude Pro or Max** subscription. The quota feeds only exist for these plans: Claude **Free** doesn't expose them, and **Team/Enterprise** use credit-based billing, so the rings don't map and it isn't supported.

## How It Works

Tokease merges two local, read-only sources. Whichever is fresher wins:

1. **Claude Desktop history (zero config).** While the Claude desktop app runs, it samples your account quota every 5 to 15 minutes into a local file (`~/Library/Application Support/Claude/plan-usage-history.json`). Tokease reads it as-is. No setup: if the desktop app is running, the rings stay fresh whatever surface you're using (VS Code extension, claude.ai, Cowork, CLI). See [ADR 0003](docs/adr/0003-source-secondaire-plan-usage-desktop.md).
2. **Claude Code statusline (adds reset countdowns).** A small capture script ([`statusline/tokease-statusline.py`](statusline/tokease-statusline.py)) runs as your Claude Code statusline command. Claude Code passes it `rate_limits.five_hour` / `.seven_day` on stdin and the script writes them to `~/.tokease/usage.json`. This is the only feed carrying the *reset times* shown next to each ring.

In both cases the data is written locally *by an official Claude client* for its own use. Tokease never reads your token and never calls any endpoint. Statusline setup: [`statusline/README.md`](statusline/README.md).

> The legacy endpoint mode (which read the OAuth token) is frozen at the git tag `v0.9.0-endpoint`. v1.0 never reads the token.

This is an independent project, **not affiliated with or endorsed by Anthropic**.

## Quick Install (Homebrew, recommended)

```bash
brew install tpatrouillat/tap/tokease
tokease          # launch immediately
brew services start tokease   # auto-start at login
```

Bypasses Gatekeeper (no Apple Developer signing required), installs the Python virtualenv automatically, and `brew upgrade` handles updates.

## Install from Source

```bash
git clone https://github.com/tpatrouillat/tokease.git
cd tokease
bash install.sh
```

The install script will:
1. Create a Python virtual environment and install dependencies
2. Optionally set up a macOS LaunchAgent for auto-start at login
3. Optionally launch the app immediately

## Manual Install (no install script)

```bash
git clone https://github.com/tpatrouillat/tokease.git
cd tokease
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/python tracker.py
```

If the Claude desktop app is running, you are done. Optionally wire up the statusline capture script for reset countdowns: see [`statusline/README.md`](statusline/README.md).

## Uninstall

- **From source:** `bash uninstall.sh` removes the LaunchAgent, the `~/.tokease/` data, and the Tokease `statusLine` block from `~/.claude/settings.json` (with a backup). Then delete the cloned folder.
- **Homebrew:** run the same cleanup first, then remove the formula:
  ```bash
  bash "$(brew --prefix)/opt/tokease/libexec/uninstall.sh"
  brew services stop tokease && brew uninstall tokease
  ```
  `brew uninstall` alone removes the app but leaves `~/.tokease/` and any statusline wiring in place.

## If the rings stop moving after a Claude update

The Claude desktop app's quota file is internal and undocumented, so a Claude update can change its format without notice. Tokease detects that and falls back to the statusline feed rather than showing a wrong number, but if neither source refreshes, the rings freeze at their last reading (always flagged stale). Two commands tell you which source broke:

```bash
ls -la ~/Library/Application\ Support/Claude/plan-usage-history.json   # desktop source present?
cat ~/.tokease/statusline.err                                          # capture script errors
```

Please [open an issue](https://github.com/tpatrouillat/tokease/issues/new/choose) with what you find. There is no telemetry, so a report is the only way this gets noticed.

## I don't see the icon

Tokease is probably running fine and your menu bar is full. On notched MacBooks, macOS hides overflow menu bar icons without any indicator. Quit a menu bar app you don't need (or use a manager like [Ice](https://github.com/jordanbaird/Ice) or Bartender) and the rings appear. The percentage-only display mode in Settings also narrows Tokease's footprint, and Cmd-dragging the icon toward the clock keeps it visible.

## A note on freshness

The percentages are **account-level**: they cover everything on your subscription, from claude.ai chat and Claude Desktop (Cowork included) to the VS Code extension and the CLI. The ring is never wrong about how much quota you've used. The only question is how fresh the last reading is.

- **Claude Desktop running**: readings every 5 to 15 minutes, whatever surface you work in. Worst case the number in the menu bar is that far behind reality, and longer if the desktop app goes idle. This is the recommended setup. Just keep the desktop app open (it lives in your menu bar anyway).
- **Only the statusline wired**: readings refresh while an interactive `claude` terminal session is active (the CLI, or the VS Code *integrated terminal*). The VS Code extension panel, Claude Desktop and headless `claude -p` never execute statuslines ([#55643](https://github.com/anthropics/claude-code/issues/55643), closed "not planned"). With the statusline as sole source, the rings go stale between CLI sessions.
- **Both** (best): desktop history keeps the rings fresh, and statusline captures add the reset countdowns whenever you use the CLI.

Past 20 minutes without a refresh from either source, the menu bar number is prefixed with `~` and the dropdown says how old it is. Reset windows that have already rolled over are detected too. An old percentage is never shown as if it were fresh.

### Who sees the reset countdowns

Only the statusline feed carries reset times. The desktop history file has percentages but no reset timestamps, so the two profiles differ:

- **Power users (any `claude` terminal use, even occasional).** Every message in an interactive CLI session captures both reset times. The weekly countdown then stays displayed until that reset passes (up to 7 days). The 5-hour countdown only lives as long as its window, so it needs a capture within the current 5 hours to show up.
- **Desktop-only users.** Rings and percentages stay current, but the menu shows `resets --`. That is expected, not a bug. One message from any `claude` terminal session (the VS Code *integrated terminal* counts) brings both countdowns back.

When a reset time has passed, Tokease shows `--` rather than guessing the next one. The weekly cycle could be extrapolated, but the 5-hour window anchors on your first message after the previous reset, and showing a made-up time would break the honesty rule above.

Two caveats on the desktop history file. Its format is internal to the Claude app and undocumented, so a future update could change it. Tokease parses it defensively (any anomaly falls back to the statusline feed) and pins its expectations to the observed `version: 2`. And older Claude Desktop builds may not write this file at all: if `plan-usage-history.json` doesn't exist on your machine, update the desktop app or wire the statusline.

Upstream feature requests that would make this cleaner (Tokease benefits automatically if any of them ships):
- [anthropics/claude-code#38380](https://github.com/anthropics/claude-code/issues/38380): expose usage/rate-limit data via a CLI flag or hook event
- [anthropics/claude-code#55643](https://github.com/anthropics/claude-code/issues/55643): statusline support in the VS Code extension
- [anthropics/claude-code#33257](https://github.com/anthropics/claude-code/issues/33257): native usage indicator

A local, opt-in **drift estimator** (estimate usage between captures from the local session logs all surfaces write) is a v1.1 candidate. See [ROADMAP.md](ROADMAP.md).

## Security

- **Reads no token, ever.** Tokease only reads two local files: `~/.tokease/usage.json` (written by the Claude Code statusline) and the Claude desktop app's own `plan-usage-history.json` (read-only). It never touches the Keychain or your OAuth token.
- **No API calls of its own.** The only network calls involved are the ones official Claude clients already make. Tokease just reads the results they wrote locally.
- **No data collection.** The app runs entirely on your machine.
- **No secrets stored.** No `.env`, no tokens, no credentials on disk.
- **Open source.** Audit the code yourself: `tracker.py` plus a small statusline script.

## Running Tests

```bash
venv/bin/python -m unittest discover -s tests
```

(Works with the install-script venv as-is. CI runs the same suite via `pytest` across Python 3.10–3.13. To run it that way locally: `pip install pytest && python -m pytest -q`.)

Tests cover both source readers, the freshness merge, reset logic, time formatting, and display logic using mocked data (no real API calls).

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, the lint/test gate, and commit conventions. Please keep the codebase minimal: this is intentionally a small, focused tool.

- Security issues: [SECURITY.md](SECURITY.md) (don't open a public issue).
- What Tokease reads and never touches: [PRIVACY.md](PRIVACY.md).

## Roadmap

v1.0 is **macOS menu bar + Claude (Desktop / Code) only**, intentionally narrow. See [ROADMAP.md](ROADMAP.md) for what's explicitly out of scope (iPhone, Windows/Linux, other AI tools) and what might land in v1.1.

## License

[MIT](LICENSE) — Thibault Patrouillat

## Disclaimer

This project is not affiliated with, endorsed by, or sponsored by Anthropic. It relies on local files written by Claude apps (the statusline `rate_limits` field and the desktop app's internal quota history), which Anthropic may change without notice. Use at your own risk.
