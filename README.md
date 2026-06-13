<div align="center">
  <img src="assets/logo-256-demo.png" alt="Tokease" width="200" height="200">
  <h1>Tokease</h1>
  <p>A lightweight macOS menu bar app showing your Claude Code API usage in real time<br/><strong>Know your limits before you hit them</strong></p>
</div>

![Tokease screenshot](docs/screenshot.png)

## Features

- **3-Ring Activity Display** — Visual gauges for 5-hour session, weekly, and top-model usage
- **Customizable Display** — Show icon + percentage, icon only, or percentage only
- **Real-time usage** — Updates every 5 minutes (configurable)
- **Extra usage tracking** — See paid overage spend if enabled
- **Zero config** — Reads your existing Claude Code OAuth token from macOS Keychain
- **Settings menu** — Launch at login, display modes, alert thresholds, refresh interval
- **Lightweight** — Pure Python, minimal dependencies, zero network overhead
- **Secure** — Token never leaves your Mac, no data collection

## Prerequisites

- **macOS** (menu bar app using `rumps`)
- **Python 3.10+**
- **Claude Code** installed and logged in (`claude login`)
- **Claude Pro or Max** subscription — the usage endpoint returns 403 on free accounts, and Team/Enterprise (credit-based billing) is not supported yet; the 3-ring model doesn't map to it

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

1. Reads Claude Code's OAuth token from the macOS Keychain (`Claude Code-credentials`)
2. Calls Anthropic's usage endpoint (`/api/oauth/usage`) with Bearer authentication
3. Displays utilization percentages and reset countdowns in the menu bar

The menu bar shows your current 5-hour session usage. Click it to see weekly limits, Sonnet limits, extra usage, and more.

## Security

- **No data collection** — the app runs entirely on your machine
- **Token handling** — the OAuth token is read from the Keychain, used for a single API call, then immediately cleared from memory
- **No redirects** — HTTP redirects are blocked to prevent the Bearer token from leaking to other domains
- **No secrets stored** — no config files, no `.env`, no credentials on disk
- **Open source** — audit the code yourself: it's a single `tracker.py` file

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
