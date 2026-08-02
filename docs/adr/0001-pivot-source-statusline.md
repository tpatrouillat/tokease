# ADR 0001 — Data source pivot: OAuth endpoint → Claude Code statusline

> **Update 2026-06-16:** the decision to keep the endpoint as a legacy mode is revised by [ADR 0002](0002-retrait-mode-endpoint.md). The endpoint is removed from v1.0.

- **Status**: Accepted (2026-06-14)
- **Decision maker**: Thibault
- **Affects**: `tracker.py` (usage data acquisition), distribution, README

## Context

Tokease displays Claude plan consumption (5-hour window, weekly) in the macOS
menu bar. Until now, the data was obtained like this:

1. read the subscription OAuth token from the Keychain (`Claude Code-credentials`)
2. call `https://api.anthropic.com/api/oauth/usage` with that Bearer plus a
   User-Agent imitating `claude-code/*`

**Problem (blocking).** Anthropic's *Consumer Terms*, clarified in February 2026,
restrict the subscription OAuth token (Free/Pro/Max) to **Claude Code and
Claude.ai only**. Any other tool is unauthorized, with server-side blocking
(Jan 2026) and account-level enforcement (Apr 2026). The mechanism above most
likely violates those terms, and the User-Agent imitation exists precisely to
bypass the server-side block. Launching publicly would mean inviting users to
risk their paid Claude account.

**New element (May 2026).** Since Claude Code **2.1.x**, Claude Code itself
passes the following fields (officially documented) on the standard input of
any *statusline* script, for Pro/Max subscribers:

```
rate_limits.five_hour.used_percentage   (+ resets_at, epoch s)
rate_limits.seven_day.used_percentage   (+ resets_at, epoch s)
```

The data that only existed in the risky endpoint is now **provided by Claude
Code itself**, through a supported integration surface.

## Decision

Make the **statusline the default and authorized data source**:

- a script (`statusline/tokease-statusline.py`) that the user wires into the
  Claude Code statusline captures `rate_limits` from stdin and writes it, with
  an atomic write, to `~/.tokease/usage.json` (timestamped `captured_at`)
- `tracker.py` reads that file on every refresh and displays it

Since Claude Code hands over the data, we stay within the "use **with** Claude
Code" scope, which is **compliant with the terms**. In this mode we no longer
read the token, no longer call the endpoint, and no longer imitate the
User-Agent.

The old **endpoint mode is kept** as `legacy`, selectable in Settings,
**disabled by default**, behind an explicit ToS warning. The full endpoint
version is also frozen in git at the tag `v0.9.0-endpoint`.

## Consequences

**Positive**
- Compliant with Anthropic's terms. No risk for the user's account.
- The `rate_limits` field is officially documented, so the contract is stable
  and far less fragile than the undocumented endpoint.
- No token read and no User-Agent imitation in the default mode.

**Negative / accepted limits**
- **Freshness**: the data only updates while Claude Code is running (the
  statusline only "ticks" on activity). When Claude Code is closed, we show
  the last known value. Mitigated by a visible timestamp, a "stale" flag, and
  detection of windows that already reset (we never show an old % as if it
  were fresh).
- **2 rings instead of 3**: the statusline exposes neither the per-model
  detail (sonnet/opus) nor the paid overage. Those lines show `n/a` in this
  mode.
- **Install friction**: Claude Code allows only one statusline command. For
  users who already have one, we provide a *snippet* to insert rather than a
  replacement (see the spec). The "zero config" pitch gets weaker.
- **Requirement**: Claude Code ≥ 2.1.x.

**Rejected alternatives**
- *OAuth endpoint by default*: unauthorized (the original blocker).
- *Admin Usage & Cost API*: authorized, but it targets API/Console and
  Enterprise customers, not Pro/Max subscription caps. That is a different
  product.
- *Local logs (ccusage-style)*: authorized, but they show consumption, not the
  remaining cap. The core value would be lost.
- *An official third-party OAuth program*: does not exist to date.

## References

- Official statusline doc (`rate_limits` fields): https://code.claude.com/docs/en/statusline
- The Register (ban clarification, Feb 2026): https://www.theregister.com/2026/02/20/anthropic_clarifies_ban_third_party_claude_access/
- Usage & Cost API (Admin): https://platform.claude.com/docs/en/manage-claude/usage-cost-api
