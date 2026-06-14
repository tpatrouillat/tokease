<div align="center">
  <img src="assets/logo-256-demo.png" alt="Tokease" width="200" height="200">
  <h1>Tokease</h1>
  <p>A lightweight macOS menu bar app showing your Claude Code API usage in real time<br/><strong>Know your limits before you hit them</strong></p>
</div>

![Tokease screenshot](docs/screenshot.png)

## Features

- **Authorized by design** — reads the usage Claude Code itself exposes to its statusline (`rate_limits`); no OAuth token read, no API call, no User-Agent spoofing
- **Usage rings** — 5-hour session + weekly gauges in the menu bar (per-model Sonnet/Opus and paid overage are available only in the legacy API mode below)
- **Customizable Display** — icon + percentage, icon only, or percentage only
- **Honest freshness** — shows when Claude Code last refreshed the data, and flags it stale when Claude Code isn't running
- **Settings menu** — data source, launch at login, display modes, alert thresholds, refresh interval
- **Lightweight** — pure Python, two small dependencies (rumps + Pillow)
- **No telemetry** — nothing leaves your machine except, in legacy mode only, the call Claude Code already makes to Anthropic's servers

## Prerequisites

- **macOS** (menu bar app using `rumps`)
- **Python 3.10+**
- **Claude Code ≥ 2.1.x** installed and logged in — the default mode reads its statusline `rate_limits` feed
- **Claude Pro or Max** subscription — `rate_limits` only appears for subscribers; Team/Enterprise (credit-based billing) isn't supported (the gauges don't map to it)

## Data sources & Terms of Service

Tokease has two modes (Settings → **Data source**):

- **Claude Code statusline (default, recommended).** Reads the `rate_limits`
  data Claude Code (≥ 2.1.x) already passes to its statusline script. The data
  is provided *by Claude Code*, so this stays within the authorized "use with
  Claude Code" scope — no token read, no endpoint call.
  → setup: [`statusline/README.md`](statusline/README.md).

- **Direct API (legacy, off by default, at your own risk).** Reads the OAuth
  token from your Keychain and calls Anthropic's usage endpoint directly. As of
  **February 2026**, Anthropic's Consumer Terms restrict the subscription OAuth
  token to Claude Code and Claude.ai only, so **this mode likely violates those
  terms**, with account-level enforcement. It exists only because it also
  surfaces per-model and overage data the statusline feed doesn't. Enable it
  only if you understand and accept the risk to your Claude account.

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

## How It Works

**Default (statusline) mode:**
1. A small capture script ([`statusline/tokease-statusline.py`](statusline/tokease-statusline.py)) runs as your Claude Code statusline command
2. Claude Code passes it `rate_limits.five_hour` / `.seven_day` on stdin; the script writes them to `~/.tokease/usage.json`
3. The menu bar reads that file and shows the gauges + reset countdowns

**Legacy (Direct API) mode** reads the Keychain token and calls `/api/oauth/usage` directly — see the ToS note above.

Click the menu bar item to see the weekly limit and (in legacy mode) per-model and overage details. Setup for the default mode: [`statusline/README.md`](statusline/README.md).

## Security

- **Default mode reads no token** — it only reads `~/.tokease/usage.json`, written by the Claude Code statusline. The token-related points below apply to the legacy *Direct API* mode only.
- **No data collection** — the app runs entirely on your machine
- **Token handling (legacy mode)** — the OAuth token is read from the Keychain, used for a single API call, then immediately cleared from memory
- **No redirects (legacy mode)** — HTTP redirects are blocked to prevent the Bearer token from leaking to other domains
- **No secrets stored** — no config files, no `.env`, no credentials on disk
- **Open source** — audit the code yourself: `tracker.py` plus a small statusline script

## Running Tests

```bash
venv/bin/python -m pytest tests/ -v
```

Tests cover token retrieval, API response parsing, time formatting, and display logic using mocked data (no real API calls).

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

This project is not affiliated with, endorsed by, or sponsored by Anthropic. It uses an undocumented API endpoint that may change without notice. Use at your own risk.
