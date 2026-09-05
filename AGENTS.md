# Tokease — project guidance

> **This repo holds the *how*.** The *why* — product framing, decisions, launch status — lives in Brain:
> `../../brain/projects/Tokease/` · workspace rules `../../brain/AGENTS.md` · Python conventions (`../../brain/knowledge/tooling/conventions/python.md`).
> Machine context (directory tree, MCP, output routing) is loaded automatically from `~/.claude/CLAUDE.md`, which imports `../../brain/context/cartographie.md`. The other paths above do not load on their own: open them at the start of the session. Paths local to the development machine.

**macOS menu bar** app that tracks Claude Code usage and quota. Python 3.14 · rumps · Pillow · py2app. No web, no Supabase.

Shipped as v1.0 and public. Distributed via Homebrew through the tap `tpatrouillat/homebrew-tap`: every release touches both repos.

## Build & Verify

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
ruff check .
python -m pytest
```

## Things to watch

- The quota reader must **never** read an authentication token: that is the product's public promise ([ADR 0002](docs/adr/0002-retrait-mode-endpoint.md)), verified in CI by `TokenFreeInvariantTest` (tests/test_tracker.py), which reads the AST of every shipped file. It is a regression tripwire, not a proof: the file staying small enough to read remains the real argument.
- Two usage sources, the fresher one wins: Claude Desktop app quota history (zero-config) and Claude Code statusline (optional, the only one that provides reset countdowns).
- The repo is public: no secrets, and the README claims bind the product.
