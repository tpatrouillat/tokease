# Spec — Codex integration (first limited multi-source)

Date: 2026-09-12. Status: proposed, nothing implemented. Sources frozen at
repo `1b480ef` (`tracker.py`, `tests/test_tracker.py`) and Brain `12716ec`.
Follows [`multi-provider-feasibility.md`](multi-provider-feasibility.md)
(verdict: Codex is the only tool integrable under R9) and is governed by
[ADR 0005](../adr/0005-architecture-multi-source.md) (how a source is added).
`main` is frozen until 2026-09-18: this lands on a branch, after the Show HN.

## 0. What this adds, in one paragraph

A **separate Codex block** in the dropdown, below the Claude rows: one row
per quota window Codex reports, and its own "Updated" line. Read from the
rollout file the Codex CLI already writes for its own `codex resume`, the same
way the Claude desktop history is read (ADR 0003): local, read-only, no token,
no network, nothing written outside `~/.tokease`. Title, rings and alerts stay
Claude. Absent Codex = absent block.

Out of scope, explicitly: Cursor, Gemini, Grok, Lovable (matrix § 1); any
write outside `~/.tokease`; a second provider in the title or the rings;
Codex threshold alerts; a Codex reset scheduling a one-shot refresh; any
"provider" abstraction (ADR 0005).

## 1. The source

### 1.1 Path

```
$CODEX_HOME/sessions/YYYY/MM/DD/rollout-<ISO time>-<uuid>.jsonl
```

`CODEX_HOME` defaults to `~/.codex` (the CLI honours the variable; Tokease
reads it with the same default, one line). Every Codex surface writes there:
originators seen on this machine `codex-tui`, `Codex Desktop`, `codex_exec`,
`orca_desktop`. On this machine on 2026-09-12: 430 rollouts, 289 MB, largest
1.4 MB, longest single line 135 KB.

Constant to add next to `_DESKTOP_HISTORY_FILE`:

```python
_CODEX_SESSIONS_DIR = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "sessions"
```

Tests patch `_CODEX_SESSIONS_DIR` the way they patch `_DESKTOP_HISTORY_FILE`
(the dev machine has real rollouts; without the patch they leak into every
`_fetch_and_update` test).

### 1.2 Selecting the rollout

The most recently **modified** rollout, not the newest name: a session
opened yesterday and still running holds the freshest quota. `glob` over
`sessions/*/*/*/rollout-*.jsonl` + `max(mtime)` costs 1 ms for 430 files
(measured), so no directory pruning. A rollout can hold no `token_count` at
all (35 of 430 here: sessions that never completed a turn), so the reader
walks the candidates in mtime order, newest first, and stops at the first
one that yields a reading. Cap: **5 files**, then "absent". The cap is not a
correctness rule, it is the bound that keeps a refresh cheap when a user
scripts `codex exec` in a loop that never gets a response.

### 1.3 Reading the last `token_count`, bounded

Never read a whole rollout: a 1.4 MB JSONL parsed every 5 minutes for one
line is the kind of cost ADR 0003 refused. Read the **last 256 KB** only
(`seek` from the end, `os.SEEK_END`, then split on `\n`). Measured over the
392 September rollouts that carry the event, the distance from EOF to the
last `token_count` line is 1.2 KB at p50, 4.3 KB at p90, 109 KB at worst,
so 256 KB reaches it in every observed file while staying under the size of
the largest single line seen. A rollout whose last `token_count` sits
further back than 256 KB is treated as **absent** (R5: unknown beats a
guess), not scanned further. `# ponytail: 256 KB tail; grow the constant if
a real file ever misses, never read the whole file.`

The first fragment after the seek is a truncated line: drop it. Then, from
the last complete line backwards:

- `json.loads` each line; a malformed line is skipped (a rollout is appended
  live and its last line may be half written).
- keep the first line where `type == "event_msg"`,
  `payload.type == "token_count"` **and** `payload.rate_limits` is a dict
  whose `primary` is a dict. 186 of 2,950 September events carry
  `rate_limits: null` and 78 carry `primary: null` (measured): they are
  skipped, an earlier event in the tail is used instead.
- nothing kept → next candidate file (§ 1.2).

The line's own `timestamp` (ISO 8601, `Z`) is the capture time, parsed with
the existing `_parse_iso`. No `timestamp` or unparsable → the reading is
dropped (R1: an unknown age would show as `⚠ capture time unknown`, but a
rollout event without a timestamp is a format change we do not want to
guess through, so the whole reading is dropped and the block stays absent).

### 1.4 Fields read, fields never read

Read, from `payload.rate_limits` only:

| Field | Use |
|---|---|
| `primary.used_percent`, `secondary.used_percent` | the percentage (`_display_pct` clamps it, as for the Claude feeds) |
| `primary.window_minutes`, `secondary.window_minutes` | the row label and the age ceiling (§ 2) |
| `primary.resets_at`, `secondary.resets_at` | epoch seconds → `_epoch_to_iso`, shown while ahead (R4) |
| `plan_type` | not shown in v1; read only to be logged nowhere. Drop it from the reader. |

`secondary` is `null` on the `prolite` and `go` plans seen (matrix § 3): one
row then. A window whose `used_percent` is not a number (`_is_number`) is
dropped; a reading with no usable window at all is absent.

Never read, by construction, not by promise:

- `$CODEX_HOME/auth.json` (the token). The reader opens paths matched by the
  glob in § 1.1 only; nothing in `tracker.py` names `auth.json`. The
  `TokenFreeInvariantTest` string check gains `"auth.json"` in
  `FORBIDDEN_STRINGS` so a future reader cannot name it either (§ 4).
- `payload.info` (token counts per turn: consumption, not quota), the
  `session_meta` line (cwd, instructions, model), `response_item` lines
  (the conversation itself), `credits` (a balance, not a window; matrix § 0
  vocabulary), `config.toml`, anything under `~/.codex` other than
  `sessions/`.

The reader touches the conversation file, so it inevitably has the
conversation within reach. The argument that it does not read it is the same
as for the Claude desktop history: the function is short enough to read, it
keeps exactly the four fields above, and the tail bound means it does not
even load most of the file.

### 1.5 Normalised shape

`_read_codex_usage()` returns `None` (absent) or:

```python
{
    "windows": [  # in feed order: primary, then secondary when present
        {"minutes": 10080, "utilization": 15.0, "resets_at": "2026-09-18T…+00:00"},
    ],
    "_meta": {"captured_at": 1789...,  "source": "codex"},
}
```

A list, not `five_hour` / `seven_day` keys: the Codex feed does not have a
fixed pair of windows (matrix § 3), and forcing it into the Claude shape
would make `_merge_usage` look applicable when it must not be.

## 2. Display

Rules from the matrix § 3, applied to the existing helpers.

### 2.1 Menu layout

```
5-hour: 42% (resets 2h 10m)          ← Claude, unchanged
Weekly: 12% (resets Sep 18)
────────
Updated: 14:02 (via Claude app)
Refresh
────────
Codex Weekly: 15% (resets Sep 18)    ← new block, hidden when absent
Codex: 14:01 (via Codex)
────────
Settings ▸ …
```

Three `rumps.MenuItem`s created in `App.__init__` after `self.mupd`:
`self.mcx1`, `self.mcx2` (second window), `self.mcxupd`, inserted in
`self.menu` between the `Refresh` item and the settings separator, with
their own separator. Hidden via the underlying `NSMenuItem`
(`item._menuitem.setHidden_(True)`), wrapped in a four-line helper
`_set_hidden(item, flag)` that no-ops when `_menuitem` is missing (the test
fakes). `# ponytail: hide, don't rebuild the menu; rumps has no cheap
remove.` The separator before the block is hidden with it, so an absent
Codex leaves no gap and no trace (matrix § 3, "absent source = absent
block").

### 2.2 Rows

Each window goes through the **existing** `_window_row`, which already
implements R3 (past reset → dash, reading older than the window → dash) and
the percentage formatting:

- label: `Codex 5-hour` for `minutes == 300`, `Codex Weekly` for `10080`,
  `Codex 30-day` for `43200`; any other value → **`Codex`** alone, no
  name guessed, the row still shows the percentage and the reset (matrix
  § 3, R5). Table `_CODEX_WINDOW_LABELS = {300: "5-hour", 10080: "Weekly",
  43200: "30-day"}` next to the constants.
- `span` (the age ceiling of R3) = `minutes * 60` when `minutes` is a
  positive number, else `None`. A `prolite` weekly reading older than 7 days
  shows `Codex Weekly: — (reading older than the window)`. Unknown
  `window_minutes` gets no ceiling: the stale marker of R1 still applies.
- reset: `_window_row` shows `(resets 2h 10m)` while ahead and `— (reset;
  awaiting …)` once passed. The client name in that string is hard-coded
  `Claude Code` today; it gains a keyword `client="Claude Code"` and the
  Codex call passes `client="Codex"`, so a passed Codex reset reads `Codex
  Weekly: — (reset; awaiting Codex)`. Two lines changed, no duplicate.
- one window → the second row is hidden. Zero usable windows → the whole
  block is hidden (§ 1.4 makes that "absent" upstream anyway).

### 2.3 Freshness line

`_freshness_label(captured_at, now, source)` gains `"codex" → "Codex"` in its
`via` mapping (today a ternary; becomes a three-entry dict). Same threshold
`_STALE_AFTER_SECS` (20 min), same wording family:

```
Updated: 14:01 (via Codex)
⚠ 14:01 · stale 3h (Codex idle?)
```

Codex writes one event per turn and nothing between sessions (matrix § 1),
so this line will read stale most of the day for most users. That is the
point of R1: the number is old and says so. No `~` marker is added anywhere
for Codex, since the title never shows a Codex number.

### 2.4 What does not change

- **Title, rings, `~` marker, alerts, reset scheduling**: fed by the Claude
  data only. `_update_display(data)` is not touched.
- **`fetch_usage()` and `_merge_usage`**: Claude-only, untouched. Providers
  are never merged (matrix § 3). The Codex read happens beside them, in
  `_fetch_and_update`, which passes a third value through `_call_on_main`.
- **Error glyphs** (`⚙`, `…`, `?`): describe the Claude source, which is
  the product. A Codex-only user sees `⚙` with the setup guide **and** the
  Codex block below it. `_apply_usage` therefore updates the Codex rows
  first, before any of its early returns.
- A Codex source that fails to parse is ignored, never shown as an error
  (R5): "absent" is the only failure mode.

## 3. Implementation plan, by file

### `tracker.py` (~95 lines added, 4 changed)

| Where | What | Lines |
|---|---|---|
| constants, after `_DESKTOP_HISTORY_FILE` | `_CODEX_SESSIONS_DIR`, `_CODEX_TAIL_BYTES = 256 * 1024`, `_CODEX_MAX_CANDIDATES = 5`, `_CODEX_WINDOW_LABELS` | 8 |
| after `_read_desktop_usage` | `_codex_event_to_data(line_obj)` → normalised dict or `None` (the field filter of § 1.4, mirrors `_desktop_sample_to_data`) | 25 |
| after it | `_read_codex_usage()` → glob, mtime sort, tail read, backward scan, returns first reading or `None` (§ 1.2, 1.3). Every `OSError`, `UnicodeDecodeError`, `json.JSONDecodeError` swallowed, like `_read_desktop_usage` | 35 |
| `App.__init__` | three `MenuItem`s + separator, inserted in `self.menu` | 6 |
| `App._set_hidden` (static) | `getattr(item, "_menuitem", None)` then `setHidden_` | 4 |
| `App._update_codex_rows(codex, now)` | hide all when `None`; else per-window `_window_row` with label/span from § 2.2, `_freshness_label` with `"codex"` | 22 |
| `App._fetch_and_update` | `codex = _read_codex_usage()` in the same `try`, passed to `_apply_usage(data, err, codex)` | 2 |
| `App._apply_usage` | `self._update_codex_rows(codex, datetime.now(timezone.utc))` as the first statement | 1 |
| `App._window_row` | keyword `client="Claude Code"`, used in the reset string | 2 changed |
| `App._freshness_label` | `via` from a dict `{"desktop": "Claude app", "codex": "Codex"}` with `"Claude Code"` default | 2 changed |

Nothing added imports anything: `glob`, `os`, `json`, `pathlib` are already
in scope (`os` for `environ`, `glob` via `Path.glob`). No new dependency.

Expected file size: **~1,095 lines** (from 1,000). The matrix estimated
1,050; the difference is the bounded tail read, which is what keeps the
promise cheap on a 1.4 MB file, and the hide/show plumbing. Neither is
optional.

### `tests/test_tracker.py` (~220 lines added, 1 changed)

Fixtures: a helper `_write_rollout(dir, name, lines, mtime)` that writes a
JSONL under `<dir>/2026/09/12/`, with `lines` a list of dicts (a
`session_meta` first, then whatever the test needs) and `os.utime` to set the
order. A `_token_count(ts, primary, secondary=None, rate_limits=True)`
builder returns the event dict; `rate_limits=False` writes `null`.

`class TestReadCodexUsage` (patches `_CODEX_SESSIONS_DIR` to a temp dir):

| Test | Asserts |
|---|---|
| `test_absent_when_dir_missing` | `None`, no exception |
| `test_absent_when_no_rollout` | empty tree → `None` |
| `test_absent_when_no_token_count` | rollout with `session_meta` + `response_item` only → `None` |
| `test_last_token_count_wins` | two events, later one's `used_percent` returned |
| `test_null_rate_limits_is_skipped` | last event has `rate_limits: null`, the previous one is used |
| `test_null_primary_is_absent` | only event has `primary: null` → `None` |
| `test_one_window_when_secondary_null` | `prolite` shape → one entry in `windows` |
| `test_most_recently_modified_rollout_wins` | two files, older name but newer mtime wins |
| `test_falls_back_to_previous_rollout` | newest file has no event, second newest has one → second used |
| `test_gives_up_after_five_candidates` | six empty newest files, seventh has an event → `None` (documents the cap) |
| `test_reads_only_the_tail` | event, then 300 KB of `response_item` padding → `None` (documents the bound honestly) |
| `test_finds_the_event_inside_the_tail` | 200 KB padding before the event, 100 KB after → found (proves the seek) |
| `test_half_written_last_line_is_skipped` | file ends with a truncated JSON line after a good event → event returned |
| `test_captured_at_from_line_timestamp` | `_meta.captured_at` equals the parsed `timestamp` |
| `test_missing_timestamp_drops_the_reading` | no `timestamp` key → `None` |
| `test_reads_no_other_field` | `data` has exactly `windows` and `_meta`; a window has exactly `minutes`, `utilization`, `resets_at` (so `plan_type`, `credits`, `info` cannot leak in later) |

`class TestCodexRows` (a `FakeApp`, calls `_update_codex_rows` directly, no
file):

| Test | Asserts |
|---|---|
| `test_absent_hides_the_block` | all three items and the separator hidden |
| `test_labels_from_window_minutes` | 300 → `Codex 5-hour:`, 10080 → `Codex Weekly:`, 43200 → `Codex 30-day:` |
| `test_unknown_window_is_unnamed` | 1440 → row starts with `Codex: 42%`, reset shown |
| `test_reset_in_the_past` | `Codex Weekly: — (reset; awaiting Codex)` |
| `test_reading_older_than_the_window` | 5h window captured 6 h ago → `— (reading older than the window)` |
| `test_unknown_window_has_no_ceiling` | 1440 captured 30 days ago → percentage still shown, freshness line stale |
| `test_one_window_hides_second_row` | `prolite` → `mcx2` hidden, `mcx1` shown |
| `test_stale_after_twenty_minutes` | `⚠ hh:mm · stale 3h (Codex idle?)` |
| `test_fresh_line_names_codex` | `Updated: hh:mm (via Codex)` |
| `test_claude_title_and_rings_untouched` | with a Codex reading present, `title` and `icon` equal the Claude-only render |
| `test_shown_under_setup_glyph` | `_apply_usage(None, "nostatusline", codex)` → title `⚙` and Codex rows visible |

Each behavioural test must fail before its patch (the rule of
`honest-freshness.md`): the reviewer reverts `tracker.py` and runs the class.

Existing tests: `FakeMenuItem` gains nothing (`_set_hidden` no-ops without
`_menuitem`); tests that drive `_fetch_and_update` patch
`tracker._read_codex_usage` to return `None` in their `setUp`, or the
dev machine's rollouts leak in. That is the one change to existing tests.

`TokenFreeInvariantTest`: add `"auth.json"` to `FORBIDDEN_STRINGS`. No
allowed-path list exists in the guard today (it checks imports, credential
API names and spawned binaries, not paths), so no "one more allowed path" is
needed; the new literal is the Codex equivalent of `Claude Code-credentials`.
`_shipped()` is unchanged: no new module.

### Diff size

`tracker.py` +95/−4, `tests/test_tracker.py` +220/−1, docs below. One PR,
one commit per file at most, no refactor of the Claude path.

## 4. Public claims that move

The README, `PRIVACY.md` and `ROADMAP.md` bind the product. The sentences
below stop being true the day the reader ships and must change **in the same
PR**. Listed, not edited here (`main` is frozen; the wording is the PR's).

| File | Line | Today | Becomes |
|---|---|---|---|
| `README.md` | 4 | "One 1,000-line Python file" | "One 1,100-line Python file" (or the measured count) |
| `README.md` | 24 | "Tokease reads only two local files: the quota history the Claude desktop app writes […] and the `rate_limits` data Claude Code hands to its statusline" | three files; name the Codex rollout and say what is read from it (one line, the four fields) |
| `README.md` | 26 | "one 1,000-line Python file" | same count as line 4 |
| `README.md` | 30 | "One 1,000-line file" | same |
| `README.md` | 53 | "Tokease merges two local, read-only sources" | still true for Claude; add that Codex is a third, separate, never merged |
| `README.md` | 154 | "Tokease only reads two local files: `~/.tokease/usage.json` […] and […] `plan-usage-history.json`" | add `~/.codex/sessions/**/rollout-*.jsonl` (last 256 KB, four fields) |
| `README.md` | 187 | "It relies on local files written by Claude apps" | "written by Claude apps and the Codex CLI"; add OpenAI to the non-affiliation |
| `PRIVACY.md` | 8–14 "What it reads" | two bullets | a third bullet for the rollout: path, the four fields, what in the file is never read (the conversation, `info`, `auth.json`) |
| `PRIVACY.md` | 57 | "Not affiliated with Anthropic." | "Not affiliated with Anthropic or OpenAI." |
| `ROADMAP.md` | 7 | "read from two local files official Claude apps already write" | three files |
| `ROADMAP.md` | 18 | "Most don't expose limits the way Claude Code's statusline does" | Codex does (matrix § 5); row moves to "done" for Codex, stays for the four others |
| `ROADMAP.md` | 31 | "Second-tool support (most likely: Cursor or Lovable)" | Codex, shipped; Cursor and Lovable blocked (matrix § 2) |

Unchanged and still true: "No HTTP client is imported", "The only
subprocess this repo spawns is `osascript`", "never touches the Keychain or
your OAuth token", everything in `PRIVACY.md` "What it stores".

One claim gets **weaker** and the README must say so plainly: "two local
files written by official Claude apps for their own use" was a narrow
surface. The rollout is the user's Codex conversation, and Tokease now opens
that file, even if it keeps four numbers from its tail. The sentence to add
is the one from § 1.4: the reader is short enough to read, and the tail
bound means most of the file is never loaded.

## 5. Open points for the challenge

Three things a reviewer should push on; the answers here are the current
position, not settled facts.

1. **256 KB tail bound.** Measured on one machine, 392 files. A user whose
   last turn produced a 300 KB tool output would see "absent" until the next
   turn. Position: acceptable (R5, the next turn fixes it); alternative is
   to double the bound, never to read the whole file.
2. **mtime as recency.** A `codex resume` of an old session touches its
   mtime and its last `token_count` may be hours old; that is what the
   stale line is for (R1), and a new turn writes a new event. Position: no
   extra rule.
3. **`rate_limits` format not declared stable** (matrix § 1). Same grey
   level as the desktop history; same answer: defensive parsing, absent on
   any anomaly, and a test fixture frozen from the real file so a format
   drift shows up as a failing test, not a wrong number.
