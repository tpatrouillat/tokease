# Phase 1 — Design & Architecture Audit

Date: 2026-09-10. Scope: `tracker.py` (1,000 lines), `statusline/tokease-statusline.py` (178), `tests/test_tracker.py` (2,222), installers, ADRs 0001–0004, the three specs, README, ROADMAP. Builds on `docs/scan/00-inventory.md` (Phase 0); nothing there is re-derived. Read-only: no edits, no installs.

What was verified on this machine (Linux, no Pillow, no rumps):

- `python3 -m unittest discover -s tests` with an isolated `HOME`: **196 tests run, OK, 4 skipped** (Pillow absent). 196 = 188 methods + 8 re-runs, because `TestDesktopSource` inherits `TestStatuslineSource` (tests/test_tracker.py:1041-1044, documented as intentional).
- `wc -l`: tracker.py = 1000, capture script = 178, exactly what README.md:4 claims.
- Not found here: the Brain page `~/ThibOS/brain/projects/Tokease/context.md` (imported by CLAUDE.md), `graphify-out/`, any git tag, and the Homebrew formula (lives in `tpatrouillat/homebrew-tap`). Claims about those are marked "not verifiable here".

Finding format: **Evidence** (file:line) · **Impact** · **Effort** S/M/L · **Confidence** high/med/low.

---

## 1. Architecture

### 1.1 Module map (what actually exists)

`tracker.py` is one module organised by comment banners, not by imports. Line ranges:

| Section | Lines | Contents |
|---|---|---|
| Runtime shims | 32-66 | `_call_on_main` (PyObjC or inline fallback), Pillow optional, `NSUserDefaults` optional, Dock-icon suppression via `NSBundle` |
| Icon rendering | 68-136 | `_resolve_icon_path`, `_render_dynamic_icon` (Pillow → PNG in `~/.tokease`) |
| Constants | 141-204 | intervals, thresholds, display modes, settings keys, file paths, stale/window spans, version |
| Settings | 210-228 | `_settings_get/_settings_set` over `NSUserDefaults` |
| Login item | 235-283 | `_get_app_path`, `_is_login_item`, `_set_login_item` (osascript) |
| Helpers | 290-343 | `_safe_int`, `_display_pct`, `_epoch_to_iso` |
| Sources + merge | 349-516 | `_read_statusline_usage`, `_desktop_sample_to_data`, `_read_desktop_usage`, `_captured_at`, `_merge_window`, `_merge_usage`, `fetch_usage` |
| Time formatting | 523-579 | `_humanize_age`, `_parse_iso`, `fmt_reset` |
| `App` | 586-996 | menu construction (588-693), settings callbacks (699-741), `_maybe_notify` (743-785), timers (787-824), refresh pipeline (830-875), display (877-996) |

`statusline/tokease-statusline.py` is a stdlib-only process spawned by Claude Code per render: read stdin → extract windows (58-69) → read current file (79-88) → keep timestamp if unchanged (148-155) → skip write if payload is windowless and file has windows (161) → atomic write (91-103) → print line (106-117, 170).

Shell: `install.sh` (venv + LaunchAgent), `statusline/install-statusline.sh` (copy script + jq-edit `~/.claude/settings.json`), `uninstall.sh`. `setup.py` + `build.sh` build a py2app bundle that is **not distributed** (ROADMAP.md:44, 68).

### 1.2 Data flow (as coded)

```
Claude Code ──stdin JSON──▶ tokease-statusline.py ──os.replace──▶ ~/.tokease/usage.json  (schema 1, epoch s)
Claude Desktop ────────────────────────────────────────────────▶ ~/Library/Application Support/Claude/plan-usage-history.json  (version 2, epoch ms)

tracker.py, every `interval` s (rumps.Timer, 790) or on reset+5s (threading.Timer, 821) or menu "Refresh":
  _refresh (830)  title="..." ; spawn worker thread
   └─ _fetch_and_update (834) ── fetch_usage (503)
         ├─ _read_statusline_usage (349) → (dict|None, err∈{nostatusline,waiting,error,None})
         ├─ _read_desktop_usage (406)    → dict|None            (no error channel)
         └─ _merge_usage (461)           → fresher wins, per-window guards (_merge_window 437)
      _call_on_main → _apply_usage (845) → error glyphs (853-873) or _update_display (942)
         ├─ _window_row ×2 (907)  → row text + pct-or-None (reset / age-ceiling voids)
         ├─ _predates_last_reset (891, ADR 0004)  → may void 5h
         ├─ _maybe_notify (743)   → mutates _last_pct/_last_reset, may notify
         ├─ _freshness_label (927), _render_dynamic_icon (98) → PNG on disk
         ├─ _apply_display (877)  → title/icon per display_mode
         └─ _schedule_reset_refresh (793)
```

Normalised in-memory shape (undocumented outside docstrings): `{"five_hour": {"utilization", "resets_at": ISO|None}, "seven_day": {...}, "_meta": {"captured_at": epoch s, "source": "statusline"|"desktop"}}` (tracker.py:370-381, 396-403).

### 1.3 Where state lives

| State | Where | Evidence | Survives restart |
|---|---|---|---|
| `interval`, `alerts_enabled`, `display_mode`, `title_weekly` | `NSUserDefaults` (4 un-namespaced keys) | tracker.py:159-162, 591-596, 709/715/723/730 | yes — under `com.tpatrouillat.tokease` for the .app, **`org.python.python` shared domain for brew/source** (PRIVACY.md:46-53) |
| `_last_pct`, `_last_reset` (alert baseline + ADR 0004 evidence) | in-memory only | tracker.py:611-612, 899 | no (documented, ADR 0004:117-119) |
| `_timer`, `_reset_timer`, `_app_path` | in-memory | 605-607 | no |
| last capture | `~/.tokease/usage.json` | script:33, 100 | yes |
| capture errors | `~/.tokease/statusline.err` | script:34, 48-55 | yes, append-only, never rotated |
| rendered icon | `~/.tokease/tokease-icon.png` | tracker.py:86, 132 | rewritten every render |
| desktop history | read-only | 170-172, 414 | n/a |
| statusline wiring | `~/.claude/settings.json` | install-statusline.sh:11, 65-69 | yes |
| auto-start | LaunchAgent plist | install.sh:22, 94-118 | yes |

### 1.4 Findings

**A1 — The ADRs are implemented as written; the code matches the intended design.**
Evidence: ADR 0001/0002 (statusline via stdin, no token, no endpoint) → tracker.py:349-381, script:120-170, guarded by `TokenFreeInvariantTest` (tests:2026-2185, AST-based, covers all 4 shipped .py files per `git ls-files`, 2074-2090). ADR 0003 (desktop secondary, version 2 pin, fresher wins) → tracker.py:406-426, 461-500. ADR 0004 option A (in-memory guard before notify) → tracker.py:891-904, 954-959, pinned by tests:776-792. · Impact: none — this is the baseline; no re-litigation needed. · Effort: – · Confidence: high.

**A2 — Layering exists only as comment banners; the reader→merge→view contract is an untyped dict with a `_meta` side-channel.**
Evidence: tracker.py:370-381 vs 396-403 build the same shape by hand; `_meta` is read in five places (432, 490-492, 495, 944, 978); `source` is stringly compared at 937 with a default of "Claude Code" for anything unknown. Test isolation has to monkeypatch module globals (`_STATUSLINE_FILE`, `_DESKTOP_HISTORY_FILE`, tests:963-970; `_DEFAULTS`, tests:82; `_TITLE_SPACER`, tests:85). · Impact: acceptable at 1,000 lines, but every new source or field is a convention to remember rather than a type to satisfy (see D3). · Effort: M · Confidence: high.

**A3 — Error channels are asymmetric: the statusline reader returns a code, the desktop reader returns `None`, and `fetch_usage` forwards only the statusline code.**
Evidence: tracker.py:349-381 (`nostatusline|waiting|error`), 406-426 (any anomaly → `None`), 510-516 (`if desktop is None: return statusline, err`). · Impact: the UI cannot distinguish "desktop app not running" from "desktop file present but version ≠ 2 / unreadable"; both render the ⚙ guide "open the Claude desktop app" (853-860). display-strategy.md:614-616 (A7) records the wording, but the root cause is structural. · Effort: S–M · Confidence: high.

**A4 — `_update_display` is the app's only orchestration point and it mixes six concerns with an order that matters.**
Evidence: tracker.py:942-996 does row formatting, ADR 0004 guard, alert-state mutation (via `_maybe_notify`, which also writes `_last_reset`, 755-763), freshness label, icon file write, title assembly, and reset scheduling. ADR 0004:110-114 acknowledges the implicit ordering and pins it with a test rather than structure. · Impact: every display feature on the roadmap (third ring, animation, "(estimated)" marker) lands in this method (see D2). · Effort: M · Confidence: high.

**A5 — Threading model is sound; one thread-affinity edge is unguarded.**
Evidence: worker thread at 832; results marshalled with `_call_on_main` (843); reset timer marshalled (821). `_refresh` itself sets `self.title` on the calling thread (831) — callers are the rumps timer, menu callbacks, `__init__` and the marshalled reset timer, all main-thread, so this is fine today. The non-Mac fallback `_call_on_main` runs inline (37-39), so tests never exercise the real marshalling; `TestMainThreadMarshalling` (tests:388-420) only checks the call is routed. · Impact: low. · Effort: – · Confidence: med (rumps not installed here).

**A6 — The invariant "writes confined to `~/.tokease`" is stated in the spec but the app also writes `NSUserDefaults`.**
Evidence: display-strategy.md:182-184 (R9), ADR 0003:56-57 ("no write outside `~/.tokease`") vs tracker.py:221-228 (`setObject_forKey_` + `synchronize`), which writes `~/Library/Preferences/…`. PRIVACY.md:28-29, 46-53 discloses it correctly. · Impact: doc/spec precision only; no privacy issue (preferences carry no usage data). Listed in §6. · Effort: S (doc) · Confidence: high.

**A7 — Window knowledge is duplicated across the two shipped files and inside each.**
Evidence: literal `("five_hour", "seven_day")` at tracker.py:371, 397 (as `fh/sd`), 473, 481, 496, 804 and script:75, 109, 135, 149; ring geometry `(20, 14)` at tracker.py:93 and assets/build-menubar-icon.py:23 with a "must stay consistent" comment (88-89); the 5h and weekly blocks in `_update_display` are near-copies (951-968 vs 971-975). By design (single file, no shared module), but it is the coupling that a third window would hit (see D1). · Effort: M · Confidence: high.

---

## 2. Product design — the journey, end to end

### 2.1 Install → first run

**P1 — Homebrew is the recommended path but the in-app setup guide gives a repo-relative script path.**
Evidence: tracker.py:858 `"Or wire the CLI: run statusline/install-statusline.sh"`; README.md:103 shows the brew layout is `$(brew --prefix)/opt/tokease/libexec/…`. The formula itself is not in this repo (not verifiable here). · Impact: the ⚙ state's second line is not actionable for the majority install path; the user has to go to the README. · Effort: S · Confidence: med.

**P2 — First run with nothing wired: handled well.**
Evidence: `nostatusline` → ⚙ title + three guide rows, icon cleared (tracker.py:848-860); tested (tests:1401-1428). `waiting` → "…" + two rows (862-869). · Impact: the empty state is explicit. · Confidence: high.

**P3 — First run for a Homebrew/source user starts under a shared preferences domain with un-namespaced keys.**
Evidence: keys `display_mode`, `alerts_enabled`, `interval_secs`, `title_weekly` (tracker.py:159-162) written to `org.python.python` (PRIVACY.md:49-53). Startup clamps/validates each value (591-596; tests:364-386, 834-850) so a foreign value cannot crash, but it can silently change the user's display mode. · Impact: low probability, confusing when it happens; also the uninstall leaves them (PRIVACY.md:46). · Effort: S (prefix keys `tokease.*`, or use `NSUserDefaults.persistentDomainForName_`) · Confidence: high.

**P4 — `.app`-only startup cost: `_is_login_item()` runs osascript synchronously in `__init__`.**
Evidence: tracker.py:625, with a 5 s timeout (254); triggers the Automation permission prompt on first launch. Only reachable when frozen (621). · Impact: nil for shipped paths; a 5 s hang for anyone who builds the bundle. · Effort: S · Confidence: high.

### 2.2 Normal operation

**P5 — Every refresh blanks the title to "..." before the worker runs.**
Evidence: tracker.py:831 `self.title = "..."` in `_refresh`, called by the rumps timer every `interval` s (790, minimum 60 s, 141) and by every settings change (719, 726). The icon is not cleared, so in `both` mode the rings stay while the number flickers; in `icon` mode the text "..." appears next to the rings; in `pct` mode the number vanishes. If a fetch is slow (e.g. a large desktop history file read in full, 414) "..." persists. · Impact: visible flicker up to once a minute; a "loading" state shown for a read that normally takes milliseconds. Not covered by the spec's scenario matrix (display-strategy.md §6 never mentions it). · Effort: S (only set "..." when no data has ever been shown) · Confidence: med (behaviour inferred from code; not observed here).

**P6 — Two Claude Code sessions in parallel make the capture ping-pong and defeat the "keep the measurement's timestamp" rule.**
Evidence: script:148-155 keeps `captured_at` only when the payload equals *the file's current content*. display-strategy.md:96-99 documents that an idle session re-sends its last response's values on every non-quota re-render. With session A idle (old values) and session B active (new values), each A re-render differs from B's file and is stamped `now`, then B's next render differs from A's and is stamped `now`: the old reading is repeatedly shown as fresh, the title alternates, and a drop-then-recross re-fires the 80 % alert (tracker.py:769; tests:658-663 asserts re-alert on `[85, 50, 85]`). No mention of parallel/concurrent sessions in `docs/` (grep: none). · Impact: exactly the failure class FIXED-4 was written to remove (old values outranking a truer desktop sample, duplicate alerts), reachable by anyone who keeps two terminals open. · Effort: M (e.g. never let a capture lower a window's `used_percentage` inside the same `resets_at` — a variant of CHOICE-2 — or key the identity check on `resets_at`+pct across the last N captures) · Confidence: med-high (logic read; upstream re-render behaviour is the spec's own statement).

**P7 — Multi-org desktop history: the last sample wins regardless of `org`.**
Evidence: tracker.py:389-403 never reads `org`; ADR 0003:95-96 says the field "must be respected"; display-strategy.md:603-605 defers it (CHOICE-6). · Impact: a user with two orgs gets numbers from whichever org sampled last. · Effort: S–M (pick the org of the most recent sample and stick to it; or expose a picker) · Confidence: high.

### 2.3 Quota nearing the limit

**P8 — The 80 %/95 % alert is a no-op on every distributed install, and there is no fallback attention signal.**
Evidence: `rumps.notification` (tracker.py:774-778) only shows a banner under the .app's bundle id (README.md:31, ROADMAP.md:45, CHANGELOG v1.0.4); the .app is not distributed (ROADMAP.md:44, 68). The toggle still persists (728-731) and is labelled "(.app build only)" (655-656). Nothing else changes at ≥ 95 %: title, icon and rows are the same as at 50 % (942-994). · Impact: the "quota nearing limit" step of the journey has no signal beyond reading the number. The ROADMAP:45 option "ship the menu bar item as the reminder" is unimplemented. · Effort: S for a text marker (e.g. `95%!`), M for `UNUserNotificationCenter` under a real bundle · Confidence: high.

**P9 — Desktop-only users see Claude Code wording in reset states.**
Evidence: row text `"— (reset; awaiting Claude Code)"` (tracker.py:921) is reached by desktop-only users via `_merge_window` (457) and via the one-shot timer; ADR 0004's variant says "awaiting a newer sample" (958). display-strategy.md:612-613 records this. · Impact: wording only. · Effort: S · Confidence: high.

### 2.4 Reset

**P10 — Reset handling is the strongest part of the product.**
Evidence: past `resets_at` voids the row and ring (920-921); the age ceiling voids readings that outlived their window (922-923, 180-181); one-shot re-render 5 s after the soonest future reset (793-824), cancelled/replaced per render (798-800); ADR 0004 guard (891-904); baseline re-anchor at 0 on a voided window (966). All tested (tests:425-480, 719-805, 1853-2024). · Impact: positive. · Confidence: high.

**P11 — Restart inside a reset gap reopens C7 (known, documented).**
Evidence: `_last_reset` in memory only (tracker.py:611-612, 899); ADR 0004:117-119. · Impact: bounded to one desktop cadence (p90 45 min, ADR 0004:28-30). · Effort: M (option B of ADR 0004) · Confidence: high.

### 2.5 Error, offline, stale, sleep, clock

**P12 — The `?` state has no explanation in the dropdown, and the rows keep whatever they showed before.**
Evidence: tracker.py:871-873 sets only `self.title = "?"`; `m5h/m7d/mupd` are untouched (compare 857-859 and 867-868 which rewrite them). On a first-run corrupt file the rows still read "5-hour: ..." / "Weekly: ..." (615-616); on a later corruption they show the previous percentages under a "?" title. display-strategy.md:151-154 (R6) and :203 promise "with the reason in the dropdown". · Impact: a dead-end — nothing tells the user to look at `~/.tokease/statusline.err` (README.md:114 does, the app doesn't). · Effort: S · Confidence: high.

**P13 — Upstream format change is indistinguishable from "client idle".**
Evidence: if Claude Code stops sending `rate_limits`, the script writes nothing while a good file exists (script:157-166) → the app shows the last capture ageing with "(Claude Code idle?)" (939) forever. If the desktop file's `version` changes, the reader returns `None` (417) → ⚙ "open the Claude desktop app" (857) for desktop-only users, or silent fallback to a stale statusline capture. The `schema` field the script writes (script:35, 130) is never read by the app (tracker.py:364-380). README.md:110 says "Tokease detects that and falls back"; detection exists only for the desktop `version` key. · Impact: the README's own "if the rings stop moving after a Claude update" section (108-117) is the user-facing mitigation, because the app cannot say "format changed". · Effort: S–M (surface per-source status: present/absent/unreadable/unknown-version in the dropdown) · Confidence: high.

**P14 — Sleep/wake and long intervals: the `~` marker is evaluated only at render.**
Evidence: `age` computed once per `_update_display` (947-948, 992); no `NSWorkspaceDidWakeNotification` handler (grep `NSWorkspace`, `didWake`: none in tracker.py); interval up to 3600 s (145). display-strategy.md:279-281 (D1/D2) and CHOICE-4 (:587-593) record this. · Impact: after a wake, or on "Every hour", a title without `~` can be up to 80 min old. · Effort: S (a cheap 60 s timer that re-runs only `_update_display` on the cached data, no file read) · Confidence: high.

**P15 — Clock skew is unguarded but benign.**
Evidence: a `captured_at` in the future gives negative `age` → treated fresh (992), never voided (922), and a future desktop sample always outranks the statusline (467). display-strategy.md:282 (D3) says "no rule needed". · Impact: low; a wrong system clock makes stale look fresh. · Effort: S · Confidence: high.

**P16 — No single-instance guard.**
Evidence: grep for `lock`, `pid`, `flock` in tracker.py: none. The problem has surfaced twice through docs (install.sh:136-138 comment; CHANGELOG v1.0.2 and v1.0.5 both fix a double-launch caused by install instructions). · Impact: two icons, the second "survives Quit" (CHANGELOG v1.0.2). · Effort: S (`fcntl.flock` on `~/.tokease/tracker.lock`, exit if held) · Confidence: high.

**P17 — Slow or partial writes: handled.**
Evidence: atomic replace (script:91-103); temp cleaned on failure (102); a non-dict file no longer kills the capture (script:85-88; tests:1564); reader treats `JSONDecodeError` as `error` (365-366). · Impact: positive. · Confidence: high.

**P18 — `statusline.err` grows without bound and is never surfaced.**
Evidence: append-only (script:52-53); nothing in tracker.py reads it (grep `statusline.err`: only the constant comment in README). · Impact: low; a broken wiring can log once per statusline render (several times a minute, display-strategy.md:78-79) for months. · Effort: S · Confidence: high.

### 2.6 Uninstall

**P19 — Coherent, with two documented residues.** uninstall.sh removes the LaunchAgent, kills only this checkout's tracker (31-35), removes the `statusLine` block only if it is ours (38), deletes `~/.tokease` (59-62); leaves `NSUserDefaults` and `settings.json.bak.*` by design (PRIVACY.md:36-38, 46-53). Homebrew users must run the libexec copy first (README.md:101-106). · Confidence: high.

---

## 3. Data model

### 3.1 Entities as they exist in code

| Entity | Shape | Producer | Consumer |
|---|---|---|---|
| **usage.json (schema 1)** | `{schema:1, captured_at: epoch s, source:"claude-code-statusline", five_hour?:{used_percentage, resets_at?}, seven_day?:{…}}` | script:129-138 | tracker.py:357-381 (ignores `schema` and `source`) |
| **plan-usage-history.json (version 2)** | `{version:2, samples:[{t: epoch ms, org: uuid, u:{fh, sd}}…]}` | Claude Desktop | tracker.py:413-426 (ignores `org`) |
| **Reading (normalised)** | `{five_hour?:{utilization, resets_at: ISO\|None}, seven_day?:{…}, _meta:{captured_at: epoch s, source}}` | 370-381, 396-403, 461-500 | 942-996 |
| **SourceStatus** | `None \| "nostatusline" \| "waiting" \| "error"` (statusline only) | 349-381 | 845-873 |
| **Window row** | `(text, pct\|None)` | 907-924 | 951-975 |
| **Settings** | 4 keys, see §1.3 | 709, 715, 723, 730 | 591-596 |
| **AlertState** | `_last_pct: int\|None`, `_last_reset: ISO\|None` | 755-763, 966 | 764-772, 903-904 |

Relations: one Reading per render; each window optionally links to a reset time that only the statusline can supply (399 forces `None` for desktop; 451-455 copies a future statusline reset onto a desktop window). `_meta.captured_at` is the age of the *oldest part shown* after a fill (486-492, R8).

### 3.2 Invariants enforced in code

| Invariant | Where |
|---|---|
| Displayed % ∈ [0,100], rounded half-up, 100 only if source ≥ 100 | `_display_pct` 301-327; tests 161-195 |
| A reset time is shown only while in the future; a desktop sample at/before a known reset is void | `_merge_window` 453-457; `_window_row` 920-921; tests 1112-1152, 1287-1300 |
| A reading older than its window is void | 922-923, 180-181; tests 1859-1893 |
| A window filled from the other source is never staler than 20 min | 449, 477-478 |
| A windowless fresher capture never hides a desktop reading | 473-474; tests 1068 |
| Desktop `version == 2`, `samples` is a list, `t`/`fh`/`sd` are numbers (bool excluded) | 384-386, 417-421, 394-398; tests 1096-1110, 1190 |
| `pct is None` ⇔ empty ring ⇔ "—" in the title | 121-122, 983, 985 |
| An unknown age is marked `~` but not voided | 948, 988-993; tests 1996-2024 |
| Capture script never raises, never writes on invalid stdin, never overwrites good windows with none | script:120-178; tests 1580-1646 |
| No shipped file imports a network client, names a credential API, or spawns anything but osascript | tests:2026-2185 |
| The reset date follows the user's timezone | 579; tests 2187-2219 |

### 3.3 Invariants assumed but NOT enforced

**M1 — Desktop samples are assumed chronological.**
Evidence: tracker.py:422 `for sample in reversed(samples): # samples are in chronological order` — no sort by `t`, no max. · Impact: an out-of-order file (compaction, merge of two machines via sync) makes an older sample the "latest" and stamps the whole display with its time. · Effort: S (`max(valid, key=t)`) · Confidence: high.

**M2 — `usage.json`'s `schema` field is written but never checked.**
Evidence: script:35, 130 vs tracker.py:364-380 (no `payload.get("schema")`). statusline-data-source.md:36-50 documents it as the contract. · Impact: the version field cannot do its job; a future schema 2 that renames keys reads as `waiting` ("Waiting for Claude Code activity…"), a misdiagnosis. · Effort: S · Confidence: high.

**M3 — Desktop `t` is assumed to be milliseconds.**
Evidence: tracker.py:402 `t / 1000.0`, guarded only by the `version == 2` pin (417). · Impact: a change to seconds under the same version makes every sample look like 1970 → every window "older than the window" → `—`, silently. · Effort: S (sanity-check the epoch magnitude) · Confidence: high.

**M4 — `_meta.source` is assumed to be one of two strings.**
Evidence: tracker.py:937 `via = "Claude app" if source == "desktop" else "Claude Code"`. · Impact: any third source is labelled "Claude Code" until this line is found. · Effort: S · Confidence: high.

**M5 — The two windows are assumed to be exactly `five_hour` and `seven_day` with spans 5 h / 7 d.**
Evidence: nine literal sites (§1.4 A7); spans 180-181 passed by hand at 953 and 973; the third-ring roadmap item (ROADMAP.md:34) says "a small change". · Impact: see D1. · Confidence: high.

**M6 — `used_percentage` is assumed monotonic inside a window.**
Evidence: the alert logic (769) and the `_last_pct` baseline rely on it; display-strategy.md:198 states it ("Usage only grows inside a window"); nothing checks it, and P6 shows a real path that violates it. · Confidence: high.

**M7 — `NOTIFY_THRESHOLDS` "sorted ascending" (comment 149) is not needed** — `max(crossed)` at 772 is order-independent. Harmless. · Confidence: high.

### 3.4 Migration story

- **Desktop file changes shape.** Guarded by one key (`version == 2`). Under the same version, key renames or unit changes are silent (M3). There is no user-visible "format changed" state; the outcome is ⚙ with wrong advice (A3/P13) or a stale fallback. README.md:110 overstates this as "detects that".
- **Claude Code changes the stdin contract.** The script writes windowless payloads only when no good file exists (script:161), so the app freezes on the last capture and reports "idle" (P13). `_epoch_to_iso` already tolerates epoch-or-ISO `resets_at` (330-343) because the format did vary (#40094). No version of Claude Code is recorded in the capture (the stdin JSON's `version` field, if any, is not captured — script:128-138 reads only `rate_limits`).
- **usage.json schema bump.** Meaningless today (M2). A schema 2 reader would need a branch in `_read_statusline_usage` and the script's `_read_current` comparison (script:148-155) would treat a schema-1 file as "different" and restamp once — harmless.
- **Settings.** No version key; each value is validated and clamped on read (591-596), so a bad or foreign value degrades to the default. Solid.
- **In-memory state.** None persisted, so nothing to migrate; the cost is P11.

---

## 4. Debt — the five items that will slow the next features most

Grounding: ROADMAP.md names, as concrete next work, (a) drawing the icon with CoreGraphics instead of Pillow (:47; `TokenFreeInvariantTest` already whitelists `Quartz/CoreGraphics` for it, tests:2047-2048), (b) a third ring / menu line for per-model windows "the day one ships" (:34), (c) an opt-in local JSONL-based feature — drift estimator (:33) or usage insights (:36) — each "opt-in, off by default, behind an ADR and privacy note", (d) ring clear-out animation (:46), (e) threshold notifications outside the .app (:45), (f) a jq variant of the capture (:48). Estimates assume one developer familiar with the code.

**D1 — Exactly two windows are hard-wired in nine literal sites, two duplicated display blocks and the icon geometry.**
Evidence: tracker.py:371, 397, 473, 481, 496, 804; script:75, 109, 135, 149; `_RING_RADII = (20, 14)` (93) mirrored in assets/build-menubar-icon.py:23; `_render_dynamic_icon(session_pct, weekly_pct)` (98); `m5h/m7d` (615-616); 951-968 vs 971-975; spans passed by hand (953, 973); `test_two_rings_only` (tests:491). Blocks (b) directly; touches (a) and (d). · Impact: the "small change" of ROADMAP:34 is a 12-site edit plus an icon redesign (three 3-px rings in a 22-pt slot: 20/14/8 radii leave a 2-px gap at the inner ring). Every window rule so far (FIXED-1 age ceiling, FIXED-6 title marker) was applied twice. · Fix now: ~1 day — a `WINDOWS` registry `(key, label, span, radius, alert?)` driving reader, merge, rows, icon and scheduling; tests already parametrise by key. · Cost of living with it: third ring 2–3 days instead of 0.5; each future window-rule fix ×2 sites and one more chance of the two blocks drifting. · Effort: M · Confidence: high.

**D2 — `_update_display` couples view assembly with alert-state mutation, with an order that only a test enforces.**
Evidence: tracker.py:942-996; `_maybe_notify` mutates `_last_pct`/`_last_reset` as a side effect (755-763); the ADR 0004 guard must run before it (954-959; ADR 0004:110-114); `_last_pct = 0` is set in the display branch (966). Blocks (d): an animation needs previous-vs-new percentage *per ring*, and the only "previous" the app keeps is `_last_pct` for the 5h window, owned by the alert logic. Blocks (c): an "~71% (estimated)" title is another branch in 983-993. Blocks (e): moving alerts to `UNUserNotificationCenter` means re-entering this method. · Fix now: ~1 day — a pure `compute_view(reading, alert_state, now) -> (View, AlertState, events)` and a thin `_apply(view)`; the ADR 0004 ordering becomes data flow instead of a pinned call order. · Cost of living with it: +0.5 day per display feature and one more implicit ordering each time; the next "FIXED-n" cycle (display-strategy.md §7.2 lists nine of them in one branch) repeats. · Effort: M · Confidence: high.

**D3 — The source contract is an untyped dict, the error channel is asymmetric, and the file's `schema` is unread.**
Evidence: §1.4 A2, A3; §3.3 M2, M4; tracker.py:349-426, 503-516, 937. Blocks (c): a third source means a third hand-built dict, a new `_meta.source` string that line 937 mislabels, a new error code the ⚙/…/? triage (853-873) does not know, and an opt-in flag with nowhere to be surfaced. Also blocks the README's "detects format changes" promise (P13). · Fix now: 1–1.5 days — `Reading` dataclass, `SourceStatus` enum per source, `schema`/`version` checks, and a per-source status line in the dropdown (e.g. "Desktop: unknown format · Claude Code: idle 3 h"). · Cost of living with it: +1 day per new source, and every upstream format change becomes a support thread instead of a self-diagnosing screen (README.md:108-117 is that thread, pre-written). · Effort: M · Confidence: high.

**D4 — No macOS lane in CI; everything AppKit-shaped is mocked, so the code paths that broke in production are the untested ones.**
Evidence: ci.yml:21, 33 (ubuntu only; rumps not installed, :43). Zero tests reference `_is_login_item`, `_set_login_item`, `_toggle_login`, `_get_app_path`, `RESOURCEPATH`/frozen, `NSBundle`, `webbrowser` (grep of tests: only `_settings_get/_set` are patched, never exercised). `TestRenderIcon` and `TestIconWriteFailure` are skipped without Pillow (tests:810, 1688) and Pillow is the only real dependency CI installs. The notification-does-not-show bug shipped in v1.0.0 and was found by measurement in v1.0.1/v1.0.4 (CHANGELOG). Blocks (a): a CoreGraphics renderer would be 0 % executed in CI (the Pillow one at least runs on Linux); blocks (e). · Fix now: 0.5 day for a `macos-latest` job installing `requirements.txt` and running the suite with real rumps/PyObjC, plus a smoke test that `_render_dynamic_icon` writes a 44×44 PNG; +1 day for a real `NSUserDefaults` round-trip test in a throwaway domain. · Cost of living with it: every macOS-only regression is found by users; (a) and (e) cannot be merged with confidence. · Effort: S–M · Confidence: high.

**D5 — The "one 1,000-line file" claim is a hard ceiling, restated in four places, and tracker.py sits exactly on it.**
Evidence: README.md:4, 26, 30; docs/index.html:921, 930; CHANGELOG v1.0.4 ("970 lines… 1,148 in total"); commits `21f6edc`, `df03837`, `b476a2b` (Phase 0 §9) are about the count; `wc -l tracker.py` = 1000 today. No test asserts the count (grep tests for `1000|wc -l`: none), so drift is caught by hand at release time. Every roadmap item above adds lines; (b) and (c) add tens. · Impact: either the number changes in four documents each release (the recent churn), or code is compressed to keep it — against the actual trust argument, which is readability (tests:2036-2037: "the reviewable-in-a-minute file size stays the real argument"). · Fix now: 0.5 day — state a bound ("under 1,200 lines") instead of an exact count, and add a CI check that fails when `wc -l` exceeds the bound or when README/index.html disagree with it. This changes a product promise, so it belongs in Brain `context.md` (AGENTS.md rule). · Cost of living with it: ~0.5 day per release of recount-and-sync, and a standing incentive to write denser code. · Effort: S · Confidence: high.

Also noted, not in the top five: the icon is a file-path API (`self.icon = str(icon_path)`, tracker.py:885, 889) written to disk on every render from the main thread (982, 131-132) — (a) will need either the same disk round-trip or rumps internals (rumps not installed here; not verified); the test file is a single 2,222-line module whose `_make_app` pattern is copied in six classes (tests:598-601, 724-729, and others).

---

## 5. Feature inventory

Legend: **solid** = implemented, tested, reachable on shipped installs · **partial** = implemented but with a gap in reach, test, or behaviour · **stub** = present but does nothing useful · **dead code** = unreachable on any distributed install.

| # | Feature | Status | Evidence |
|---|---|---|---|
| 1 | Two-ring dynamic menu bar icon (5h outer, weekly inner, empty ring for void window) | solid | tracker.py:98-136, 982; tests 1689-1710 (skipped without Pillow, so **not run in this environment**; CI installs Pillow, ci.yml:43) |
| 2 | Static template icon fallback (Pillow absent / asset missing) | solid | 41-47, 68-80, 601; display-strategy E7 |
| 3 | Display modes: icon+%, % only, icon only | solid | 153-156, 630-649, 877-889; tests 669-717 |
| 4 | "Add weekly %" title toggle | solid | 644-648, 721-726, 984-986; tests 1357-1374 |
| 5 | Stale `~` marker in title (20 min, unknown age) | solid | 177, 988-993; tests 1728-1850, 1996-2011 |
| 6 | "Updated / stale" freshness line with source name | solid | 927-940, 523-530; tests 1247, 1352, 1717, 1964 |
| 7 | Statusline source reader (epoch or ISO `resets_at`) | solid | 349-381, 330-343; tests 959-1039 |
| 8 | Desktop source reader (version 2 pin, defensive) | partial — `org` ignored (P7), order assumed (M1) | 406-426, 389-403; tests 1057-1110, 1190 |
| 9 | Dual-source merge by freshness with per-window guards | solid (complex) | 437-516; tests 1112-1320, 1973-1994 |
| 10 | Age ceiling (5 h / 7 d) | solid | 180-181, 922-923; tests 1859-1893 |
| 11 | Reset detection (past `resets_at` → void) + one-shot post-reset refresh | solid | 920-921, 793-824; tests 425-480, 1382 |
| 12 | Pre-reset guard (ADR 0004, in-memory) | solid, restart-limited | 891-904, 954-959; tests 719-805 |
| 13 | Threshold notifications 80 %/95 % (crossing-only, new-window re-anchor) | partial — logic tested, **delivered on no distributed install** (P8) | 148-151, 743-785, 960-966; tests 594-664, 1817-1850, 1895-1953; README.md:31 |
| 14 | Alerts on/off toggle | partial — persists, no observable effect outside .app | 654-658, 728-731; tests 852-866 |
| 15 | Launch at login (System Events via osascript) | **dead code on shipped paths** — needs frozen bundle; menu item greyed otherwise; zero tests | 235-283, 607, 621-628, 733-738; ROADMAP.md:44, 68 |
| 16 | Refresh interval 1/5/30/60 min, persisted | solid | 141-146, 591, 699-711, 787-791; tests 335-386 |
| 17 | Settings persistence (NSUserDefaults) | partial — never exercised against real defaults (tests:82 nulls it); un-namespaced keys in a shared domain (P3) | 159-162, 210-228; PRIVACY.md:46-53 |
| 18 | Dock-icon suppression for non-bundle runs | solid, untested | 57-66 |
| 19 | Main-thread marshalling of UI mutations | solid | 32-39, 821, 843; tests 388-420 |
| 20 | Error states ⚙ / … / ? with icon cleared | partial — `?` has no dropdown text, rows stale (P12) | 845-873; tests 308-330, 564-591, 1395-1428 |
| 21 | Manual "Refresh" menu item | solid | 684 |
| 22 | Support submenu: version label, "Star on GitHub" | solid | 189-193, 676-679, 740-741 |
| 23 | Quit (custom, `quit_button=None`) | solid | 603, 688 |
| 24 | Title spacer between icon and % | solid, **never tested with the spacer on** (tests:85 blanks it) | 185, 887 |
| 25 | Capture script: extract windows, atomic write, keep measurement timestamp, never overwrite good windows with none, error log, quiet mode, minimal render line | solid — except the parallel-session case (P6) | script:58-170; tests 1431-1683 |
| 26 | `TOKEASE_STATUSLINE_QUIET` snippet mode | solid | script:168-169; statusline/README.md:52-61 |
| 27 | Statusline installer (copy, jq-edit settings.json with backup, never overwrite an existing statusline) | solid, shell untested | install-statusline.sh:19-118 |
| 28 | Source installer (venv, LaunchAgent, single-launch guard) | solid, shell untested | install.sh:44-145 |
| 29 | Uninstaller (scoped pkill, jq removal of our block only, delete ~/.tokease) | solid, shell untested | uninstall.sh:25-62 |
| 30 | py2app bundle (LSUIElement, icon, bundle id) | partial — builds, **not distributed**; version duplicated by hand (setup.py:27-28 vs tracker.py:193, "keep in sync" 192) | setup.py, build.sh |
| 31 | Token-free CI tripwire (AST: imports, credential strings, spawned binaries, file-list completeness) | solid | tests:2026-2185; ci.yml |
| 32 | Local-timezone reset date | solid | 579; tests 2187-2219 |
| 33 | Landing page / privacy / security docs | solid as docs; claims checked in §6 | docs/index.html, PRIVACY.md, SECURITY.md |
| 34 | rumps app name `"Claude"` | note — the NSStatusItem/app name passed to rumps is the trademark, not "Tokease" | tracker.py:603 |

Surprises worth calling out: (15) is the only true dead code and it is a documented feature ("launch at login (.app build)", README.md:40); (13)/(14) are a feature the README advertises with a caveat that amounts to "off"; (1) and (24) are solid in production but their tests are respectively skipped here and neutralised.

---

## 6. BRAIN vs CODE divergences

Where the docs/ADRs/specs and the code disagree. "Doc lags code" means the code moved on; "code lags spec" means the spec promises what the code does not do. The Brain `context.md` itself was **not found on this machine**, so only in-repo decision documents were checked.

1. **ADR 0002 has no "revised by ADR 0003" banner; `statusline-data-source.md` contradicts itself.** ADR 0002:39-41 "The **only** data source is now the Claude Code statusline"; ADR 0001:3 carries a revision banner, ADR 0002 does not. docs/specs/statusline-data-source.md:7-9 repeats "the statusline is the **only** data source" and then :53-55 describes the desktop merge. Code: two sources (tracker.py:503-516). — Doc lags code. Fix: a banner on ADR 0002 and one sentence in the spec header. S.

2. **`captured_at` semantics.** statusline-data-source.md:48 "`captured_at`: epoch seconds **at write time**". Code keeps the measurement's timestamp across identical or window-dropped re-renders (script:148-155; display-strategy.md R10 :187-192, FIXED-4/8). — Doc lags code; this is the file contract other integrators would read. S.

3. **Staleness signal.** statusline-data-source.md:72-74 says the *Updated* line gets a ⚠ prefix; code also prefixes the title with `~` (tracker.py:992-993, honest-freshness.md B). — Doc lags code. S.

4. **`?` state explanation.** display-strategy.md:151-154 (R6) and :203 promise the reason in the dropdown for `⚙ … ?`; code gives none for `?` and leaves the rows stale (tracker.py:871-873). — Code lags spec (P12). S.

5. **Write-confinement invariant.** display-strategy.md:182-184 (R9) and ADR 0003:56-57 say writes are confined to `~/.tokease`; the app writes `NSUserDefaults` (tracker.py:221-228). PRIVACY.md:28-29 already discloses it. — Spec wording incomplete; not a privacy issue. S.

6. **"Detects a format change and falls back."** README.md:110 vs tracker.py:417, 513, 853-860: detection is a single `version == 2` check, and a desktop-only user gets ⚙ with "open the Claude desktop app" rather than a frozen stale reading. display-strategy.md:614-616 (A7) already flags the wording; the README sentence overstates. — README overstates code (P13). S.

7. **`org` handling.** ADR 0003:95-96 "the `org` field **must** be respected if several orgs appear"; code never reads `org` (tracker.py:389-403); display-strategy.md CHOICE-6 (:603-605) defers it. — ADR says must, spec says deferred, code does neither; the ADR should say "deferred (CHOICE-6)". S.

8. **"Drop then re-cross is no longer reachable."** display-strategy.md:303 (F4) vs tests:658-663 (`test_drop_below_then_recross_renotifies` asserts two alerts) and the parallel-session path (P6), plus A10-style desktop drops. — Spec claim too strong; code behaviour is deliberate. S (doc).

9. **Primary/secondary wording.** tracker.py:5-8 and 504 call the statusline "primary"; display-strategy.md:62 calls the desktop "secondary in name, primary in practice". Behaviour is symmetric by freshness (461-500), so this is wording only. No action needed beyond consistency.

10. **Launch-at-login and threshold alerts are documented as features of a build that is not shipped.** README.md:40 and ROADMAP.md:44-45 are internally honest about it, but the Features list (README.md:36-42) still enumerates them. Product decision for Brain: either drop them from "Features" until the .app ships, or ship the .app.

Nothing in the code contradicts ADR 0001, 0002 (as revised), 0003's decision section, or ADR 0004's chosen option. The token-free promise holds by inspection and by the tripwire (tests:2026-2185).
