# Contributing to Tokease

Thanks for considering a contribution. Tokease is intentionally small — a menu
bar app that reads local usage files written by official Claude clients, token-free. Please keep changes
minimal and in that spirit.

## Dev setup

```bash
git clone https://github.com/tpatrouillat/tokease.git
cd tokease
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
pip install ruff pytest        # dev tools
```

## Before opening a PR

- **Lint:** `ruff check .` (must pass — includes basic security rules).
- **Format:** `ruff format .`
- **Tests:** `python -m pytest -q` (must stay green; add tests for new behavior).
- Keep `tracker.py` readable and dependency-light (currently `rumps` + `Pillow`).
  New runtime dependencies need a strong justification.
- The statusline capture script must **never crash** Claude Code's statusline
  (always exit 0, log errors to `~/.tokease/statusline.err`).
- Don't reintroduce token/Keychain/endpoint reads — that path was removed on
  purpose (see `docs/adr/0002-retrait-mode-endpoint.md`).

## Commits & PRs

- Use [Conventional Commits](https://www.conventionalcommits.org/)
  (`fix:`, `feat:`, `docs:`, `chore:`…).
- Keep PRs focused; describe what changed and why.
- CI (ruff + pytest across Python 3.10–3.13) must be green.

## Reporting bugs

Open an issue with the bug template (Claude Code version, plan, what the menu bar
shows, and any `~/.tokease/statusline.err` excerpt). For security issues, see
[`SECURITY.md`](SECURITY.md).
