# ADR 0002 — Removal of the endpoint mode from the v1.0 build

- **Status**: Accepted (2026-06-16)
- **Decision maker**: Thibault
- **Affects**: `tracker.py` (data acquisition), README, Homebrew distribution, positioning
- **Revises**: [ADR 0001](0001-pivot-source-statusline.md) (which kept the endpoint as `legacy`)

## Context

[ADR 0001](0001-pivot-source-statusline.md) made the Claude Code statusline the
default source, **while keeping the old endpoint mode** as `legacy` (disabled
by default, behind a warning). That legacy mode:

1. reads the subscription OAuth token from the Keychain
2. calls an undocumented Anthropic endpoint with a User-Agent imitating Claude Code

Three observations at the time of freezing v1.0:

- **The ToS risk is not gone.** As long as the token-reading code is present
  and can be enabled, the project *invites* the user to risk their paid Claude
  account. That is exactly what ADR 0001 wanted to avoid. Keeping the option,
  even switched off, keeps the product and legal risk alive.
- **The wedge gets diluted.** The v1.0 positioning is "the only Claude Code cap
  tracker that NEVER reads your token". A claim like "the token never leaves
  your machine" is *false* as long as the legacy mode exists (it reads the
  Keychain). A "token-free" product that still ships a token reader is not
  credible.
- **Useless surface.** The legacy mode adds code, error paths, and a security
  surface (Bearer handling, redirect blocking) for data (per-model split plus
  overage) that is not the core value (the remaining cap is), and that the
  statusline does not provide anyway.

The endpoint data (Sonnet/Opus split, paid overage) remains accessible
historically: the full endpoint build is frozen in git at the tag
`v0.9.0-endpoint`.

## Decision

**Remove the endpoint mode entirely from the v1.0 build.** The **only** data
source is now the Claude Code statusline (documented `rate_limits` field via
stdin → `~/.tokease/usage.json`).

- No more "Data source" selector in Settings: there is only one source.
- No Keychain read, no endpoint call, no User-Agent imitation in any v1.0 code
  path.
- The endpoint build stays preserved and auditable at the tag
  `v0.9.0-endpoint`. It is no longer shipped or maintained.
- The positioning fully embraces the **token-free** wedge: "never reads your
  token", compliant by construction (not by promise).

## Consequences

**Positive**
- **A true, defensible token-free wedge**: no code path exists anymore where
  Tokease reads the token. The sentence "never reads your token" becomes
  literally accurate.
- **ToS risk eliminated** for the user: there is no way to enable an
  unauthorized mode by mistake.
- **Less code and a smaller security surface**: no Bearer handling or
  anti-redirect logic to maintain.
- A simpler product message: one source, one story.

**Negative / accepted limits**
- **Loss of the per-model split and the overage**: the statusline does not
  provide them, so the UI has **2 rings** (5h + weekly), with no Sonnet/Opus
  line and no overage. Accepted: that was not the core value (the remaining
  cap is).
- **Freshness**: the data only updates while Claude Code is running (unchanged
  since ADR 0001). Handled honestly with a "stale" flag and detection of
  windows that already reset.
- **Stricter requirements**: Claude Code ≥ 2.1.x plus a Pro/Max plan are
  mandatory (no endpoint fallback for uncovered cases).

**Rejected alternatives**
- *Keep the legacy mode off by default* (ADR 0001 status quo): keeps the ToS
  risk alive and breaks the token-free wedge. That is precisely what this ADR
  fixes.
- *Also delete the endpoint git history*: pointless and destructive. The
  `v0.9.0-endpoint` tag documents where we come from without any risk for
  users.

## References

- [ADR 0001](0001-pivot-source-statusline.md): pivot to the statusline (revised here).
- Preservation git tag: `v0.9.0-endpoint`.
- Official statusline doc (`rate_limits` fields): https://code.claude.com/docs/en/statusline
