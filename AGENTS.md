# Tokease — project guidance

> **This repo holds the *how*.** The *why* — product framing, decisions, launch status — lives in Brain:
> `../../brain/projects/Tokease/context.md` · workspace rules `../../brain/AGENTS.md` · Python conventions (`../../brain/knowledge/tooling/conventions/python.md`).
> Machine context (directory tree, MCP, output routing) is loaded automatically from `~/.claude/CLAUDE.md`, which imports `../../brain/context/cartographie.md`. The other paths above do not load on their own: open them at the start of the session. Paths local to the development machine.

Shipped as v1.0 and public. Distributed via Homebrew through the tap `tpatrouillat/homebrew-tap`: every release touches both repos.

## Brain — short vs long

`CLAUDE.md` loads **only** `context.md` (one page). Journal, product ADRs, cycle-1 plan: on demand, never `@`imported.

If a change alters a product promise, freeze, visible behaviour, or launch — even if the trigger is technical — update Brain `context.md` in **this** session (`decisions/` if it is a decision). Technical ADRs stay in `docs/adr/`. No daily agent.

## graphify

Knowledge graph at `graphify-out/`.

- Code questions: `graphify query "…"` when `graphify-out/graph.json` exists; `graphify path "A" "B"`; `graphify explain "…"`.
- Broad nav: `graphify-out/wiki/index.md` if present. `GRAPH_REPORT.md` only if those miss.
- After code changes: `graphify update .` (AST-only, no API cost).

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
