# Roadmap

Where this project is, and where it might go.

## v1.0 — what ships now

A single-file macOS menu bar app that shows your 5-hour / weekly remaining capacity as two rings, read from two local files official Claude apps already write: the Claude desktop app's quota history (zero config, refreshed every 5 to 15 minutes) and the `rate_limits` data Claude Code publishes to its statusline (optional, adds reset countdowns). That's it. No token read, no endpoint call. A small single-file Python app, MIT, two small dependencies (`rumps` for the menu bar, `Pillow` for the dynamic icon).

> The legacy endpoint mode (which read the OAuth token from the Keychain and called an undocumented endpoint) is removed from v1.0 and frozen at the git tag `v0.9.0-endpoint`.

### Explicitly out of scope for v1.0

| Ask | Why not now |
|---|---|
| **iPhone / iPad app** | Native iOS = Swift + Apple Developer cert + App Store review. 1–2 months of work before validating the menu bar version even resonates. |
| **Web dashboard** | Would require a backend to relay data off your machine. Breaks the "audit one file, nothing leaves your Mac, no token read" pitch — which is the whole trust argument. |
| **Windows / Linux ports** | Depend on `rumps` (macOS-only NSStatusBar wrapper). The statusline capture itself is small and portable — a fork-friendly target, but I won't maintain ports myself. |
| **Lovable / Cursor / Codex / other AI tools** | Each tool has its own quota system. Most don't expose limits the way Claude Code's statusline does. Adding them = waiting on each vendor to publish (or reverse-engineering each one and inheriting N break-points). |
| **Per-window / per-session token breakdown** | The statusline `rate_limits` feed reports account-level windows (5-hour / weekly), not per-conversation telemetry. Would require parsing local Claude Code JSONL logs, which drift whenever the CLI changes. |
| **Auto-update / Sparkle** | Updates ship via `brew upgrade`. Sparkle would need code signing + notarization. |

## v1.1 — candidates

These are real possibilities, not promises. Which one (if any) gets built depends on adoption and on what launch feedback actually asks for.

### If there's strong pull for more

Pick **one** of the following based on what issues and comments actually ask for. Not two of them. Not all seven.

1. **iPhone companion app (native Swift)** — read-only view of the same `usage.json`, synced from the Mac by a small local helper. Transport design is deliberately open: anything that talks over a network, even on your own LAN, would ship opt-in, off by default, behind its own ADR. Estimated 4–6 weeks.
2. **Second-tool support (most likely: Cursor or Lovable)** — only if that tool's vendor exposes a stable, authorized way to read remaining limits, or the community surfaces one with a known cadence. Estimated 1–2 weeks per tool.
3. **Per-window context tracker** — parses `~/.claude/projects/*.jsonl` to surface "this conversation has used X/200K context." Estimated 2–3 weeks; fragile by design.
4. **Opt-in drift estimator (nothing-running gap)** — between two official captures, estimate quota drift by counting tokens in the local `~/.claude/projects/*.jsonl` session logs and show "~71% *(estimated)*" until the next exact capture. Since the Claude Desktop history landed (ADR 0003), the remaining gap is only "no Claude client running at all", which shrinks the case for this. Still 100% local, zero network, zero token read — but it widens the read surface beyond `~/.tokease`, so it would ship **opt-in, off by default**, behind a dedicated privacy note and ADR. Estimated 1–2 weeks. Only if launch comments actually ask for it.
5. **Per-model windows (Fable / Opus)** — Claude Fable 5 now has its own quota on Max plans, but Claude Code drops the model-scoped windows before serializing `rate_limits` to the statusline (only `five_hour` + `seven_day` reach us). **Blocked upstream** — the request still open is [anthropics/claude-code#73770](https://github.com/anthropics/claude-code/issues/73770). [#78232](https://github.com/anthropics/claude-code/issues/78232) was closed as a duplicate of it, and [#79022](https://github.com/anthropics/claude-code/issues/79022) as a duplicate of [#52661](https://github.com/anthropics/claude-code/issues/52661), which the stale bot then closed for inactivity rather than on a product decision. [#77453](https://github.com/anthropics/claude-code/issues/77453) was closed as completed by its own author; the statusline payload we read has not changed since, which is our own observation rather than anything the issue states. The day one ships, adding a third ring / menu line is a small change. The known workaround (reading `cachedUsageUtilization` from Claude Code's internal state files) is undocumented internal state — rejected for now, same reasoning as the privacy invariant: we only read what Claude Code deliberately publishes.

6. **Usage insights (what drives your limits)** — a local re-computation of the "What's contributing to your limits usage?" panel from Claude Code's `/usage` screen, always visible from the menu bar: share of usage coming from subagent-heavy sessions, from sessions active 8+ hours, from >150k-token contexts, from parallel sessions, plus per-skill / per-subagent / per-MCP-server breakdowns. Claude Code computes this on the fly from the local session transcripts (`~/.claude/projects/*.jsonl`) and stores it nowhere, so Tokease would parse the same files: metadata only (timestamps, token counts, tool names), never conversation content, still read-only and zero network. Same fragility caveat as candidates 3 and 4 (undocumented JSONL that drifts with CLI versions), and it widens the read surface beyond `~/.tokease`, so it ships opt-in behind its own ADR and privacy note. Estimated 2–3 weeks.
7. **API-billing mode (Console/API-key users)** — a different product shape: API accounts have no 5-hour/weekly subscription windows, they have spend and RPM/TPM limits. The authorized path is Anthropic's documented Admin Usage & Cost API, but it needs an admin API key and network calls, which breaks the zero-network invariant. If ever built, it ships as a clearly separated opt-in mode behind its own ADR and privacy note. Post-launch evaluation only.

### If interest is steady but modest

No v1.1 work. v1.0.1 polish only — bug fixes, UX hardening, more tests around edge cases users report.

**Tracked polish ideas:**
- **Signed and notarized `.app` (double-click install)** — the py2app build already works (`build.sh` produces `Tokease.app`). What's missing is the Apple Developer Program (~99 USD/year) for codesigning and notarization. Without it, a downloaded `.app` hits Gatekeeper's "can't be opened" dialog, which is a worse first impression than the one-line brew install. Worth the yearly fee if launch traction justifies it.
- **Threshold notifications outside the `.app`** — the 80 % and 95 % alerts only show a banner when Tokease runs as the bundle, which carries its own bundle identifier. From Homebrew or source the process runs under the Python interpreter's identity and macOS displays nothing, silently: measured on macOS 26, `rumps.notification` returns cleanly in both cases, so no error reaches the log. An ad-hoc signature is enough for the banner, so this is about bundle identity rather than the Developer Program. Options if it matters: ship the menu bar item as the reminder instead, or move alerts to `UNUserNotificationCenter` behind a real bundle.
- **Ring clear-out animation** — when a 5-hour or weekly limit resets, briefly animate the affected ring from its previous fill back to empty (4–5 frames over ~400ms, driven by `rumps.Timer`). Pure cosmetic, but it makes resets feel earned.
- **Draw the ring icon with CoreGraphics instead of Pillow.** Pillow is roughly 35k lines and 14 MB, imported to draw two arcs. PyObjC is already a dependency and CoreGraphics can draw them, which would drop the second dependency and shrink the install. Same output, smaller trust surface.
- **A `jq` or shell variant of the statusline capture.** The capture script pays Python interpreter startup on every statusline render, where a `jq` one-liner would cost a few milliseconds. The Python script stays the reference, the faster variant would be optional.
- **Enterprise / Team plan support** — credit-based billing instead of 5-hour/weekly windows, so the 2-ring UI doesn't map. Blocked on whether Claude Code's statusline ever exposes a credit-style signal for these plans; until then, Pro/Max only (the README says so).

### If the hook doesn't land

No expansion as a recovery move. The scope stays where it is, and the focus shifts to understanding what didn't resonate before building anything new.

## Why this roadmap exists

If you opened an issue or PR asking for one of the v1.1 candidates: thank you, your interest is the signal that decides what gets built. Please don't open a PR adding it yet — the v1.0 scope is deliberately narrow so the trust pitch ("read the one file") survives. Once a v1.1 track is chosen, we'll open dedicated issues for it and label them `help-wanted`.

If you want something not on this list, open an issue describing the use case. The roadmap updates monthly based on what people actually need vs. what I assumed they'd need.

## What will never ship

These are non-negotiables, not "maybe later" items.

- **No backend server, no cloud relay, no phone-home.** Nothing leaves your Mac, and Tokease never reads your token in the first place. Anything that ever talks over a network ships opt-in, off by default, behind its own ADR.
- **No telemetry, no analytics, no phone-home.** Not even anonymous usage counts.
- **No paid tier, no premium features held back.** Fully MIT-licensed; the Homebrew build is identical to the source.
- **No unsigned `.app` pushed as the default install path.** Homebrew + source install keeps the audit trail visible. A properly signed and notarized `.app` may ship later as an *additional* option (see v1.1), never as a replacement.
