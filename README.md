<div align="center">
  <img src="assets/logo-256-demo.png" alt="Tokease" width="200" height="200">
  <h1>Tokease</h1>
  <p>A lightweight macOS menu bar app showing your Claude Code rate limits in real time<br/><strong>The only Claude Code limit tracker that never reads your token</strong></p>
</div>

![Tokease screenshot](docs/screenshot.png)

## Why Tokease

Tokease reads the `rate_limits` data **Claude Code itself publishes to its statusline** — nothing else. No OAuth token read from the Keychain, no hidden API call, no User-Agent spoofing. It's compliant with Anthropic's Terms by construction, not by promise. Other trackers read your subscription token from the Keychain; Tokease never touches it.

Three things it does:

1. **Compliant by construction, not by promise.** The only data source is the `rate_limits` feed Claude Code passes to its statusline script (a documented field). No token read, no endpoint call.
2. **Shows the limit you have left, not the history you spent.** Your 5-hour and weekly remaining capacity, with reset countdowns — amber at 80%, red at 95%.
3. **One file, zero telemetry, zero account.** A small single-file menu bar app, MIT-licensed. Nothing leaves your machine; nothing to sign up for.

## Features

- **Two usage rings** — 5-hour session (outer) + weekly (inner) gauges, right in the menu bar
- **Reset countdowns** — see when each window rolls over
- **Honest freshness** — shows when Claude Code last refreshed the data, and flags it *stale* when Claude Code isn't running
- **Customizable display** — icon + percentage, icon only, or percentage only
- **Settings menu** — launch at login, display modes, alert thresholds (amber 80% / red 95%), refresh interval
- **Lightweight** — pure Python, two small dependencies (`rumps` + `Pillow`)
- **No telemetry** — no account, no config files, nothing phones home

## Prerequisites

- **macOS** (menu bar app using `rumps`)
- **Python 3.10+**
- **Claude Code ≥ 2.1.x** installed and logged in — Tokease reads its statusline `rate_limits` feed
- **Claude Pro or Max** subscription — `rate_limits` only appears for these plans. Claude **Free** doesn't expose it; **Team/Enterprise** use credit-based billing, so the rings don't map and it isn't supported.

> **Note on Desktop & Cowork.** The statusline is a feature of the **Claude Code CLI only** — Claude Desktop and Cowork can't feed Tokease. But rate limits are tracked at the **account level**, so running the CLI now and then also reflects what you consumed in Desktop/Cowork. Tokease targets CLI users.

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

## A note on freshness

The `rate_limits` feed only updates **while Claude Code is running** — its statusline ticks on activity. When Claude Code is closed, Tokease shows the last known values and flags them *stale*; it also detects reset windows that have already rolled over, so an old percentage is never shown as if it were fresh. This is an honest limitation of reading a statusline feed rather than calling an endpoint.

## Security

- **Reads no token, ever.** Tokease only reads `~/.tokease/usage.json`, written by the Claude Code statusline. It never touches the Keychain or your OAuth token.
- **No API calls of its own.** The only network call involved is the one Claude Code already makes — Tokease just reads the result Claude Code wrote locally.
- **No data collection** — the app runs entirely on your machine.
- **No secrets stored** — no config files, no `.env`, no credentials on disk.
- **Open source** — audit the code yourself: `tracker.py` plus a small statusline script.

## Running Tests

```bash
venv/bin/python -m pytest tests/ -v
```

Tests cover statusline parsing, freshness/reset logic, time formatting, and display logic using mocked data (no real API calls).

## Contributing

Contributions are welcome! Here's how:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes
4. Run the tests (`venv/bin/python -m pytest tests/ -v`)
5. Commit and push
6. Open a Pull Request

Please keep the codebase minimal — this is intentionally a small, focused tool.

## Roadmap

v1.0 is **macOS menu bar + Claude Code only** — intentionally narrow. See [ROADMAP.md](ROADMAP.md) for what's explicitly out of scope (iPhone, Windows/Linux, other AI tools) and what might land in v1.1.

## License

[MIT](LICENSE) — Thibault Patrouillat

## Disclaimer

This project is not affiliated with, endorsed by, or sponsored by Anthropic. It relies on the Claude Code statusline `rate_limits` field, which Anthropic may change without notice. Use at your own risk.
