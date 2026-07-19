<div align="center">
  <img src="assets/logo-256-demo.png" alt="Tokease" width="200" height="200">
  <h1>Tokease</h1>
  <p>A lightweight macOS menu bar app showing your Claude Code rate limits in real time<br/><strong>The Claude Code limit tracker that never touches your token or Keychain — it reads only what Claude Code already publishes</strong></p>
  <p>
    <a href="https://github.com/tpatrouillat/tokease/actions/workflows/ci.yml"><img src="https://github.com/tpatrouillat/tokease/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
    <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT">
    <img src="https://img.shields.io/badge/platform-macOS-lightgrey.svg" alt="Platform: macOS">
    <img src="https://img.shields.io/badge/telemetry-none-success.svg" alt="No telemetry">
  </p>
</div>

![Tokease menu bar dropdown showing the Claude Code 5-hour and weekly limits with reset times](docs/screenshot.png)

## Why Tokease

Tokease reads the `rate_limits` data **Claude Code itself publishes to its statusline** — nothing else. No OAuth token read from the Keychain, no hidden API call, no User-Agent spoofing. It's compliant with Anthropic's Terms by construction, not by promise. Other trackers read your subscription token from the Keychain; Tokease never touches it.

Three things it does:

1. **Compliant by construction, not by promise.** The only data source is the `rate_limits` feed Claude Code passes to its statusline script (a documented field). No token read, no endpoint call.
2. **Shows the limit you have left, not the history you spent.** Your 5-hour and weekly remaining capacity, with reset countdowns and opt-in alerts at 80% and 95%.
3. **One file, zero telemetry, zero account.** A small single-file menu bar app, MIT-licensed. It runs entirely on your machine — no telemetry, no account, nothing to sign up for.

## Features

- **Two usage rings** — 5-hour session (outer) + weekly (inner) gauges, right in the menu bar
- **Reset countdowns** — see when each window rolls over
- **Honest freshness** — shows when Claude Code last refreshed the data, and flags it *stale* when Claude Code isn't running
- **Customizable display** — icon + percentage, icon only, or percentage only
- **Settings menu** — launch at login, display modes, alert thresholds (notify at 80% / 95%), refresh interval
- **Lightweight** — pure Python, two small dependencies (`rumps` + `Pillow`)
- **No telemetry** — no account, no tracking, nothing phones home

## Prerequisites

- **macOS** (menu bar app using `rumps`)
- **Python 3.10+**
- **Claude Code ≥ 2.1.x** installed and logged in — Tokease reads its statusline `rate_limits` feed
- **Claude Pro or Max** subscription — `rate_limits` only appears for these plans. Claude **Free** doesn't expose it; **Team/Enterprise** use credit-based billing, so the rings don't map and it isn't supported.

> **Note on Desktop, Cowork & VS Code.** Your quota is account-level, so everything you consume there **is counted** in the percentages — but only an interactive CLI session can *refresh* them. Details in [A note on freshness](#a-note-on-freshness).

## How It Works

The only data source is the Claude Code statusline:

1. A small capture script ([`statusline/tokease-statusline.py`](statusline/tokease-statusline.py)) runs as your Claude Code statusline command.
2. Claude Code passes it `rate_limits.five_hour` / `.seven_day` on stdin; the script writes them to `~/.tokease/usage.json`.
3. The menu bar reads that file and shows the two rings + reset countdowns.

Because the data is handed over *by Claude Code*, Tokease stays within the authorized "use with Claude Code" scope: no token read, no endpoint call. Setup details: [`statusline/README.md`](statusline/README.md).

> The legacy endpoint mode (which read the OAuth token) is frozen at the git tag `v0.9.0-endpoint`; v1.0 never reads the token.

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

After installing the app, wire up the statusline capture script — see [`statusline/README.md`](statusline/README.md).

## Uninstall

- **Homebrew:** `brew services stop tokease && brew uninstall tokease`
- **From source:** `bash uninstall.sh` — removes the LaunchAgent, the `~/.tokease/` data, and the Tokease `statusLine` block from `~/.claude/settings.json` (with a backup). Then delete the cloned folder.

## A note on freshness

Two facts define what the rings can and can't do:

1. **The numbers are account-level.** The 5-hour and weekly percentages cover everything on your subscription — claude.ai chat, Claude Desktop (Cowork included), the VS Code extension, and the CLI. The ring is never wrong about how much quota you've used.
2. **Only the interactive CLI refreshes them.** The statusline is a feature of the Claude Code CLI running in a terminal. Claude Desktop, headless `claude -p`, and the VS Code extension panel never execute it — and Claude Code exposes `rate_limits` nowhere else (not in hooks, not in telemetry, not on disk).

So if you mostly work in Desktop or Cowork, Tokease shows the *last captured* value, visibly flagged **stale** — it also detects reset windows that have already rolled over, so an old percentage is never shown as if it were fresh. To refresh: send one message from any `claude` terminal session.

> **Tip:** the VS Code *integrated terminal* running `claude` counts as an interactive CLI session — keep a tab open there and the rings stay fresh without leaving your editor.

Upstream feature requests that would close this gap (Tokease benefits automatically if any of them ships):
- [anthropics/claude-code#38380](https://github.com/anthropics/claude-code/issues/38380) — expose usage/rate-limit data via a CLI flag or hook event
- [anthropics/claude-code#55643](https://github.com/anthropics/claude-code/issues/55643) — statusline support in the VS Code extension
- [anthropics/claude-code#33257](https://github.com/anthropics/claude-code/issues/33257) — native usage indicator

A local, opt-in **drift estimator** (estimate usage between captures from the local session logs all surfaces write) is a v1.1 candidate — see [ROADMAP.md](ROADMAP.md).

## Security

- **Reads no token, ever.** Tokease only reads `~/.tokease/usage.json`, written by the Claude Code statusline. It never touches the Keychain or your OAuth token.
- **No API calls of its own.** The only network call involved is the one Claude Code already makes — Tokease just reads the result Claude Code wrote locally.
- **No data collection** — the app runs entirely on your machine.
- **No secrets stored** — no `.env`, no tokens, no credentials on disk.
- **Open source** — audit the code yourself: `tracker.py` plus a small statusline script.

## Running Tests

```bash
venv/bin/python -m unittest discover -s tests
```

(Works with the install-script venv as-is. CI runs the same suite via `pytest` across Python 3.10–3.13; to run it that way locally: `pip install pytest && python -m pytest -q`.)

Tests cover statusline parsing, freshness/reset logic, time formatting, and display logic using mocked data (no real API calls).

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, the lint/test gate, and commit conventions. Please keep the codebase minimal; this is intentionally a small, focused tool.

- Security issues: [SECURITY.md](SECURITY.md) (don't open a public issue).
- What Tokease reads and never touches: [PRIVACY.md](PRIVACY.md).

## Roadmap

v1.0 is **macOS menu bar + Claude Code only** — intentionally narrow. See [ROADMAP.md](ROADMAP.md) for what's explicitly out of scope (iPhone, Windows/Linux, other AI tools) and what might land in v1.1.

## License

[MIT](LICENSE) — Thibault Patrouillat

## Disclaimer

This project is not affiliated with, endorsed by, or sponsored by Anthropic. It relies on the Claude Code statusline `rate_limits` field, which Anthropic may change without notice. Use at your own risk.
