# Independent security review brief — Tokease (paste into codex / cursor-agent / grok)

You are doing an independent, unprimed security review. You have not seen any prior findings; form your own.

## What the software is
Tokease is a public, shipped (v1.0.6) macOS menu-bar app in Python, distributed via Homebrew (`tpatrouillat/homebrew-tap`, formula not in this repo). It shows the user's Claude usage quota (5-hour and weekly windows). Its central public claim (README, PRIVACY.md, SECURITY.md, docs/adr/0002-retrait-mode-endpoint.md) is that it **never reads an authentication token or the Keychain and makes no network call**. A CI test, `TokenFreeInvariantTest` in `tests/test_tracker.py`, is presented as the automated guard for that claim: it parses the AST of every shipped `.py` file.

## Threat model to use
Local-only: no server, no accounts, no network. The app reads two JSON files written by other processes running as the same user — `~/.tokease/usage.json` (written by `statusline/tokease-statusline.py`, which Claude Code runs and feeds JSON on stdin) and `~/Library/Application Support/Claude/plan-usage-history.json` (written by the Claude desktop app). It writes `~/.tokease/` and NSUserDefaults. Shell installers write `~/Library/LaunchAgents/` and edit `~/.claude/settings.json` (a file that can contain secrets and that tells Claude Code which command to execute).

Adversaries worth considering: a malicious or careless contributor / compromised maintainer account; PyPI and GitHub Actions supply chain; another process running as the same user feeding crafted JSON (note: it already has code execution as the user, so rate accordingly); another local account on the same Mac reading files left behind. Web-app categories (SQLi, XSS, CSRF, sessions) do not apply — say "not applicable" rather than padding.

## Files to read
- `tracker.py` (~1,000 lines, the app) and `statusline/tokease-statusline.py` (178 lines, the capture script)
- `install.sh`, `statusline/install-statusline.sh`, `uninstall.sh`
- `tests/test_tracker.py`, class `TokenFreeInvariantTest` (near the end of the file)
- `requirements.txt`, `pyproject.toml` (ruff config), `.github/workflows/ci.yml`, `.github/dependabot.yml`, `setup.py`, `build.sh`
- Claims to verify against: `SECURITY.md`, `PRIVACY.md`, `README.md` (the "Trust" paragraphs), `docs/adr/0002-retrait-mode-endpoint.md`

## The open question
Audit this app's handling of untrusted local JSON input and its installer scripts for injection, file-permission, and supply-chain risk. **Do not assume the token-free claim is true — verify it**, and specifically test whether the AST-based CI guard would actually catch code that reads a credential or reaches the network by a route it does not enumerate (try to write a snippet that passes all of its checks). Also check whether the installers can corrupt, widen the permissions of, or wrongly edit `~/.claude/settings.json`.

## Output format
One finding per item: severity (Critical/High/Medium/Low/Info, as exploitability × blast radius), `file:line` evidence, what an attacker actually gets, a one-line fix. Mark anything requiring the attacker to already run code as the user as theoretical. No finding without a file:line.
