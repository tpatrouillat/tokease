# Integration Plan — Claude Usage Tracker

**Date:** 2026-03-12
**Goal:** Make usage data accessible everywhere — menu bar, CLI, Claude Code sessions, and third-party tools.

---

## The Problem

The tracker is currently a **GUI-only macOS menu bar app**. But many Claude Code users live in the terminal and never look at the menu bar. They need usage data where they already are:

1. **Inside Claude Code sessions** — see usage without leaving the conversation
2. **In the terminal** — quick `claude-usage` command
3. **In other tools** — Slack bots, dashboards, IDE status bars
4. **Cross-platform** — Linux/WSL users can't use `rumps` at all

---

## Architecture: Current vs. Proposed

### Current (v1.0)

```
macOS Keychain → tracker.py → rumps menu bar
                (monolith)
```

### Proposed (v2.0) — Layered Architecture

```
                          ┌─────────────────────────┐
                          │     Consumers            │
                          │                          │
                          │  • Menu bar (rumps)      │
                          │  • CLI command           │
                          │  • MCP Server            │
                          │  • Claude Code hook      │
                          │  • HTTP API (optional)   │
                          └────────┬────────────────┘
                                   │
                          ┌────────▼────────────────┐
                          │     Core Library         │
                          │                          │
                          │  • get_usage()           │
                          │  • _read_keychain_token()│
                          │  • fmt_reset()           │
                          │  • _safe_int()           │
                          │  • format_plain_text()   │
                          │  • format_json()         │
                          └────────┬────────────────┘
                                   │
                          ┌────────▼────────────────┐
                          │   Data Sources           │
                          │                          │
                          │  • macOS Keychain        │
                          │  • Anthropic OAuth API   │
                          └─────────────────────────┘
```

**Key insight:** Extract the data-fetching logic into a reusable core module. All consumers import the same library.

---

## Integration Options (Ranked by Impact)

### 1. MCP Server (HIGH IMPACT — connects to every Claude Code session)

**What:** Register the tracker as an MCP server so Claude Code can query usage data mid-conversation.

**Why this is the killer feature:**
- Every Claude Code user (CLI and IDE) gets usage awareness
- No separate app needed — it runs inside Claude Code itself
- Users can ask "what's my usage?" naturally in conversation
- Claude can proactively warn when approaching limits

**How it works:**
```
claude mcp add usage-tracker -- python3 /path/to/mcp_server.py
```

Once registered, Claude Code gains a `get_usage` tool it can call. Users can ask:
- "What's my current usage?"
- "How close am I to the rate limit?"
- "When does my 5-hour window reset?"

**Implementation:**
- New file: `mcp_server.py` (~80 lines)
- Uses the `mcp` Python SDK (stdio transport)
- Exposes one tool: `get_usage` → returns formatted usage data
- Reuses existing `get_usage()` from `tracker.py`

**Registration:**
```bash
claude mcp add usage-tracker -- python3 /path/to/mcp_server.py
```

Or via `.mcp.json` in any project:
```json
{
  "mcpServers": {
    "usage-tracker": {
      "command": "python3",
      "args": ["/path/to/mcp_server.py"]
    }
  }
}
```

**Effort:** Small (1 new file, reuse existing logic)
**Platform:** Cross-platform (works on Linux/WSL too if keychain is replaced)

---

### 2. CLI Command (HIGH IMPACT — terminal-native users)

**What:** A standalone `claude-usage` command that prints usage to stdout.

**Why:** Many users want a quick glance without a GUI. Works in scripts, tmux status bars, shell prompts, etc.

**Output formats:**
```bash
# Human-readable (default)
$ claude-usage
5-hour:  42% (resets in 3h 12m)
Weekly:  18% (resets Mar 15)
Sonnet:   5% (resets Mar 15)
Extra:   $12.50/$50.00 (25%)

# JSON (for scripting)
$ claude-usage --json
{"five_hour":{"utilization":42,"resets_at":"2026-03-12T18:00:00Z"},...}

# One-liner (for status bars / prompts)
$ claude-usage --short
42% | 18% | 5%
```

**Implementation:**
- New file: `cli.py` (~60 lines)
- Uses `argparse` for `--json`, `--short` flags
- Reuses `get_usage()` and `fmt_reset()` from core
- Install via `pip install .` or symlink

**Integration examples:**
```bash
# tmux status bar
set -g status-right '#(claude-usage --short)'

# Shell prompt (zsh)
RPROMPT='$(claude-usage --short 2>/dev/null)'

# Watch mode
watch -n 60 claude-usage
```

**Effort:** Small (1 new file)
**Platform:** Cross-platform (same keychain caveat)

---

### 3. Claude Code Hook (MEDIUM IMPACT — automatic awareness)

**What:** A user-prompt-submit hook that injects usage context before each message.

**Why:** Users don't have to ask — Claude always knows the current usage state and can warn proactively.

**How Claude Code hooks work:**
In `~/.claude/settings.json`:
```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "type": "command",
        "command": "python3 /path/to/hook_usage.py"
      }
    ]
  }
}
```

The hook runs before each user message is processed. It can inject system context.

**Implementation:**
- New file: `hook_usage.py` (~30 lines)
- Calls `get_usage()`, formats a one-line summary
- Outputs to stdout → Claude sees it as system context
- Caches results for 60s to avoid hammering the API on every message

**What Claude sees:**
```
[Usage: 5h=42% (resets 3h12m) | Weekly=18% | Sonnet=5%]
```

**Tradeoff:** Adds ~1-2s latency per message (API call). Caching mitigates this.

**Effort:** Small (1 new file + config)

---

### 4. Shared Core Library Refactor (PREREQUISITE for all above)

**What:** Extract data-fetching and formatting from `tracker.py` into a reusable module.

**Current state:** Everything is in one file. The menu bar app imports and runs directly.

**Proposed structure:**
```
claude-usage-tracker/
├── claude_usage/
│   ├── __init__.py          # Package exports
│   ├── core.py              # get_usage(), _read_keychain_token(), _safe_int()
│   ├── formatting.py        # fmt_reset(), format_plain_text(), format_json()
│   └── constants.py         # INTERVALS, defaults, API URL
├── tracker.py               # Menu bar app (imports from claude_usage)
├── cli.py                   # CLI command (imports from claude_usage)
├── mcp_server.py            # MCP server (imports from claude_usage)
├── hook_usage.py            # Claude Code hook (imports from claude_usage)
└── tests/
    ├── test_core.py
    ├── test_formatting.py
    ├── test_tracker.py
    ├── test_cli.py
    └── test_mcp_server.py
```

**Effort:** Medium (refactor, not rewrite — move functions, update imports, keep tests green)

---

### 5. Cross-Platform Token Source (MEDIUM IMPACT — Linux/WSL support)

**What:** Support reading tokens from sources other than macOS Keychain.

**Why:** Linux and WSL users run Claude Code too. They store credentials differently.

**Token sources to support:**
1. **macOS Keychain** (current) — `security find-generic-password`
2. **Linux secret-tool** — `secret-tool lookup service "Claude Code-credentials"`
3. **Environment variable** — `CLAUDE_OAUTH_TOKEN` (for CI/scripts)
4. **Config file** — `~/.claude/credentials.json` (if Claude Code stores it there on Linux)

**Implementation:**
- Abstract `_read_keychain_token()` into a token provider interface
- Auto-detect platform and use appropriate backend
- Fallback chain: env var → platform keychain → config file

**Effort:** Medium

---

## Future Vision: Multi-Tool Usage Aggregator (v2/v3)

Beyond Claude Code, many AI-powered tools have their own usage limits and credits:

| Tool | Usage Model |
|------|-------------|
| **Claude Code** | 5-hour / weekly / Sonnet caps + paid overage |
| **Lovable** | Monthly credit allocation |
| **Replit** | Token/cycle-based billing |
| **Cursor** | Monthly request caps (fast/slow) |
| **Windsurf** | Credit-based system |
| **GitHub Copilot** | Monthly completions quota |
| **v0 (Vercel)** | Generation credits |

**Vision:** A unified dashboard showing usage across all AI dev tools in one place — menu bar, CLI, or MCP server.

**Why defer to v2/v3:**
- Each tool has its own auth mechanism (OAuth, API keys, cookies)
- Most don't have public usage APIs — would need reverse-engineering per tool
- Token/credential management across tools is a significant security surface
- Plugin architecture needed to add tools without modifying core

**When to start:** Once the core library refactor (Phase 1) is done and the plugin/provider pattern is in place, adding new tools becomes modular.

---

## What NOT to Build (v1)

| Idea | Why skip it |
|------|-------------|
| **Web dashboard** | Over-engineering for a personal utility; menu bar + CLI covers it |
| **Electron app** | Adds 200MB+ for what rumps does in 1MB |
| **Database/history** | The API gives real-time data; historical tracking is a different product |
| **Multi-user support** | Personal tool; one keychain = one user |
| **Auto-refresh in CLI** | `watch claude-usage` already exists |
| **Slack/Discord bot** | Too niche; users can pipe CLI output if they want |

---

## Recommended Implementation Order

### Phase 1 — Core + CLI (do now)
1. Refactor into `claude_usage/` package (keeps `tracker.py` working)
2. Add `cli.py` with `--json` and `--short` flags
3. Update `setup.py` with `console_scripts` entry point

### Phase 2 — MCP Server (do next)
4. Create `mcp_server.py` with `get_usage` tool
5. Add install instructions for `claude mcp add`
6. Test in live Claude Code sessions

### Phase 3 — Hooks + Cross-platform (future)
7. Add hook script with caching
8. Abstract token source for Linux support
9. Update README with all integration methods

---

## Sync Problem: CLI Users Without the Menu Bar

**The real question:** How do CLI-only users stay aware of their usage?

**Answer: The MCP Server is the solution.** Here's why:

| Approach | Requires GUI? | Always visible? | Works in CLI? | Zero-effort? |
|----------|--------------|-----------------|---------------|--------------|
| Menu bar app | Yes | Yes | No | Yes |
| CLI command | No | No (must run it) | Yes | No |
| MCP Server | No | Yes (Claude knows) | Yes | Yes |
| Hook | No | Yes (auto-injected) | Yes | Yes |

The MCP server is the best sync mechanism because:
- It runs alongside every Claude Code session (CLI or IDE)
- Claude can proactively mention usage without the user asking
- No separate window, no extra commands, no context switching
- Works on all platforms Claude Code supports

**Combined approach for maximum coverage:**
- **Power users:** CLI command + MCP server
- **Casual users:** Menu bar app (current)
- **All users:** MCP server (auto-awareness in every session)
