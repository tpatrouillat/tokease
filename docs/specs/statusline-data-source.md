# Spec — "statusline" data source

Ref: [ADR 0001](../adr/0001-pivot-source-statusline.md) and
[ADR 0002](../adr/0002-retrait-mode-endpoint.md). Describes the contract
between the statusline script (producer) and the menu bar app (consumer).

> Since [ADR 0002](../adr/0002-retrait-mode-endpoint.md), the statusline is the
> **only** data source: the endpoint mode is removed from v1.0 (frozen at the
> tag `v0.9.0-endpoint`). Tokease therefore never reads the token.

## Overview

```
Claude Code  ──(JSON stdin on every tick)──▶  tokease-statusline.py  ──(atomic write)──▶  ~/.tokease/usage.json
                                                                                                      │
                                                                              tracker.py (every N s) ──┘  reads, displays
```

## Producer — `statusline/tokease-statusline.py`

Invoked by Claude Code as the statusline command. On every run it:

1. reads the JSON on stdin (`{ ..., "rate_limits": { "five_hour": {...}, "seven_day": {...} } }`)
2. extracts the windows present (each may be absent, per the Claude Code doc:
   `rate_limits` only appears **after the first exchange** of a session, for Pro/Max subscribers)
3. writes `~/.tokease/usage.json` **atomically** (write to a temp file in the
   same directory, then `os.replace`) so the reader never sees a partial file
4. prints a minimal statusline line (or nothing). The statusline display is not
   the goal, the capture is.

Constraints: Python 3 stdlib only (no `jq`), and it must **never** fail loudly
(a crash would pollute the Claude Code statusline). Every error is swallowed
silently on the script side, **but** nothing is written when the JSON is
invalid.

## File format `~/.tokease/usage.json` (schema 1)

```json
{
  "schema": 1,
  "captured_at": 1739000000,
  "source": "claude-code-statusline",
  "five_hour": { "used_percentage": 23.5, "resets_at": 1738425600 },
  "seven_day": { "used_percentage": 41.2, "resets_at": 1738857600 }
}
```

- `captured_at`: epoch seconds at write time (used to compute staleness).
- each window is **optional**. `used_percentage` ∈ [0,100], `resets_at` epoch s.
- no sonnet/opus split and no overage: not provided by the statusline.

## Consumer — `tracker.py`

`fetch_usage()` reads the `~/.tokease/usage.json` file (primary source; the
desktop history of [ADR 0003](../adr/0003-source-secondaire-plan-usage-desktop.md)
is merged in by freshness) and normalizes it into the internal shape `_update_display`
expects
(`{"five_hour": {"utilization": …, "resets_at": ISO}, …}`, `used_percentage`→`utilization`,
epoch→ISO), adding `_meta`. There is no user-facing source switching: the endpoint
mode was removed (see [ADR 0002](../adr/0002-retrait-mode-endpoint.md)).

### Error states

| Code | Trigger | Display |
|------|---------|---------|
| `nostatusline` | file missing | ⚙ title + 3-step guide in the menu (not wired) |
| `waiting` | file present, no window captured | "Waiting for Claude Code…" |
| `error` | unreadable file / invalid JSON | "?" |

### Freshness & reset

- **Staleness**: if `now − captured_at > 20 min`, flag the data as stale (the
  *Updated* line gets a ⚠ prefix). This signals that no Claude client is
  refreshing it (threshold set in `honest-freshness.md`).
- **Window reset**: if `resets_at < now`, the window has rolled over since the
  capture, so the stored `used_percentage` is no longer valid. We display
  "(reset)" and do not draw the ring as if it were current.

### Rendering

- **2 rings** (5h outer, weekly inner).
- no Sonnet / Opus split and no overage: not provided by the statusline, and
  the endpoint mode that exposed them was removed (see [ADR 0002](../adr/0002-retrait-mode-endpoint.md)).

## User-side wiring (friction #2)

Claude Code allows only **one** statusline command (`settings.json` →
`statusLine.command`). Two cases:

1. **No existing statusline**: point `statusLine.command` at
   `python3 ~/.tokease/tokease-statusline.py` (the installer copies the script there).
2. **Existing statusline**: insert the capture *snippet* (3 lines) at the top
   of the existing script. It writes the file, then leaves the original
   display intact. (We never modify `settings.json` automatically: the risk is
   overwriting an existing statusline.)

Details and snippet: `statusline/README.md`.
