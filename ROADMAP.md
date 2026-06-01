# Roadmap

Where this project is, and where it might go.

## v1.0 — what ships now

A single-file macOS menu bar app that reads your Claude Code OAuth token from the Keychain, hits the undocumented `/api/oauth/usage` endpoint, and shows your 5-hour / weekly / per-model utilization. That's it. ~430 lines of Python, MIT, single dependency (`rumps`).

### Explicitly out of scope for v1.0

| Ask | Why not now |
|---|---|
| **iPhone / iPad app** | Native iOS = Swift + Apple Developer cert + App Store review. 1–2 months of work before validating the menu bar version even resonates. |
| **Web dashboard** | Would require a backend to relay OAuth tokens. Breaks the "audit one file, token never leaves your Mac" pitch — which is the whole trust argument. |
| **Windows / Linux ports** | Depend on `rumps` (macOS-only NSStatusBar wrapper) and the macOS Keychain. The HTTP call itself is ~80 lines and portable — a fork-friendly target, but I won't maintain ports myself. |
| **Lovable / Cursor / Codex / other AI tools** | Each tool has its own quota system. Most don't expose a public usage endpoint. Adding them = waiting on each vendor to publish (or reverse-engineering each one and inheriting N break-points). |
| **Per-window / per-session token breakdown** | The `/api/oauth/usage` endpoint returns account-level aggregates, not per-conversation telemetry. Would require parsing local Claude Code JSONL logs, which drift whenever the CLI changes. |
| **Auto-update / Sparkle** | Updates ship via `brew upgrade`. Sparkle would need code signing + notarization. |

## v1.1 — candidates

These are real possibilities, not promises. Which one (if any) gets built depends on launch-week signal.

### Trigger: >500 GitHub stars in the first week

Pick **one** of the following based on what the comments actually ask for. Not both. Not all three.

1. **iPhone companion app (native Swift)** — read-only view backed by a small local sync helper on the Mac. Token never leaves the Mac; the phone pulls from a local HTTP server on the LAN. Estimated 4–6 weeks.
2. **Second-tool support (most likely: Cursor or Lovable)** — only if that tool's vendor publishes a stable usage endpoint, or the community reverse-engineers one with a known cadence. Estimated 1–2 weeks per tool.
3. **Per-window context tracker** — parses `~/.claude/projects/*.jsonl` to surface "this conversation has used X/200K context." Estimated 2–3 weeks; fragile by design.

### Trigger: 200–500 stars in the first week

No v1.1 work. v1.0.1 polish only — bug fixes, UX hardening, more tests around edge cases users report.

**Tracked polish ideas:**
- **Ring clear-out animation** — when a 5-hour or weekly limit resets, briefly animate the affected ring from its previous fill back to empty (4–5 frames over ~400ms, driven by `rumps.Timer`). Pure cosmetic, but it makes resets feel earned.

### Trigger: <200 stars in the first week

The hook didn't land. No expansion as a recovery move. Iterate on positioning, write a follow-up post in 4 weeks framed around something other than "I built another tool."

## Why this roadmap exists

If you opened an issue or PR asking for one of the v1.1 candidates: thank you, your interest is the signal that decides what gets built. Please don't open a PR adding it yet — the v1.0 scope is deliberately narrow so the trust pitch ("read the one file") survives. After the v1.1 trigger fires, we'll open dedicated issues for the chosen track and label them `help-wanted`.

If you want something not on this list, open an issue describing the use case. The roadmap updates monthly based on what people actually need vs. what I assumed they'd need.

## What will never ship

These are non-negotiables, not "maybe later" items.

- **No backend server, no cloud relay.** The token never leaves your Mac.
- **No telemetry, no analytics, no phone-home.** Not even anonymous usage counts.
- **No paid tier, no premium features held back.** Fully MIT-licensed; the Homebrew build is identical to the source.
- **No bundled `.app` requiring signed installation.** Homebrew + source install keeps the audit trail visible.
