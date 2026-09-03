# ADR 0003 — Secondary source: Claude desktop app usage history

- **Status**: Accepted (2026-07-20)
- **Decision maker**: Thibault
- **Affects**: `tracker.py` (acquisition), README (requirements), privacy invariant

## Context

The statusline source (ADR 0001) only "ticks" during a Claude Code session
**in a terminal** (TUI). The VS Code extension in its graphical panel never
executes `statusLine.command`. Anthropic treats this as a known limitation
(issue [#55643](https://github.com/anthropics/claude-code/issues/55643) closed
"not planned"). Yet Thibault's main usage (and likely a growing share of
users') goes through the extension. As a result, `usage.json` goes stale as
soon as no terminal session is running, and Tokease shows "stale" continuously.

Paths investigated and rejected (2026-07-20, official docs + tests on this machine):
- **Hooks**: no payload contains `rate_limits`.
- **Transcripts** (`~/.claude/projects/*.jsonl`): per-message tokens, never the
  quota windows.
- **OpenTelemetry**: token/cost metrics only, no 5h/7d windows.
- **Claude Code caches** (`~/.claude.json`, `~/.claude/**`): nothing structural.

**Discovery.** The **Claude desktop app** (`/Applications/Claude.app`) samples
the plan quota **every 5 to 15 minutes** while it runs, and persists it to:

```
~/Library/Application Support/Claude/plan-usage-history.json
```

Observed format (version 2): `{"version": 2, "samples": [{"t": <epoch ms>,
"org": "<uuid>", "u": {"fh": <% 5h>, "sd": <% 7d>}}, …]}`. Verified live:
284 samples over ~29 h, median cadence 300 s, values consistent with the
statusline. Re-measured on 1086 samples over a month, the cadence is bimodal:
half the gaps are 5 min, a quarter are 15 min, and the app skips samples while
idle. A reading can therefore be up to ~20 min old and still be normal
operation, which is why `_STALE_AFTER_SECS` is 20 min and not 15. The data
stays fresh **even when only the VS Code extension is
used** (and even during Claude.ai/Desktop usage, since this is the account's
quota).

## Decision

Add `plan-usage-history.json` as a **read-only secondary source**, merged with
the statusline by freshness:

- the **statusline stays the primary source** (richer: it alone provides
  `resets_at`)
- if the desktop sample is more recent than `captured_at`, its percentages
  (`fh` → five_hour, `sd` → seven_day) take over for display
- **defensive** parsing: `version != 2`, missing key, invalid JSON, missing
  file → silently ignore the source and fall back to the statusline (never a
  crash, never a visible error)
- **strict read-only**: no write outside `~/.tokease` (invariant unchanged),
  zero network, zero Keychain

## Consequences

**Positive**
- Near-continuous data (no 20-hour gap) whenever the desktop app runs. Covers
  VS Code extension, Claude.ai and Desktop usage, not just the CLI.
- Privacy invariant intact: we read a local file written by Anthropic's own
  app for its own use. No token, no network call, no imitation. Far lower ToS
  risk than the endpoint (ADR 0001/0002): no server access at all.

**Negative / accepted limits**
- **Undocumented format**: internal to the desktop app, it can change without
  notice. Hence the defensive parsing plus the `version` guard, with the
  statusline as the safety net.
- **No `resets_at`**: reset times only come from the statusline. They are
  shown only when a recent statusline capture exists.
- **Lag up to ~20 min**: between two desktop samples the percentage is frozen
  and can be far behind reality (on 2026-09-01 the menu bar sat at 26 % for
  30 min while the 5h window went to 100 %). Past the stale threshold the
  title prefixes the number with `~`, so a frozen reading says so itself.
  Threshold alerts are deliberately not gated on freshness: they only fire
  when the percentage crosses upward between two refreshes, so a frozen
  reading never fires one, and a late one is still true. A refresh that lands
  on a reset reports no percentage at all, so the last seen value is re-anchored
  at 0 and the new cycle can raise its own alert.
- **Mixed merge**: when a partial statusline capture is completed by the
  desktop feed, the "Updated" line reports the fresher source. The filled
  window can be up to 20 min older than that line suggests.
- **Requirement**: the Claude desktop app installed and running (menubar). To
  document in the README as "recommended for freshness", not mandatory.
- **Multi-org**: the `org` field must be respected if several orgs appear (we
  take the most recent sample, displayed org not handled in v1).

**ToS compliance (analysis verified on 2026-07-20)**
- The Consumer Terms (Oct 8, 2025) forbid neither reading local files created
  by Anthropic apps nor anything comparable. The reverse engineering clause
  targets decompilation ("reduce our Services to human-readable form", and a
  plain-text JSON already is). The automated access/scraping clauses target
  access to the **Services** (servers), not the user's disk.
- The February 2026 clarification is scoped to **routing requests to
  Anthropic's servers with a subscription token** ("route requests through
  Free, Pro, or Max plan credentials"). Tokease makes no network call.
- Direct precedent: ccusage and friends have been reading Claude Code's
  undocumented local JSONL files since mid-2025, at scale, with no known
  enforcement, including after the January-February 2026 OAuth purge.
- Retained classification: statusline source = authorized (documented
  surface), desktop source = weak grey area, no identifiable violation of the
  current terms. To re-check if Anthropic changes its Terms.

**Rejected alternatives**
- *The extension's terminal mode* (`"claudeCode.useTerminal": true`): works,
  but it forces a usage change on the user. Kept as a README tip, not as the
  product solution.
- *Upstream feature request* (expose `rate_limits` to hooks or in a documented
  cache): worth opening anyway (see issue
  [#20636](https://github.com/anthropics/claude-code/issues/20636)), uncertain
  horizon.

## References

- Issue #55643 (statusline in the VS Code extension, "not planned"):
  https://github.com/anthropics/claude-code/issues/55643
- Issue #20636 (expose the rate limits outside the statusline):
  https://github.com/anthropics/claude-code/issues/20636
- Statusline doc (`rate_limits` contract): https://code.claude.com/docs/en/statusline
- ADR 0001 (statusline pivot) · ADR 0002 (endpoint removal)
