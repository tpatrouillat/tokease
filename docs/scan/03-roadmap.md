# Phase 3 — Roadmap (sequenced plan)

Date: 2026-09-10. Inputs: `docs/scan/00-inventory.md`, `01-design.md`, `02-security.md`, `ROADMAP.md`. Read-only: no code changed. This document sequences; it does not choose product direction. Where a choice belongs to the owner, ROADMAP.md's own deferral is cited instead of a guess.

## How to read this

- **Finding IDs.** Phase 1 (`01-design.md`): `A1–A7` (§1.4), `P1–P19` (§2), `M1–M7` (§3.3), `D1–D5` (§4), feature rows `§5 #n`, divergences `§6 #n`. Phase 2 (`02-security.md`): `F1–F9`.
- **Effort.** S ≤ 0.5 day, M 0.5–2 days, L > 2 days; one developer who knows the code. **Bet against** = I would not stake my own estimate on it, with the reason.
- **Two constraints shape every item that touches shipped code:**
  1. `tracker.py` sits at exactly 1,000 lines and README.md:4/26/30, docs/index.html, CHANGELOG restate that number (D5). Every shipped-code item below adds lines. Until Q1 is answered, each one must be net-zero, which is the "denser code" incentive Phase 1 warns against. That is why **Now** contains only test/CI changes.
  2. AGENTS.md: a change to a product promise, visible behaviour or claim must update Brain `context.md` in the same session. The Brain page is **not present in this environment** (Phase 1 header), so the items marked *(Brain)* need the owner or a session that has it.

Sequencing at a glance:

```
Now    N1 tripwire fails closed ─ N2 SHA-pinned actions (rider)
Next   X1 line-count gate (needs Q1) ─▶ X3 small user-facing fixes ─▶ X4 self-diagnosing states
       X2 parallel-session capture ─▶ X7 docs match code
       X5 macOS CI lane          X6 installer hygiene
Later  L1 window registry ─▶ L2 pure view ─▶ L3 CoreGraphics ─▶ L4 animation
       X5 ─▶ L7 .app-readiness ─▶ L8 signed .app (owner: Developer Program)
       L2 + L7 ─▶ L5b banner alerts     Q2 ─▶ L5a title marker (could move to Next)
       X2 + X7 ─▶ L9 jq capture         L6 multi-org     L10 hash lockfile
       L11 v1.1 candidates: blocked on the owner's decision, not sequenced here
```

---

## Now (this week)

**Phase 2 status, plainly: 0 Critical, 0 High.** One Medium (F1), five Low (F2–F6, F6 theoretical), three Info. The shipped code holds the token-free promise by inspection (F9). Nothing is on fire.

**Nothing blocks users today.** Both distributed paths (Homebrew, source) work. The two nearest things to a user-blocking defect are P6 (two parallel Claude Code sessions make an old reading look fresh and can re-fire the 80 % alert) and P16 (no single-instance guard, two icons — surfaced twice via CHANGELOG). Both have workarounds and are sequenced first in Next, not inflated into Now.

**Decision on F1 (Medium): it goes in Now.** Not because it is an emergency — it is a control weakness, not an exposed surface, and it needs a merged PR to exploit — but because:

1. It is the CI guard on the product's one public promise, cited as such by README.md:26, AGENTS.md ("Things to watch") and SECURITY.md. A reviewer skimming the four `FORBIDDEN_*` sets over-estimates it; Phase 2 showed six cheap bypasses that pass.
2. Every PR in this plan goes through that gate. Tightening it *before* the code churn of Next/Later starts is the right order; after is the wrong one.
3. It is test/CI-only: zero lines in `tracker.py`, no behaviour change, no D5 collision, no Brain update, no macOS needed. It is the cheapest, highest-leverage change in the whole review.

Optional owner action, 15 minutes, before N1 lands: paste `docs/scan/handoffs/phase2-security-peer-brief.md` into a second model. Every Phase 2 finding is tagged `[solo — no peer available]`; F1's table is reproducible (probe script described in F1) but unconfirmed by a second reader.

### N1 — The token-free tripwire fails closed on the bypasses Phase 2 demonstrated

- **Outcome.** `TokenFreeInvariantTest` rejects dynamic imports, `ctypes`, framework-level URL loading, credential *files* (not only Keychain APIs), non-constant spawn argv, and browser opens to anything but `STAR_URL`; the three shell installers are inside the guard; its docstring says what it does and does not catch. A contributor who tries any row of F1's table gets a red check.
- **Acceptance criteria.**
  - Each of the nine snippets in F1's table, recreated as fixtures (e.g. `tests/fixtures/tripwire/*.py`, or inline strings fed to the same AST checks), **fails** the test; the two controls still fail; the current shipped files still pass; the full suite stays green on py3.10–3.13.
  - Imports: a positive allow-list for the two shipped files (Phase 2 fix sketch (6) — smaller to maintain than the deny-list; the app imports 9 stdlib modules + rumps/PIL/Foundation/PyObjCTools, the script `json/os/sys/time/pathlib`). `Quartz`/`CoreGraphics` stay allowed (tests:2047-2048) so L3 does not have to reopen this test. Any `Call` whose callee is `__import__` or `import_module`, and any `importlib`/`ctypes` import, is a failure.
  - Strings/attributes: `dataWithContentsOfURL`, `stringWithContentsOfURL`, `NSURLConnection`, `NSURL`, `.credentials`, `Keychain`, `.env` added to the forbidden set.
  - Spawn check fails closed: a spawner call whose argv head is not a string constant is a failure, not a skip.
  - `webbrowser.open` accepts only the `Name` node `STAR_URL`.
  - `_shipped()` includes `install.sh`, `uninstall.sh`, `statusline/install-statusline.sh`; a shell lint (regex over `curl|wget|nc |python3? -c|base64 -d|eval`) fails on them; SECURITY.md:25's "install scripts in scope" becomes true.
  - Docstring (tests:2032-2037) lists the categories covered and repeats "regression guard, not a proof".
- **Effort.** M (0.5–1 day). **Bet against:** no.
- **Dependencies.** None.
- **Closes.** `02-security.md F1`.

### N2 — GitHub Actions pinned by commit SHA (rider on N1)

- **Outcome.** `ci.yml` references `actions/checkout` and `actions/setup-python` by full 40-char SHA with a `# vX.Y.Z` comment; dependabot (already watching `github-actions`, dependabot.yml:12-15) keeps the pins moving.
- **Acceptance criteria.** No floating tag in `.github/workflows/`; CI green; dependabot config unchanged.
- **Effort.** S (15 minutes). **Bet against:** no.
- **Dependencies.** None; same PR as N1 is fine.
- **Closes.** `02-security.md F5`. Included as a rider because F5's only payoff for an attacker is forging the green check N1 produces — not because of its (Low) severity.

**Now total: ~1 day, one PR, test/CI files only.**

---

## Next (this month)

Ordering principle: settle the line-count gate (X1), fix what users actually hit (X2, X3), make every state self-explanatory (X4), make macOS-shaped code testable before any macOS-shaped feature (X5), then hygiene and docs (X6, X7). X2, X5, X6 do not touch `tracker.py` and can start before Q1 is answered.

### X1 — The line-count promise is a checked bound, not a hand-counted exact number

- **Outcome.** README.md, docs/index.html and CHANGELOG state one phrase for the size of `tracker.py` and the capture script; CI fails when either file exceeds the bound or when the documents disagree with each other. The three-commits-per-release recount churn (Phase 0 §9: `21f6edc`, `df03837`, `b476a2b`) stops. *(Brain: this changes a README claim → `context.md` + `decisions/`.)*
- **Acceptance criteria.** A test (or CI step) asserts `wc -l tracker.py ≤ BOUND` and `wc -l statusline/tokease-statusline.py ≤ BOUND_SCRIPT`, and greps README.md and docs/index.html for the same phrase; a deliberate +1 line over the bound goes red; Brain updated in the same session.
- **Effort.** S (0.5 day). **Bet against:** no.
- **Dependencies.** **Owner answer to Q1** (bound vs exact). If the owner keeps the exact number, this item becomes an equality check and X3/X4 each carry a compression tax noted below.
- **Closes.** `01-design.md D5`.

### X2 — Two parallel Claude Code sessions cannot make an old reading look fresh or re-fire an alert

- **Outcome.** The capture script's "keep the measurement's timestamp" rule is keyed on the measurement, not on byte-equality with the current file; a re-render from an idle session cannot restamp or lower a window's `used_percentage` inside the same `resets_at` (M6 becomes enforced, which is what display-strategy.md:198 already claims). `statusline.err` is bounded (P18). The spec gains a parallel-session scenario and its over-strong F4 claim is corrected.
- **Acceptance criteria.** Test: session A (idle, 60 %, old `resets_at`) and session B (active, 70 %, same `resets_at`) alternate renders → file keeps 70 % and B's `captured_at`; A's re-render neither restamps nor lowers; after `resets_at` passes, a lower value is accepted again; existing script tests (tests:1431-1683) green; `statusline.err` truncated or rotated at a fixed size (e.g. 64 KiB); display-strategy.md §6 has the scenario, :303 (F4) reworded; `docs/specs/statusline-data-source.md:48` describes the real `captured_at` semantics (§6 #2, coordinated with X7).
- **Effort.** M (1 day). **Bet against: yes, mildly.** The upstream behaviour "an idle session re-sends its last values on every re-render" is the spec's own statement (display-strategy.md:96-99), not observed in this environment. The fixture may not model the real cadence; verify on a Mac with two terminals before release. Also a design choice between the two rules Phase 1 lists — Phase 4 should record it in the spec (an ADR only if it changes a visible promise).
- **Dependencies.** None (script only; the script's own line count is claimed in README.md:4 — covered by X1's `BOUND_SCRIPT` but not blocked by it).
- **Closes.** `01-design.md P6, M6, P18, §6 #8`; `§5 #25` → solid without caveat.

### X3 — Single instance, no flicker, honest `~` after sleep, no false "fresh forever"

Four small `tracker.py` fixes bundled because each is S and they share the refresh/age code.

- **Outcome.**
  - A second Tokease process exits silently instead of showing a second icon (P16).
  - The title is blanked to "..." only until the first reading has ever been shown; afterwards a refresh keeps the last title until the new one is ready (P5).
  - The `~` marker appears at 20 minutes regardless of the refresh interval or a sleep/wake, via a cheap timer that re-runs `_update_display` on the cached reading with no file read (P14).
  - `_captured_at` treats non-finite values and timestamps more than 5 minutes in the future as "unknown" (existing `~`/⚠ path); desktop `t` is sanity-checked for magnitude; readers catch `RecursionError` with `JSONDecodeError`; files over 8 MiB are `error`; `_render_dynamic_icon` tightens a pre-existing `~/.tokease` like the script does (P15, M3, F6, F7).
  - One test runs with `_TITLE_SPACER` at its real value (§5 #24).
- **Acceptance criteria.** Test: lock held on `~/.tokease/tracker.lock` → `App()` raises `SystemExit(0)`; test: after one successful render, `_refresh` leaves `self.title` unchanged; test: with interval 3600 s and a cached reading aged 25 min, the marker timer produces `~`; the F6 table inputs (year-2100 `t`, `NaN`, `1e400`, `captured_at` +31 y, 100 000-deep array) all end in `~`/⚠ or `error`, never a fresh-looking value; `install.sh:136-138`'s single-launch comment removed or reworded.
- **Effort.** M (1–1.5 days). **Bet against:** P5 only, medium — the flicker is inferred from code, not observed; if rumps coalesces title writes it may be invisible in practice, in which case drop that bullet rather than add lines for it.
- **Dependencies.** X1 (adds ~40 lines; under an exact-1,000 rule these must be found elsewhere).
- **Closes.** `01-design.md P16, P5, P14, P15, M3, §5 #24`; `02-security.md F6, F7`.

### X4 — Every state explains itself: per-source status, `schema`/`version` checked, `?` with a reason

- **Outcome.** The reader→merge→view contract is a small `Reading` dataclass with a `SourceStatus` per source; the dropdown carries one line per source (e.g. "Claude Code: idle 3 h · Claude app: unknown format"); the `?` state rewrites the rows and names `~/.tokease/statusline.err`; `usage.json`'s `schema` and the desktop `version` are checked and an unknown value reads as "unknown format", never as "waiting"; desktop samples are picked by `max(t)`, not file order (M1); the source label comes from a table, not a ternary with a default (M4); desktop-only users never see "awaiting Claude Code" (P9); README.md:110 says what the code does. This is the "self-diagnosing screen" that README.md:108-117 currently substitutes for.
- **Acceptance criteria.** Tests for each status per source (absent / present-no-windows / unreadable / unknown-version / ok / idle N); a schema-2 `usage.json` renders "unknown format"; a desktop file with `version: 3` gives "unknown format" for that source while a fresh statusline still shows; the `?` state's three rows are rewritten; out-of-order desktop samples pick the latest `t`; `_meta` reads collapse to attribute access; display-strategy.md A7 (:614-616) closed; README.md:110 matches.
- **Effort.** M–L (1.5–2 days). **Bet against: on line count, yes** — this is +60–100 lines in `tracker.py` and is the item that forces Q1; it cannot land under an exact-1,000 rule without compressing unrelated code.
- **Dependencies.** X1. X3 first (shares the reader code).
- **Closes.** `01-design.md D3, A2 (typed contract), A3, P9, P12, P13, M1, M2, M4, §6 #4, §6 #6`; `§5 #8, #20` → solid.

### X5 — macOS CI lane, so AppKit-shaped code is executed somewhere before users run it

- **Outcome.** A `macos-latest` job installs `requirements.txt` (real rumps, PyObjC, Pillow) and runs the suite with zero skips; a smoke test asserts `_render_dynamic_icon` writes a 44×44 PNG; a real `NSUserDefaults` round-trip runs in a throwaway domain; `_is_login_item`/`_set_login_item`/`_toggle_login`/`_get_app_path` have unit tests with `subprocess.run` mocked (they currently have none).
- **Acceptance criteria.** CI matrix shows the macOS job; its skip count is 0; a deliberate break in `_render_dynamic_icon` goes red only on macOS (documenting that the Linux lane cannot catch it); the ubuntu jobs are unchanged; `TestMainThreadMarshalling` is either extended to exercise `AppHelper.callAfter` or its docstring states that it only checks routing.
- **Effort.** M (0.5 day for the job, +1 day for the defaults and login-item tests). **Bet against: yes.** No macOS is available in this environment; rumps instantiates `NSApplication`, which may need adjustments on a headless runner (the test doubles avoid `App.run`, so probably fine, but unverified). Budget an extra half day for runner quirks. GitHub-hosted macOS runners are free for public repositories, so cost is not the risk.
- **Dependencies.** None. Must land before L3, L4, L5b, L7 — Phase 1 D4: a CoreGraphics renderer would otherwise be 0 % executed in CI.
- **Closes.** `01-design.md D4`; `§5 #1` ("skipped here"), `#15` ("zero tests"), `#17` ("never exercised against real defaults").

### X6 — Installer hygiene with a shell test

- **Outcome.** `~/.claude/settings.json` keeps its original mode across the jq rewrite (umask 077 / `install -m`, `cp -p` for the backup); `uninstall.sh` removes the `statusLine` block only when `.statusLine.command` names our script, not when the marker appears anywhere in the file; `install-statusline.sh`'s "already exists" check tests `.statusLine != null`; PRIVACY.md says backups may contain `env`/`apiKeyHelper` values; a shell test runs on the ubuntu lane (jq is available there).
- **Acceptance criteria.** Test cases: (1) a 0600 settings file stays 0600 after install and after uninstall; (2) a file whose `statusLine.command` is the user's own script but whose `permissions.allow` mentions `tokease-statusline.py` is left intact by uninstall; (3) a `statusLine` block without `command` is not overwritten by install; (4) the happy path still wires and unwires. PRIVACY.md sentence present; uninstall output mentions the backups.
- **Effort.** S–M (0.5 day). **Bet against:** no.
- **Dependencies.** None. N1's shell lint applies to the changed scripts.
- **Closes.** `02-security.md F2, F3`; `01-design.md §5 #27, #29` ("shell untested") partially.

### X7 — Docs and ADRs match the code

- **Outcome.** ADR 0002 carries a "revised by ADR 0003" banner like ADR 0001; `statusline-data-source.md` header no longer says "only data source", :48 describes the real `captured_at` rule, :72-74 mentions the `~` title marker; display-strategy.md R9 and ADR 0003:56-57 list `NSUserDefaults` as the one write outside `~/.tokease` (as PRIVACY.md already does); ADR 0003:95-96 says `org` handling is *deferred (CHOICE-6)* instead of *must*.
- **Acceptance criteria.** Each of the six locations edited; no code change; a grep for "only data source" in `docs/` returns nothing.
- **Effort.** S (0.5 day). **Bet against:** no.
- **Dependencies.** X2 first (so the `captured_at` sentence describes the final rule). The README "Features" list (§6 #10) is deliberately **not** in this item — it depends on Q2.
- **Closes.** `01-design.md §6 #1, #2, #3, #5, #7; A6`.

**Next total: ~7–9 days.** X2, X5, X6 can start immediately; X1 → X3 → X4 wait on Q1.

---

## Later (this quarter)

Ordered so dependencies land first. Items L1–L2 are the debt that every ROADMAP polish idea and most v1.1 candidates would otherwise pay repeatedly (Phase 1 §4 grounding).

### L1 — One window registry drives reader, merge, rows, icon and scheduling

- **Outcome.** A single `WINDOWS` table `(key, label, span, radius, alerts?)` replaces the nine literal `("five_hour", "seven_day")` sites, the two near-duplicate display blocks and the hand-passed spans; `assets/build-menubar-icon.py` reads the same geometry instead of a "must stay consistent" comment. Adding a window is a table row.
- **Acceptance criteria.** A test that appends a synthetic third window to the table yields a third row, a third ring and a third reset-schedule candidate with no other edit; `test_two_rings_only` re-expressed against the table; all existing window tests green; grep for the literal tuple returns only the table.
- **Effort.** M (1 day). **Bet against:** no.
- **Dependencies.** X1, X4 (the typed `Reading` is what the table indexes).
- **Closes.** `01-design.md D1, A7, M5`. Prerequisite for L3, L4 and v1.1 candidate 5.

### L2 — View computation is a pure function; alert state is data, not a side effect

- **Outcome.** `compute_view(reading, alert_state, now) -> (View, AlertState, events)` owns row text, the ADR 0004 guard, threshold crossings, freshness label and title; `_update_display` shrinks to `_apply(view)` plus the icon write; the ADR 0004 ordering is data flow rather than a call order pinned by one test; the previous percentage per ring is available to the view layer.
- **Acceptance criteria.** Tests 719-805 (ADR 0004) and the display tests pass through the pure function; no `_last_pct`/`_last_reset` mutation inside display code; `_maybe_notify` no longer mutates state it does not own; the ADR 0004 implementation note updated.
- **Effort.** M (1 day). **Bet against:** no.
- **Dependencies.** L1 (so the view is per-window from the first version).
- **Closes.** `01-design.md D2, A4`. Prerequisite for L4, L5b, and v1.1 candidate 4's "(estimated)" title.

### L3 — Ring icon drawn with CoreGraphics; Pillow dropped (ROADMAP "Tracked polish ideas", 4th)

- **Outcome.** Rings rendered via Quartz from the L1 geometry; `Pillow` removed from `requirements.txt`, `build.sh`, `ci.yml`; README/index.html dependency claims updated ("two small dependencies" → one) *(Brain)*; the template-icon fallback remains for the no-Quartz case.
- **Acceptance criteria.** The macOS lane renders the icon and compares it to a checked-in Pillow baseline within a tolerance; ubuntu lanes skip the renderer tests with an explicit reason; a missing Quartz import degrades to the template icon (existing E7 path); the tripwire allow-list (N1) admits `Quartz` without edits.
- **Effort.** M–L (1.5–2 days). **Bet against: yes.** No Mac here. rumps exposes the icon as a file path (`self.icon = str(path)`, tracker.py:885) so the per-render disk round-trip stays unless rumps internals (`NSStatusItem` + `NSImage`) are used directly — Phase 1 §4 note, unverified. Budget +1 day.
- **Dependencies.** X5 (mandatory — otherwise the new renderer never runs in CI), L1.
- **Closes.** ROADMAP polish item 4; `01-design.md §4` trailing note on the file-path icon API.

### L4 — Ring clear-out animation on reset (ROADMAP polish, 3rd)

- **Outcome.** When a window resets, its ring animates from the previous fill to empty over ~400 ms (4–5 frames, `rumps.Timer`), then the normal render resumes.
- **Acceptance criteria.** Test: a reading whose 5h window went from 71 % to void triggers exactly one animation sequence for that ring, none for the other; frames stop on quit; no animation on first render or on error states.
- **Effort.** M (1 day). **Bet against: yes** — five icon writes in 400 ms through a file-path API, and `rumps.Timer` cadence under load, are unverified here.
- **Dependencies.** L2 (previous-per-ring state), L3 (do not write the frame renderer twice).
- **Closes.** ROADMAP polish item 3.

### L5 — Threshold alerts that users actually receive (ROADMAP polish, 2nd)

ROADMAP.md:45 lists two options and picks neither. This plan keeps both, ordered by cost; **which to ship is Q2.**

- **L5a — the menu bar item is the reminder.** *Outcome:* at ≥ 80 % / ≥ 95 % the title carries a visible marker (e.g. `95%!` or a ⚠) on every install, brew included; the "Alerts" toggle controls the marker so it stops being a no-op (§5 #14). *Acceptance:* tests for marker on crossing, off below, off when alerts disabled, re-armed on a new window; README "Features" wording updated *(Brain)*. *Effort:* S. *Dependencies:* Q2; X1. If Q2 says yes, pull this into Next — nothing else depends on it.
- **L5b — banner notifications under a real bundle identity.** *Outcome:* `UNUserNotificationCenter` alerts delivered on the Homebrew/source paths. *Acceptance:* the macOS lane asserts the request is issued under a bundle id; measured on a real Mac that the banner shows for a brew install. *Effort:* M. **Bet against: yes** — ROADMAP:45 says an ad-hoc signature is enough, but how a brew-installed interpreter process acquires a bundle identity (a stub `.app` in `libexec`? a signed launcher?) is undesigned; this could turn into L8's problem.
- **Dependencies.** L5b: L2, X5, and a bundle-identity design (likely L7/L8).
- **Closes.** `01-design.md P8; §5 #13, #14; §6 #10` (with Q2).

### L6 — Multi-org desktop history handled deterministically

- **Outcome.** The reader picks the `org` of the most recent sample and sticks to it for the session (no cross-org flapping); a picker only if a user asks.
- **Acceptance criteria.** Fixture with two orgs interleaved → the display follows one org consistently; ADR 0003 wording (X7) points to this as the implementation of CHOICE-6.
- **Effort.** S–M. **Bet against:** medium — no multi-org fixture exists; a real file from a two-org user is needed to know how samples interleave.
- **Dependencies.** X4.
- **Closes.** `01-design.md P7; §5 #8` remaining caveat.

### L7 — `.app`-readiness debt paid before any bundle ships

- **Outcome.** `setup.py` reads the version from `tracker.py` (no "keep in sync" comment); `_is_login_item()` is off the `__init__` path (lazy on menu open, or async) so a bundle launch never blocks 5 s on osascript; login-item functions unit-tested (from X5); settings keys namespaced (`tokease.*`) with a one-time read-old-write-new migration — done here rather than in Next because the bundle changes the preferences domain anyway, so this is one migration instead of two.
- **Acceptance criteria.** `python setup.py --version` equals `tracker.__version__`; `App.__init__` makes no subprocess call (test); a foreign `display_mode` in the shared `org.python.python` domain no longer affects Tokease (P3); old keys migrated once.
- **Effort.** M (1 day). **Bet against:** no.
- **Dependencies.** X5.
- **Closes.** `01-design.md P3, P4; §5 #15, #17, #30` partials.

### L8 — Signed and notarized `.app` as an *additional* install path (ROADMAP polish, 1st)

- **Outcome.** A `Tokease.app` that opens without the Gatekeeper dialog, published alongside — never instead of — Homebrew (ROADMAP.md:68, "What will never ship").
- **Acceptance criteria.** Notarization passes; a release workflow separate from `ci.yml` (which holds no secrets today, and should keep it that way) signs and staples; README lists it as the second option.
- **Effort.** M (1–2 days once unblocked). **Bet against: yes** — notarization pipelines are fiddly, and this repo has deliberately had no CI secrets.
- **Dependencies.** **Blocked on the owner**: Apple Developer Program fee, "worth the yearly fee if launch traction justifies it" (ROADMAP.md:44). Engineering prerequisites: L7, X5.
- **Closes.** ROADMAP polish item 1; makes `§5 #15` (launch at login) reachable.

### L9 — `jq`/shell variant of the capture (ROADMAP polish, 5th)

- **Outcome.** An optional shell capture with the same on-disk contract; the Python script stays the reference.
- **Acceptance criteria.** The X2 parallel-session test and the "never overwrite good windows with none" test run against both implementations; N1's shell lint passes on it; `statusline/README.md` documents the trade-off.
- **Effort.** M. **Bet against: yes** — keep-timestamp, never-overwrite-good-windows and the X2 rule (script:148-166) are more than a jq one-liner; expect a 40-line shell script and a second implementation to keep in sync.
- **Dependencies.** X2 and X7 (the contract must be final and written down before it is copied).
- **Closes.** ROADMAP polish item 5.

### L10 — Source-install lockfile with hashes (F4)

- **Outcome.** `install.sh`/`build.sh` install from a hash-pinned lockfile that includes transitive PyObjC; the `pip install --upgrade pip` step is pinned or dropped.
- **Acceptance criteria.** `pip install --require-hashes -r requirements.lock` succeeds on macOS arm64 and x86_64 for py3.10–3.13; dependabot or a documented refresh command keeps it current.
- **Effort.** S–M. **Bet against: yes** — `--require-hashes` needs hashes for every platform wheel PyObjC ships across four Python versions and two architectures; `pip-compile` on one Mac yields one platform's set (`uv pip compile --universal` may be needed).
- **Dependencies.** None. Low priority: Homebrew is the recommended path and is claimed hash-pinned (not verifiable here).
- **Closes.** `02-security.md F4`.

### L11 — v1.1 candidates: blocked on the owner's product decision, not sequenced here

ROADMAP.md:24: *"Which one (if any) gets built depends on adoption and on what launch feedback actually asks for."* ROADMAP.md:28: *"Pick one of the following… Not two of them. Not all seven."* This plan does not pick. What it can say is which in-repo prerequisite each candidate would need, so the owner's choice lands on paid-down debt:

| ROADMAP candidate | In-repo prerequisite from this plan | Other blocker |
|---|---|---|
| 1. iPhone companion | none in this repo | transport ADR first (ROADMAP:30) |
| 2. Second tool (Cursor/Lovable) | X4 (third source, its own status line) | vendor exposes an authorized feed |
| 3. Per-window context tracker | X4 (opt-in source) | JSONL drift |
| 4. Drift estimator | X4 + L2 ("(estimated)" title variant) | opt-in ADR + privacy note |
| 5. Per-model windows | L1 (registry: "a table row") | **upstream** — claude-code#73770 |
| 6. Usage insights | X4 (opt-in source) | JSONL drift; opt-in ADR |
| 7. API-billing mode | X4 + a separated mode | network → opt-in ADR (ROADMAP:65) |

**Later total: ~10–13 days of unblocked work (L1–L4, L6, L7, L9, L10), plus L5b/L8 once the owner unblocks them.**

---

## Not doing

### Ruled out by ROADMAP.md "Explicitly out of scope for v1.0" (:11-20)

- **iPhone/iPad app** as v1.0 work — 1–2 months before the menu bar version is validated. (Remains v1.1 candidate 1, owner's call.)
- **Web dashboard** — needs a relay off the machine; breaks the trust argument.
- **Windows/Linux ports** — `rumps` is macOS-only; fork-friendly, not maintained here.
- **Other AI tools' quotas** — each is a vendor break-point. (Remains v1.1 candidate 2.)
- **Per-session token breakdown** — JSONL parsing that drifts with the CLI.
- **Sparkle/auto-update** — `brew upgrade` is the update path.

### Ruled out by ROADMAP.md "What will never ship" (:61-68)

- **No backend, relay, phone-home, telemetry, analytics, paid tier, unsigned `.app` as default.** Consequence for this plan: no item above adds a network path, an update check, or an install path that bypasses Homebrew; L8 is explicitly *additional*.

### Phase 1 / Phase 2 findings deliberately not actioned

- **F6 beyond the cheap clamp in X3** (full defence against crafted local JSON). Phase 2's own threat model: a process running as the user already holds more than the app does; hardening past "degrade honestly" is theatre. Low, theoretical.
- **F8, F9 (Info).** Nothing to do; recorded as positive findings.
- **P11 — persisting `_last_reset` (ADR 0004 option B).** ADR 0004 chose option A deliberately; the exposure is bounded to one desktop cadence and documented. Revisit only on a user report.
- **A5 — thread-affinity edge in `_refresh`.** Sound today; all callers are main-thread.
- **M7 — "sorted ascending" comment.** Harmless.
- **§6 #9 — primary/secondary wording.** Phase 1: consistency only, no action.
- **Enterprise/Team plan support** (ROADMAP polish, 6th). Blocked upstream on a credit-style statusline signal; nothing to build.
- **Per-model windows via `cachedUsageUtilization`.** Rejected by ROADMAP.md:34 — undocumented internal state, same reasoning as the privacy invariant.
- **Replacing `rumps`** (unmaintained ~3 years, F4). It is one of two dependencies, works, and has no drop-in alternative; a rewrite is L and outside every stated scope.
- **Test-file refactor** (six `_make_app` copies, one 2,222-line module). Cosmetic; fold opportunistically into X4/L2, never as its own PR.
- **Full typing beyond X4** (typed settings, typed view before L2). Diminishing return at 1,000 lines.
- **A coverage-percentage gate in CI.** 196 tests over ~1,450 shipped lines; a number would not change behaviour. X5 (executing the macOS paths at all) is the real gap.
- **`§5 #34` — rumps app name `"Claude"`.** A one-line change with no behavioural finding behind it; not raised as a question because Phase 1 only *noted* it. Mention to the owner in passing if L5b puts that string on a notification banner.

---

## Questions for the product owner

ROADMAP.md answers almost everything. Two things it does not:

1. **Q1 — The "1,000-line" claim: exact number or bound?** Phase 1 D5 recommends a checked bound ("under 1,200 lines") because the exact count has cost three commits of recount churn and creates an incentive to write denser code. The three latest release commits suggest you care about the exact figure. Blocks X1, and in practice X3 and X4 (+60–100 lines). Under "exact", every code item in Next pays a compression tax.

2. **Q2 — Alerts: which of ROADMAP.md:45's two options, and what does the README say meanwhile?** (a) May the cheap option — the menu bar item itself as the ≥ 80 %/95 % reminder (L5a, S, works on every install) — ship now, in Next, independently of any later banner path? (b) Until an alert path is delivered on the distributed installs, should README.md:36-42 "Features" keep listing threshold alerts and launch-at-login as features of a build that is not shipped (§6 #10)?
