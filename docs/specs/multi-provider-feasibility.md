# Spec — multi-provider feasibility (Codex, Cursor, Gemini, Grok, Lovable)

Date: 2026-09-12. Status: analysis, nothing implemented. Sources frozen at
repo `1b480ef` and Brain `12716ec`. Companion documents:
[`codex-integration.md`](codex-integration.md) (first integration) and
[ADR 0005](../adr/0005-architecture-multi-source.md) (how a source is added).

## 0. The question

Which of the five tools can Tokease show **honestly under its current
promise**: a local file written by the vendor's own client for its own use,
read as is, no token, no network, no Keychain, nothing written outside
`~/.tokease` (R9 in `display-strategy.md`, ADR 0002, `PRIVACY.md`). A tool
that only exposes its quota through an authenticated endpoint is
**incompatible**, not "to be worked around".

Vocabulary kept strict, because the vendors mix them: **quota** (a rolling
or calendar window with a used percentage and a reset time, what the rings
show), **consumption** (tokens or requests spent, no ceiling attached),
**credits** (a prepaid balance in money or units), **cost**.

## 1. Matrix

| Tool | Data that exists | Local access (no token, no network) | Freshness | Plans covered | Promise | Verdict |
|---|---|---|---|---|---|---|
| **Codex** (CLI, Desktop app, `codex exec`, IDE) | Quota: `primary` / `secondary` rolling windows, `used_percent`, `window_minutes`, `resets_at` epoch, plus `credits` balance and `plan_type`. Several limit families coexist, told apart by `limit_id`: `codex` is the account quota, others are per-model or promotional (`base_model_inference`, `codex_bengalfox` seen) | **Yes, with a caveat.** Every turn appends a `token_count` event carrying the `rate_limits` snapshot to the session rollout `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`. Caveat: the rollout is the session's **conversation log** (messages, reasoning, tool calls and outputs, cwd), the quota event is one line among them, and the Codex Desktop builds seen here (0.152.1, 0.153.1) write `rate_limits: null` in every `token_count`. Persistence is in the open-source CLI ([`codex-rs/rollout/src/policy.rs`](https://github.com/openai/codex/blob/main/codex-rs/rollout/src/policy.rs), `EventMsg::TokenCount` in the persisted list); struct in [`codex-rs/protocol/src/protocol.rs`](https://github.com/openai/codex/blob/main/codex-rs/protocol/src/protocol.rs) (`RateLimitSnapshot`, `RateLimitWindow`). Same directory for every surface: originators seen on this machine `codex-tui`, `Codex Desktop`, `codex_exec`, `orca_desktop`. | One event per turn while Codex runs (10 to 20 s apart in an active session), nothing between sessions. Same profile as the Claude Code statusline, with one advantage: it carries `resets_at`. | ChatGPT Plus, Pro, Go, Business, Edu (windows differ by plan, see § 3). API-key users: no windows. | R9: passes (file written by the official client for its own `codex resume`, read-only, no token, no network; format public in the vendor's repo but not declared stable). Promise: **wider than ADR 0003**. The reader parses the tail of a conversation log and deserialises conversation lines before discarding them; "two quota files" and "never reads the conversation" stop being true. That is a product decision, not an R9 check (ADR 0005) | **Integrable under R9; gated on Brain decision 0005** (proposed 2026-09-13, unsigned). First if admitted. |
| **Cursor** (IDE, `cursor-agent`) | Credits: two dollar-denominated monthly pools ("Cursor Models", "Other Models"), reset with the billing cycle, no rolling window | **No.** Usage is shown in editor settings and the web dashboard, both fetched live ([cursor.com/docs/account/pricing](https://cursor.com/docs/account/pricing): "Usage pools", "each resetting with your monthly billing cycle"; no CLI, status bar or API surface documented). On this machine `state.vscdb` holds no usage value (only `cursor.creditGrantPrimaryDismissedPromos`, `cursor.dismissedCreditGrantIds`); `~/.cursor/` has hooks, projects, `cli-config.json`, an `ai-code-tracking.db` (lines of code, not quota). Cursor hooks hand tool events to scripts, never a balance. | n/a | n/a | Only reachable through the account session (dashboard, Admin API for Teams): token plus network | **Not integrable today.** |
| **Gemini CLI** (`gemini` 0.58.0, Code Assist) | Quota: per-model buckets with `remainingFraction`, `remainingAmount`, `resetTime` (`RetrieveUserQuotaResponse` in [`packages/core/src/code_assist/types.ts`](https://github.com/google-gemini/gemini-cli/blob/main/packages/core/src/code_assist/types.ts)); plans in [docs/resources/quota-and-pricing.md](https://github.com/google-gemini/gemini-cli/blob/main/docs/resources/quota-and-pricing.md) (1,000 req/day free, 1,500 AI Pro, 2,000 Ultra) | **No.** The CLI fetches `retrieveUserQuota` over the network and keeps it in memory (`this.lastRetrievedQuota` in [`packages/core/src/config/config.ts`](https://github.com/google-gemini/gemini-cli/blob/main/packages/core/src/config/config.ts)) for `/stats model` and `ModelQuotaDisplay.tsx`. Nothing under `~/.gemini/` on this machine carries a quota: `tmp/<project>/logs.json` is the message log, `state.json` is UI state, `oauth_creds.json` is the token (never read). Hooks and telemetry carry tokens and requests, not the buckets. | n/a | n/a | Only through the Code Assist endpoint with the OAuth token: token plus network | **Not integrable today.** Cheapest unblock of the four: the CLI already has the data in memory; an upstream request to persist the last quota response locally would make it a Codex-shaped source. |
| **Grok** (`grok` CLI 1.0.25, Grok Bot app, grok.com) | Subscription: one weekly allowance shared across Grok products, visible in grok.com "Settings → Usage" (percentage and reset). API: prepaid credits and per-model RPS/TPM in the xAI Console ([docs.x.ai/developers/rate-limits](https://docs.x.ai/developers/rate-limits)) | **No.** The bundled CLI reference (`~/.grok/README.md`, 107 KB) documents `~/.grok/sessions/<cwd>/<id>/` with `signals.json` ("session signals (turn count, token usage)"), `summary.json`, `updates.jsonl`: consumption and context, no quota. No `/usage` or `/status` command listed. `settings_cache.json` is a signed server settings payload (feature flags), no limits. `auth.json` is the token (never read). | n/a | n/a | Only through grok.com or the API with the session token: token plus network | **Not integrable today.** |
| **Lovable** (lovable.dev, `Lovable.app` 1.4.3 Electron wrapper) | Credits: daily build credits (5/day, reset 00:00 UTC), monthly plan credits (billing cycle, rollover 2 months), Cloud/AI grants ([docs.lovable.dev/introduction/credits-and-usage](https://docs.lovable.dev/introduction/credits-and-usage)) | **No.** Web app; the desktop bundle is an Electron shell (`app.asar`, updater `downloads.lovable.dev/desktop`), no Application Support data on this machine. Credits are shown in the workspace credit bar and "Settings → Plans & credit usage"; no CLI, no local file, no public API documented. | n/a | n/a | Browser session only: token plus network (reading a browser profile is out of scope by construction) | **Not integrable today.** |

Evidence hashes (files outside the repo, read-only, sha256):

| Path | sha256 |
|---|---|
| `~/.codex/sessions/2026/09/11/rollout-2026-09-11T17-01-10-01a090fc-9f68-71b3-bd16-9932f8f230db.jsonl` | `c8d09ff5cff169fab821d01ce23a698d889066d85022a55d210c4b3dc3030ebe` |
| `~/.codex/sessions/2026/09/04/rollout-2026-09-04T22-11-21-01a06e0c-17d7-7ce1-96fb-d2e437c0d702.jsonl` | `51e19902387850fd1719a06b9f0cf3a6011412118f2a2a29af1e3ed15d8a4e9b` |
| `~/.codex/config.toml` | `ee3e41683f8adec422a715ab6d445ee1fddf939cc394bc00b2b156e260af507f` |
| `~/.grok/README.md` (bundled CLI reference, v1.0.25) | `53d251b380bae4d6f5d83ed90de4f987dda152854191d02ade9d4cc9b3a3e1e7` |
| `~/.grok/sessions/…/01a0709b-4d34-72b1-92f9-1160a1a32b53/signals.json` | `71c0d85b39456f1f5a07db10d8cf1f68a748214835d2f99cfa5c24da60bad9b9` |
| `~/.gemini/tmp/thib/logs.json` | `e34ee6c87e72eb09ec8bc27fa708b5d5b35d3351c3bb8a1aaecf3ea490e59db0` |
| `~/.cursor/cli-config.json` | `4d6ad0a15a2d5975aec003c85e4b2a4ae720e6220a2d49521bf54559d816194b` |

Cursor `state.vscdb` was queried for key names only (`ItemTable`, keys
matching usage/quota/limit/billing/plan, auth and token keys excluded);
`auth.json` (Codex, Grok) and `oauth_creds.json` (Gemini) were listed, never
opened.

## 2. Priority order

1. **Codex.** The only one with a vendor-written local file, and it carries
   more than the Claude desktop feed does (reset times, window length, plan).
   Its user base overlaps Tokease's (people who run several agent CLIs), and
   the reader is the same shape as `_read_desktop_usage`, but not the same
   surface: it parses a conversation log. Blocked on Brain 0005, not on
   code.
2. **Gemini CLI.** Blocked, but one upstream change away: the quota response
   already lives in the process. Worth a feature request, not code.
3. **Cursor, Grok, Lovable.** Blocked with no local surface in sight. Cursor
   and Lovable are credit balances, not windows, so even with a file they
   would not fit the rings; they would be a text line.

This contradicts `ROADMAP.md` line 31 ("Second-tool support (most likely:
Cursor or Lovable)"): those are the two with the least local surface. The
roadmap line should name Codex when `main` reopens (18/09); this spec does
not touch it.

## 3. Heterogeneous quotas

The Claude feed has exactly two windows, always the same. The Codex feed does
not:

| `plan_type` seen | `primary.window_minutes` | `secondary.window_minutes` |
|---|---|---|
| `plus` | 300 (5 h) | 10080 (7 d) |
| `prolite` | 10080 (7 d) | absent (`null`) |
| `go` | 43200 (30 d) | absent |

(Counts over the September rollouts on this machine: 2157 events with a
300-minute window, 2625 with 10080, 61 with 43200.) So a provider row cannot
assume "5-hour and weekly". Rules, reusing `display-strategy.md`:

- **Label from the data, never from an assumption.** A window is named by
  its `window_minutes` (`5-hour`, `Weekly`, `30-day`), and a plan with one
  window shows one row. Unknown `window_minutes` → the row shows the
  percentage with the reset only, no name guessed (R5).
- **Age ceiling from the window itself** (R3): a reading older than
  `window_minutes` is void (`— (reading older than the window)`), the same
  guard `_window_row` already applies with `_FIVE_HOUR_SECS` /
  `_SEVEN_DAY_SECS`.
- **Reset from the feed, only while ahead** (R4): the Codex feed carries
  `resets_at`, so a passed reset shows `— (reset; awaiting Codex)`.
- **Providers are never merged.** Two accounts, two quotas, two "Updated"
  lines. The per-window freshness merge of `_merge_usage` is a Claude-internal
  rule (two feeds of one account). A provider is its own block.
- **Absent source = absent block**, not a nag (R5, R6). The `⚙` setup guide
  stays for the Claude source, which is the product. A provider section only
  appears when its file is readable; a provider that never ran leaves no
  trace in the menu.
- **Stale is per provider** (R1): the section's own line reads
  `⚠ 14:02 · stale 3h (Codex idle?)` past 20 min, same threshold, same
  wording family as `_freshness_label`.
- **Title and rings stay Claude** in the first integration (§ 5 confidence
  ladder unchanged). A second provider in the title is a product choice
  (Brain), not a display rule.

## 4. What would change the promise

Codex fits under R9 as written, but R9 covers where the file comes from and
what the reader may not do, not what else the file holds. The rollout is a
conversation log; parsing its tail weakens the "two quota files" wording of
README and `PRIVACY.md` even though four numbers are kept. That is the
product decision drafted (not signed) in Brain
`projects/Tokease/decisions/0005-lecture-du-journal-codex.md`: default with
exact wording, explicit opt-in, or wait for a quota-only file upstream. The
2026-09-12 draft of this section said "nothing here requires it"; that was
wrong. The four others would need a network call with the user's token,
which is exactly what ADR 0002 removed: a further, separate product
decision if ever wanted, not drafted. Watch list that would unblock a tool
without touching the promise:

- Codex CLI persists its last `RateLimitSnapshot` in a dedicated file under
  `~/.codex` (option C of Brain 0005): the source becomes a quota file, R9
  suffices, the conversation log is never opened.
- Gemini CLI persists its last `retrieveUserQuota` response under `~/.gemini`.
- Cursor adds a usage payload to its hooks, or `cursor-agent` writes a
  status file.
- Grok CLI writes rate-limit headers or a usage snapshot into
  `~/.grok/sessions/*/signals.json`.
- Lovable ships a real local client. Unlikely to matter: its unit is a
  credit balance, not a window.

## 5. Deviations between the brief and the frozen sources

- The brief lists Brain decisions `0002…0003`; both exist and neither
  concerns other tools. No conflict.
- `ROADMAP.md` line 18 says of the five tools "Most don't expose limits the
  way Claude Code's statusline does". Verified: true for four, false for
  Codex, which exposes strictly more (window length, plan, credits).
- README and `PRIVACY.md` bind the product to "two local files" and "one
  1,000-line file". A Codex source makes it two quota files plus the tail
  of a conversation log, and about 1,090 lines; both claims must move with
  the code (see the integration spec § 4), and the first one gets weaker,
  which is Brain 0005's call. Not a deviation from the brief, but a public
  claim the brief does not list.
