# Spec: display strategy (what the menu bar shows, and why)

Date: 2026-09-04. Status: proposed. Describes the code on
`fix/display-strategy-gaps` (173 tests green).

Revision note. The first version of this document was written against
`main` after `fix/honest-freshness` and listed five gaps, GAP-1 to GAP-5.
The branch `fix/display-strategy-gaps` then changed four behaviours in one
commit. This revision re-checks every scenario against that code. A row
marked **FIXED-n** was a gap in the first version and is closed now, and
section 7.2 keeps the original diagnosis next to the fix so the history
stays readable. Two things the first version's numbering hides: GAP-4 is not
among the four fixed behaviours and stays open, and the fix for GAP-2 opened
a new gap, GAP-6, closed since as FIXED-5. The cosmetic gaps GAP-5a and
GAP-5b are closed as FIXED-6 and FIXED-7.

Refs: [ADR 0001](../adr/0001-pivot-source-statusline.md) (statusline source),
[ADR 0003](../adr/0003-source-secondaire-plan-usage-desktop.md) (desktop
source), [statusline-data-source.md](statusline-data-source.md) (file
contract), [honest-freshness.md](honest-freshness.md) (the 26 % incident).

## 1. Why this document exists

The display logic has been fixed one incident at a time: a merge bug, a stale
marker, an alert lost on reset. Each fix is right on its own, but nothing
states, for a given situation, what the menu bar must show and why. This
document is that rule set. It lets someone who has not read `tracker.py`
predict the menu bar in any situation, and decide whether an observed
behaviour is a bug or the rule at work.

The governing constraint is truth over comfort. Saying "I don't know" is
better than showing a wrong number with confidence. The founding incident:
the menu bar showed `26%` with no warning for 30 minutes while the 5-hour
quota was in fact exhausted.

Section 6 is the scenario matrix. Section 7 separates what the code does
right, what was fixed and how it was checked, what is still a gap, and what
is an open product choice.

## 2. Vocabulary

- **Window**: one of the two quotas, `five_hour` (5h) and `seven_day`
  (weekly). Each has a percentage used and, from one source only, a reset
  time.
- **Reading**: one window's percentage as captured by one source at one
  time. A reading describes the window that was active when it was taken,
  never a later one.
- **Source**: a local file written by an official Claude client and read as
  is. Two exist (section 3).
- **Fresh**: a reading at most 20 minutes old at render time
  (`_STALE_AFTER_SECS`). **Aged**: older than that.
- **Rendered**: the moment `_update_display` runs. Everything in this
  document is evaluated at that moment. Between two renders the menu bar
  does not change.
- **Title**: the text next to the icon in the menu bar. **Dropdown**: the
  three lines `5-hour`, `Weekly`, `Updated` in the menu.

## 3. The sources, as they really behave

### 3.1 Claude desktop app history (secondary in name, primary in practice)

File `plan-usage-history.json` under the desktop app's Application Support
directory, sampled by the desktop app while it runs. Each sample carries both
windows, no reset time. Read-only, undocumented format, parsing pinned to
`version: 2`.

Measured on a month of samples on one machine (807 samples): median gap 5
min, p75 15 min, p90 45 min, 5 % of gaps above 4 hours (Mac asleep, app
idle or quit). The app skips samples while idle. Within a single 5-minute
gap the 5h percentage was seen to jump by 59 points, and by 74 points across
a 30-minute gap. A fresh reading is therefore not a current one: "fresh" only
bounds its age, not its distance from reality.

For a user working in the VS Code extension or in Cowork this is the only
source that ever moves, because those surfaces never run the statusline.

The samples carry an organisation identifier. It is never displayed, never
written anywhere and must never appear in this repository.

### 3.2 Claude Code statusline capture (the only source with reset times)

`statusline/tokease-statusline.py` receives Claude Code's session JSON on
stdin and writes `~/.tokease/usage.json` with `captured_at` set to the write
time. `rate_limits` appears only for Pro and Max, only after the first API
response of a session, and each window may be absent.

What the official statusline documentation says about when the script runs,
and what it implies for freshness:

- It runs on session start and resume, on every new assistant message, after
  `/compact`, when the permission mode changes, when vim mode toggles, when
  a `refreshInterval` timer elapses, and **when a rate-limit window reaches
  its `resets_at`**. Claude Code **drops a window once its `resets_at`
  passes**.
- Only the "new assistant message" trigger carries new quota values. Every
  other trigger re-sends the values of the last API response. In an idle
  terminal session those values can be hours old, and the capture script
  timestamps them with the current time.
- The reset trigger produces a capture that lacks the window that just
  reset. This is the documented origin of the partial capture in the 26 %
  incident (weekly only, no 5h, in the middle of the night): an idle
  terminal session whose 5h window reached its reset time.

Consequence: `captured_at` was a write time, not a measurement time. The
capture script now keeps the previous timestamp when nothing changed
(FIXED-4 in section 7.2), including when a window vanished at its reset
(FIXED-4, FIXED-8).

### 3.3 What the app does between the sources

`fetch_usage` reads both files on every refresh (default every 5 min, user
choice from 1 min to 1 hour, plus a one-shot refresh 5 s after the soonest
known reset). If only one source parses, it is used alone. If both parse,
`_merge_usage` combines them per window (rules in section 4).

## 4. The rules

R1. **Age is declared, always.** A percentage rendered without a marker was
captured at most 20 minutes before the render. Past that it carries the `~`
prefix in the title and the dropdown says how old it is. There is no
exception for any source or display mode (icon mode is the accepted blind
spot, see C5).

R2. **The fresher measurement wins, per window.** When both sources carry a
window, the one measured later is shown. The other source may still
contribute what it alone knows (the reset time, R4). Nothing is averaged or
reconciled.

R3. **A reading belongs to its window.** If the app knows that a window reset
after a reading was taken, that reading is void and the window shows the
dash placeholder (`—`) in the title, the empty ring in the icon, and
`reset; awaiting Claude Code` in the dropdown. A pre-reset percentage must
never be shown as the new window's value. A reading also cannot outlive the
window it describes: a 5h reading older than 5 hours, or a weekly reading
older than 7 days, is void the same way, with `reading older than the
window` in the dropdown (FIXED-1).

R4. **Reset times come from the statusline only, and only while ahead.** A
countdown that has passed is never shown, and a next reset is never
extrapolated (README, "A note on freshness").

R5. **Unknown beats a guess.** A window without a usable reading shows the
dash placeholder, not `0%`. A source that fails to parse is ignored, never
displayed as an error, unless nothing else is left.

R6. **Errors are explained in every display mode.** `⚙` (no source at all,
with the setup guide in the dropdown), `…` (statusline file present but no
window yet), `?` (unreadable data). The ring icon is cleared so it cannot
contradict the glyph.

R7. **Alerts fire on upward crossings only.** 80 % and 95 % on the 5h window,
compared between two consecutive renders, never on the first render after
launch, never twice at a plateau. Freshness does not gate them (a frozen
reading cannot cross anything, a late crossing is still true). When the app
detects a 5h reset the baseline is re-anchored at 0 so the new window can
raise its own alert. A reset is detected in two shapes: a window present
with a past `resets_at`, or a reading whose `resets_at` is later than the
last one seen, since a window carries its own reset time (FIXED-2,
FIXED-5). A reading with no reset time that arrives once the last seen
reset has passed forgets that reset, so the reset time arriving later with
the next capture does not re-anchor a window the desktop feed already
tracked (FIXED-5). The desktop feed has no reset time, so there a new
window is only visible as a drop and the baseline follows the drop.
Delivery itself needs a signed `.app` bundle.

R8. **One "Updated" line per render, dated from the oldest part shown.**
When a partial capture is completed from the desktop feed, the merged
reading takes the desktop sample's time, so the line and the `~` marker
describe the filled window rather than the capture that triggered the merge
(FIXED-3, which revises the "up to 20 minutes older" caveat the first
version and ADR 0003 accepted). The `via` label names the desktop too,
since it is the desktop's time that is shown (FIXED-7).

R9. **Everything shown comes from a local file written by an official Claude
client, read as is.** No Keychain, no network, writes confined to
`~/.tokease`, and the capture script never raises. Any rule that would need
more than that is out of bounds, and section 7 says so where it applies.

R10. **A capture without a new measurement keeps its timestamp.** The
capture script re-stamps `captured_at` only when a window it carries
changed. Identical windows re-sent by Claude Code for a non-quota reason keep
the time of the measurement they repeat (FIXED-4), and so does a capture in
which a window vanished at its reset while the other is unchanged (FIXED-8).
A window that appears, or changes, is a new measurement and is stamped anew.

## 5. What the title claims (confidence ladder)

| Title | Claim | What it does not claim |
|---|---|---|
| `42%` | Captured at most 20 min before the last render. Usage only grows inside a window, so the real figure is at least this unless the window reset since. | That it is current. 20 minutes of heavy use can move it by tens of points. |
| `~42%` | A reading exists but is older than 20 min. | Anything about now. |
| `—` | No usable reading for the 5h window, the window is known to have reset, or the reading is older than the window itself. | Nothing. This is the honest "I don't know". |
| `42% / 12%` | Same, with the weekly window appended (setting "Add weekly %"). One `~` in front covers both. | |
| `⚙` `…` `?` | No data, with the reason in the dropdown. | |
| icon only | Rings drawn from the same values. No age marker. | Freshness (C5). |

The "Updated" line adds the clock time of the capture and which client wrote
it (`via Claude app` or `via Claude Code`), or `⚠ hh:mm · stale 45m`,
`stale 3h`, `stale 2d`.

## 6. Scenario matrix

Columns: source retained, what the menu bar shows in the "icon + percentage"
and "percentage only" modes (icon mode shows the rings only), dropdown, and
whether an alert can fire at that render. Verdict: **OK** (code matches the
rules), **FIXED-n** (a gap of the first version, closed on
`fix/display-strategy-gaps`, section 7.2), **GAP-n** (section 7.3),
**CHOICE-n** (section 7.4).

Notation: `5h` and `7d` are the readings, `t` is their age at render.

### 6.1 Desktop app only (statusline never wired, or its file missing)

This is the everyday case for a VS Code extension or Cowork user.

| # | Situation | Retained | Title | Dropdown | Alert | Verdict |
|---|---|---|---|---|---|---|
| A1 | Sample `t` ≤ 20 min | desktop | `42%` | `5-hour: 42% (resets --)`, `Updated hh:mm (via Claude app)` | on crossing | OK |
| A2 | Sample 20 min < `t` (app idle, Mac asleep, app quit) | desktop | `~42%` | `⚠ hh:mm · stale Nm (Claude app idle?)` | no (value frozen) | OK |
| A3 | Sample older than the window itself (5h reading > 5 h old, weekly > 7 d old): Mac asleep overnight with the app idle, or app quit for days | desktop | `—` while the weekly is inside its 7 days and the weekly option is off, `~— / 18%` with it on, `— / —` past 7 days | `5-hour: — (reading older than the window)`, `⚠ hh:mm · stale 3d` | no, baseline set to 0 | FIXED-1 for the number, FIXED-6 for the title, FIXED-7 for the age |
| A4 | Burst between two samples: 26 % at `t0`, exhausted at `t0+10`, next sample at `t0+30` (the incident) | desktop | `26%` until `t0+20`, then `~26%` until `t0+30`, then `100%` | as A1 then A2 | at `t0+30` (95 % crossed) | OK per R1, CHOICE-1 |
| A5 | 5h window resets between two samples: 100 % then 12 % | desktop | `12%` | `resets --` | baseline follows the drop | OK |
| A6 | Weekly reset moved earlier by the server, seen as a drop between two samples | desktop | `12%`, weekly `2%` | `resets --` | none (weekly has no alert) | OK |
| A7 | Desktop file changes format (`version` ≠ 2), or unreadable | none | `⚙` | guide says "open the Claude desktop app" although it is running | no | OK per R5/R6, wording noted in 7.4 |
| A8 | Several organisations in the history | desktop, last sample whatever its org | as A1 | | | CHOICE-6 (ADR 0003) |
| A9 | First render after launch, already at 97 % | desktop | `97%` | | none (no baseline) | OK per R7 |
| A10 | New window opens between two samples already above 80 %: 98 % seen, then 85 % in the new window, no reset time in this feed | desktop | `85%` | `resets --` | none for 80 % (the drop lowers the baseline to 85, a later 95 % crossing still fires) | CHOICE-2 |

### 6.2 Statusline only (desktop app not running)

The CLI user's case.

| # | Situation | Retained | Title | Dropdown | Alert | Verdict |
|---|---|---|---|---|---|---|
| B1 | Active terminal session, capture ≤ 20 min | statusline | `42%` | `5-hour: 42% (resets 2h 10m)`, `via Claude Code` | on crossing | OK |
| B2 | Session closed, capture aged, resets still ahead | statusline | `~42%` | stale + countdowns | no | OK |
| B3 | Capture present, 5h `resets_at` has passed, no newer capture | statusline | `—` (5h row void), weekly still shown | `5-hour: — (reset; awaiting Claude Code)` | baseline re-anchored at 0 | OK. The title reads `—`, never `~—`, whatever the weekly's age (FIXED-6) |
| B4 | The 5h window reaches `resets_at` while a terminal session is idle: Claude Code drops the window and re-runs the script, which writes a weekly-only capture | statusline | `—`, weekly at the measurement's age | `5-hour: --`, `Updated` at the measurement time, stale once it is 20 min old | not at this render (window absent, `_last_pct` and `_last_reset` untouched), but the next capture carries a reset time never seen and anchors the baseline at 0 (F8) | FIXED-2 for the alert, FIXED-8 for the timestamp |
| B5 | Session start, resume or `/clear`: Claude Code renders before it has `rate_limits` | previous capture kept by the script | unchanged | unchanged | | OK (v1.0.1) |
| B6 | Idle session re-rendered for a non-quota reason (permission mode, vim toggle, `/compact`, a user-set `refreshInterval`): same values | statusline | `42%`, then `~42%` once the measurement is 20 min old | `Updated` at the measurement time | none (no change) | FIXED-4: the script keeps the previous `captured_at` when both windows are identical |
| B7 | No `rate_limits` ever (Free, Team, Enterprise, or before the first response) and no earlier file | none | `…` | `Waiting for Claude Code activity…`, "Pro or Max" | no | OK |
| B8 | File corrupt | none | `?` | | no | OK |
| B9 | `resets_at` as an ISO string, or malformed | statusline | `42%` | `resets 2h 10m` or `resets ?` | | OK |
| B10 | 5h window reset detected by the one-shot timer (5 s after `resets_at`) without any new capture | statusline | `—` | reset row | re-anchored | OK |

### 6.3 Both sources present

| # | Situation | Retained | Title | Dropdown | Alert | Verdict |
|---|---|---|---|---|---|---|
| C1 | Both fresh, statusline newer, both windows | statusline wholesale | `42%` | countdowns, `via Claude Code` | on crossing | OK |
| C2 | Both fresh, desktop newer, statusline resets still ahead | desktop % + statusline countdown | `42%` | `resets 2h 10m`, `via Claude app` | on crossing | OK |
| C3 | Desktop newer, statusline 5h `resets_at` passed, desktop sampled **after** the reset | desktop % without countdown | `12%` | `resets --` | baseline follows | OK |
| C4 | Desktop newer, statusline 5h `resets_at` passed, desktop sampled **before** the reset | statusline window (void) | `—` | `reset; awaiting Claude Code` (the next desktop sample will resolve it, not Claude Code) | re-anchored | OK, wording in 7.4 |
| C5 | Statusline newer but windowless (session start) | desktop wholesale, desktop timestamp | `42%` | `via Claude app` | | OK (PR #15 then #16 fix) |
| C6 | Statusline partial (weekly only, the reset-drop capture of B4), desktop ≤ 20 min and sampled **after** the reset | desktop wholesale when its sample is newer than the measurement the capture repeats, which is the usual case after an idle terminal (FIXED-8), otherwise statusline weekly + desktop 5h dated from the desktop sample (FIXED-3) | `12%` | `resets --`, `Updated` at the desktop sample time, `via Claude app` | baseline follows (no reset time on the filled window) | OK |
| C7 | Same as C6 but the desktop sample **predates** the reset that caused the drop | same routing as C6, the desktop 5h describes the old window either way. The desktop-newer branch only has a pre-reset guard when the statusline window carries the reset time, which the reset-drop capture no longer does | `100%` shown as fresh for up to one desktop cadence | `Updated` at the desktop sample time (FIXED-3 changes the date, not the number) | none | GAP-4, still open, ADR 0004 |
| C8 | Statusline newer and partial, desktop aged | statusline only | `—` for the missing window | | | OK |
| C9 | Desktop newer, a window missing from the desktop sample (not observed in a month of data) | desktop + statusline window if statusline ≤ 20 min | | | | OK |
| C10 | Idle session re-rendered (B6) while the desktop has a fresher true value | desktop, being fresher | `81%` from the desktop, the display no longer goes backwards | `via Claude app` | once | FIXED-4: the re-run keeps the measurement's timestamp, so the desktop sample outranks it |
| C11 | Both aged, statusline newer | statusline | `~42%` | stale | no | OK |
| C12 | Both aged, desktop newer | desktop, statusline-only windows dropped | `~42%` | stale | no | OK |
| C13 | Same instant, different values (rounding, or the CLI's last response older than the desktop sample) | fresher by write time | | | | OK per R2, and CHOICE-2 on tie-breaking |
| C14 | Weekly reset moved earlier by the server: desktop newer shows the drop, statusline countdown still points to the old date | desktop % + stale countdown | weekly `2%`, `resets 5d` (wrong date) | | | CHOICE-3 |
| C15 | Usage burns in Cowork while a terminal session sits idle: the CLI feed does not move | desktop, being fresher | `42%` | `via Claude app` | on crossing | OK by design (ADR 0003) |
| C16 | Both sources. The 5h window resets while the user works outside the terminal, the desktop feed crosses 80 % in the new window (alert fires, baseline follows), then the first Claude Code message of that window captures 87 % with a reset time never seen | statusline | `87%` | countdown, `via Claude Code` | none for 80 %: the desktop reading that followed the reset forgot the ended window, so the reset time arriving with the capture has nothing to be later than and the baseline stays at 85 | FIXED-5 |

### 6.4 Time and machine events

| # | Situation | Retained | Title | Dropdown | Alert | Verdict |
|---|---|---|---|---|---|---|
| D1 | Mac wakes after hours. The pre-sleep title stands until the next render (immediate if the timer was due during sleep, else up to one interval) | last render | pre-sleep value, no `~`, until re-rendered | | | OK per section 2, CHOICE-4 |
| D2 | Refresh interval set to "Every hour" | | a title without `~` can be up to 20 min + 60 min old | | | CHOICE-4 |
| D3 | Clock moved backwards, `captured_at` in the future | | treated as fresh | | | OK (no rule needed) |
| D4 | `captured_at` missing or garbled in the statusline file | treated as maximally old in the merge, but rendered with no `~` and no age ceiling when alone | `42%` | `Updated: --` | | GAP-5c |

### 6.5 Display modes and options

| # | Situation | Title | Icon | Verdict |
|---|---|---|---|---|
| E1 | Icon + percentage (default) | two-space spacer + text, with `~` when aged | rings, empty ring for a void or absent window | OK |
| E2 | Percentage only | text, with `~` | none | OK |
| E3 | Icon only | empty, `~` never visible | rings, no freshness signal | decided, CHOICE-5 |
| E4 | "Add weekly %" on, in modes E1 or E2 | `42% / 12%`, `42% / —`, `~42% / 12%`, `~— / 12%` | | OK |
| E5 | "Add weekly %" on, icon mode | no effect (the inner ring already is the weekly) | | OK |
| E6 | Error states in any mode | glyph shown, text in dropdown | cleared | OK |
| E7 | Pillow absent (source install) | text as usual | static icon kept | OK |

### 6.6 Alerts

| # | Situation | Alert | Verdict |
|---|---|---|---|
| F1 | 5h goes 78 → 83 between two renders | one alert, 80 % | OK |
| F2 | 5h goes 78 → 97 in one step | one alert, 95 % | OK |
| F3 | Sits at 85 % across renders | none | OK |
| F4 | Drops below 80 % then crosses again in the same window (was only possible through C10) | none | FIXED-4, no longer reachable |
| F5 | Crossing seen on an aged reading | fires | OK (decided, R7) |
| F6 | First render after launch at 97 % | none | OK (R7) |
| F7 | 5h reset seen as a present window with a past `resets_at` (B3, C4), then 85 % in the new window | fires | OK (fix/honest-freshness) |
| F8 | 5h reset seen as the window vanishing from the capture (B4), then 85 % | fires at the first capture of the new window, its reset time being new | FIXED-2 |
| F9 | 5h reset seen as a drop in the desktop feed (A5) | baseline follows the drop, next crossing fires | OK |
| F10 | Weekly crosses 80 % | none, by design | CHOICE-7 |
| F11 | Homebrew or source install | never delivered by macOS | documented |
| F12 | Desktop feed already alerted in the new window, then the statusline sees the new reset time (C16) | none | FIXED-5 |
| F13 | The 5h `resets_at` value drifts by a second inside one window (not observed, the documented shape is one fixed time per window) | none, only a later reset time marks a new window | FIXED-5 (`test_a_jittery_reset_time_does_not_realert`) |

## 7. Verdicts

### 7.1 Already correct

The core of the strategy is in place and matches R1 to R9:

- Fresher-wins per window, with the pre-reset guard on the desktop side
  (`_merge_window`) and the symmetric fill of a partial capture guarded by
  the 20-minute threshold (`_merge_usage`).
- A windowless capture never hides a usable desktop reading, and a partial
  one never wipes the other window.
- A window whose reset time has passed is void, not shown as a stale number
  (`_window_row`), and the one-shot timer re-renders right after the reset.
- Age is visible in the title (`~`) in both text modes, once, including the
  weekly variant, and in the dropdown in every mode.
- Error states are explained and clear the icon.
- Alerts fire on upward crossings only, are not gated on freshness, and the
  baseline is re-anchored at a detected reset, in both shapes a reset takes
  in the statusline feed.
- A reset time is compared as a time, and only a later one marks a new
  window. A reading without a reset time forgets a reset that has passed, so
  a window is never anchored at 0 twice.
- The `~` marker only qualifies a number the title actually shows.
- The freshness line reads in minutes, hours or days, and names the source
  whose time it shows.
- A reading that has outlived its window is void, per window, whatever the
  source.
- A merged reading dates itself from its oldest part, and a capture that
  repeats a measurement keeps that measurement's time.
- Every source is parsed defensively and read-only. The capture script
  cannot raise and never overwrites good windows with an empty render.

Tests cover each of these (173 green on `fix/display-strategy-gaps`).

### 7.2 Fixed on `fix/display-strategy-gaps`

The first version of this document listed these as gaps. Each entry keeps
the original diagnosis, then says what the branch did and how this revision
checked it against the code.

**FIXED-1 (was GAP-1). No age ceiling on a reading.**
Diagnosis: a 5h reading older than 5 hours describes a window that has
certainly ended, likewise a weekly reading older than 7 days, and the app
showed it as `~42%` for days (A3).
Fix: `_FIVE_HOUR_SECS` and `_SEVEN_DAY_SECS` in `tracker.py`, applied in
`_window_row` through the `age` and `span` arguments, after the `resets_at`
check. The age is the merged reading's `captured_at` seen from render time.
A voided window shows `— (reading older than the window)` in the dropdown,
the empty ring, and the dash in the title.
Checked: A3 is closed for the number. For a statusline reading with a valid
`resets_at` the reset check fires first, since a window's reset is never
later than its span after the measurement, so the ceiling matters for the
desktop feed and for a capture whose `resets_at` is unreadable (B9). Both
merge branches date the reading from a source at most 20 minutes old when
they mix windows, so the ceiling never voids a window that another source
had fresh. Two side effects followed: the `~—` title after every long sleep
(GAP-5a, closed as FIXED-6) and a reading with no `captured_at` skipping the
ceiling (GAP-5c, 7.3).

**FIXED-2 (was GAP-2). A reset that removes the window lost the next alert.**
Diagnosis: the documented shape of a 5h reset in the statusline feed is a
capture without `five_hour`, and the re-anchor ran only on a window present
with a past `resets_at`, so a new window opening at 85 % raised nothing
(B4, F8).
Fix: `_maybe_notify` receives the window's `resets_at` and keeps the last
one seen in `_last_reset`. A reset time different from the last one seen
marks a new window and the baseline is taken as 0 for that comparison.
Checked: B4 leaves `_last_pct` and `_last_reset` untouched (the window is
absent, the `else` branch only resets the row text), and the first capture
of the new window carries a reset time that differs, so 85 % fires (F8,
`test_a_new_window_alerts_even_below_the_previous_peak`). A dip inside one
window stays silent since its reset time does not change
(`test_same_window_does_not_realert_on_a_dip`). The constraint of the first
version holds: an absent window is not treated as a reset, only a new reset
time is, so session start and Free plans are unaffected. In the mixed
merge, a desktop reading carries the statusline's reset time while it is
ahead, so the new-window detection also works for desktop readings as long
as the statusline saw the window. The fix had one wrong case, GAP-6, where
the same new window was anchored at 0 twice, closed as FIXED-5.

**FIXED-3 (was the R8 caveat, not a numbered gap). A merged reading claimed
the capture's freshness.**
Diagnosis: when a partial capture was completed from the desktop feed, the
`Updated` line and the `~` marker used the capture's time, so the filled
window could be up to 20 minutes older than the line said. ADR 0003 had
accepted that.
Fix: `_merge_usage`, statusline-fresher branch, sets the merged
`captured_at` to the desktop sample's time whenever a window was filled
(`test_a_filled_window_dates_the_display_from_the_desktop`).
Checked: the fill only happens when the desktop sample is at most 20
minutes old, so the merged age never reaches the `~` threshold or the age
ceiling through this path, and the desktop-newer branch already dated the
merge from the desktop sample. R8 is rewritten above. This is not a fix for
C7: the filled window can still describe the old window (GAP-4). The `via`
label now names the desktop next to the desktop's time (FIXED-7).

**FIXED-4 (was GAP-3, for the identical-capture case). `captured_at` was
re-stamped on every statusline run.**
Diagnosis: every statusline re-run that was not a new assistant message
re-emitted the last response's values with a new timestamp, so hours-old
values outranked a truer desktop sample, the display went backwards with no
`~` (B6, C10), and the 80 % alert could fire twice in one window (F4).
Fix: `statusline/tokease-statusline.py` reads the current file before
writing and keeps its `captured_at` when both windows, percentage and reset
time, equal the current ones
(`test_identical_windows_keep_the_first_timestamp`).
Checked: B6 and C10 keep the measurement's timestamp, so the desktop sample
wins when it is fresher and the statusline reading goes stale in place. F4
is no longer reachable through C10. Within R9: one more read of the same
file, still never raises. The case of a vanished window is FIXED-8.
CHOICE-2 was not needed for this fix.

**FIXED-5 (was GAP-6, opened by FIXED-2). The same new window could be
anchored at 0 twice, which repeated an alert.**
Diagnosis: `_last_reset` was only updated by a reading carrying a
`resets_at`. Desktop readings carry none once the statusline's reset has
passed, so after a 5h reset seen from the desktop side `_last_reset` still
named the ended window while the desktop feed tracked the new one and fired
its 80 % alert. The first Claude Code message of that window brought a reset
time never seen, the baseline was taken as 0 again, and the same 80 % fired a
second time (C16, F12). The comparison was also between two ISO strings, so a
reset time moving by a second would have anchored at 0 on every render (F13).
Fix: `_maybe_notify` in `tracker.py`. A reading with no reset time that
arrives once the reset on file has passed clears `_last_reset`, since the
window being tracked can no longer be named. Reset times are compared as
parsed datetimes, and only a later one marks a new window.
Checked: C16 no longer re-alerts
(`test_no_second_alert_when_the_new_window_reset_finally_arrives`), a reset
time moving back by one second stays silent
(`test_a_jittery_reset_time_does_not_realert`), and F8 still fires
(`test_a_new_window_alerts_even_below_the_previous_peak`, the new reset time
is later). B4 is unaffected: the window is absent there, `_maybe_notify` is
not called, `_last_reset` keeps naming the ended window until the new one
appears with a later time. In-memory state only, nothing written.

**FIXED-6 (was GAP-5a). `~—` as a whole title.**
Diagnosis: when the 5h window was void or absent, the weekly reading aged and
the weekly option off, the title was `~—`. A marker on a placeholder says
nothing, and since FIXED-1 this was the title after every sleep longer than 5
hours for a desktop user (A3).
Fix: `_update_display` marks the title only when it shows a number
(`shows_a_number`: a 5h value, or a weekly value with the weekly option on).
Checked: `test_no_stale_marker_on_a_title_showing_no_number` and
`test_reading_older_than_the_five_hour_window_is_void` assert `—`.
`~— / 18%` stays when the weekly option is on and the weekly is aged
(`test_weekly_survives_an_age_that_voids_the_five_hour`), since a number is
shown. The dropdown keeps the stale line in every case.

**FIXED-7 (was GAP-5b, plus the `via` wording of 7.5). The stale label
counted in minutes without bound, and a filled merge named the wrong
source.**
Diagnosis: `stale 4320m` in `_freshness_label` (A3). And a merge that took
the desktop sample's time (FIXED-3) still said `via Claude Code`, so the line
named one source and dated from the other (C6).
Fix: `_humanize_age` in `tracker.py` (minutes under an hour, hours under a
day, days past that). `_merge_usage` copies the desktop's `source` along with
its `captured_at` when a window was filled.
Checked: `test_a_long_stale_age_reads_in_hours_or_days` (3 d and 4 h).
`test_merge_fresher_partial_statusline_keeps_desktop_window` now asserts
`source == "desktop"` and the desktop time. R8 rewritten above.

**FIXED-8 (was the GAP-3 residual). A capture that lost a window was stamped
as new.**
Diagnosis: the script kept `captured_at` only when both windows were equal.
The reset-triggered capture of B4 differed by the missing window, so its
weekly value, which is the last response's value and can be hours old, was
written with the current time and shown as fresh. It also made that capture
fresher than the desktop sample and routed C6 and C7 through the fill.
Fix: `statusline/tokease-statusline.py` keeps the timestamp when every window
present in the payload equals the current file's, with at least one present.
A window that appears or changes still stamps the capture anew. A capture
carrying no window at all is stamped anew too, since there is no measurement
to repeat, which is harmless: the app reads a windowless file as `waiting`
and never reaches its timestamp
(`test_a_windowless_re_run_restamps_a_windowless_file`).
Checked: `test_a_capture_that_lost_a_window_keeps_the_timestamp` (red
before), `test_a_window_that_reappears_restamps_the_capture`,
`test_a_changed_weekly_in_a_partial_capture_restamps`. B4 now shows the
weekly at its real age. C6 usually routes through the desktop-newer branch,
since the capture keeps a time older than the desktop sample
(`test_a_weekly_only_capture_older_than_the_desktop_lets_the_desktop_win`).
When the desktop sample is newer but itself aged, that same branch now
applies instead of the fill guard, so the statusline weekly is no longer
shown under a fresh `Updated` line: the display carries the `~` marker and
`stale Nh`. This does not close GAP-4: in C7 the desktop sample wins the
merge and still carries the old window, with the same 5h value and the same
`_meta` as before. Within R9: same file, same directory, still never raises.
The same commit makes `_read_current` return `{}` for a file holding valid
JSON that is not an object, which used to raise `AttributeError` on the
comparison and leave the capture dead for good
(`test_a_non_dict_usage_file_does_not_block_the_capture`, red before).

### 7.3 Gaps still open

Ordered by impact on the user. Each gives the location and the constraint,
the design is the implementer's call. All fit inside R9.

**GAP-4 (unchanged). The partial-capture fill has no pre-reset guard.**
Not touched by the branch. The fill in `_merge_usage` copies the desktop 5h
window whenever the desktop sample is at most 20 minutes old, and the
desktop reading it takes, through the fill or through the desktop-newer
branch since FIXED-8, is in the documented case sampled around the reset
Claude Code just reported. If the desktop sample predates that reset, the
old window's percentage (often 100 %) is shown as fresh with no countdown
until the next desktop sample (C7). FIXED-3 changes only the date under it,
and the age ceiling does not help since the sample is minutes old. It is
the mirror image of the incident (over- instead of under-estimating), less
harmful, still false with confidence. The evidence the guard needs is the
reset time that the reset-triggered capture no longer carries, and the
branch keeps it in memory: `_last_reset` holds the last 5h reset time seen,
until a reading with no reset time arrives after it has passed (FIXED-5
clears it then). A window with no reset time whose capture time is before
`_last_reset`, itself in the past, describes the ended window and should be
void, the same way `_merge_window` voids a desktop sample that predates a
known reset. That check can live in `_update_display`, where `_last_reset`
is at hand, or the capture script can persist the dropped window's
`resets_at` so the guard survives an app restart. Both stay inside
`~/.tokease`. The choice between the two is an architecture decision,
opened as ADR 0004.

**GAP-5c (cosmetic, unlikely). No or garbled `captured_at`.**
A statusline file with no usable `captured_at` is ranked as maximally old
in `_merge_usage` but rendered with no `~`, no age ceiling and
`Updated: --` when it is the only source (D4). Only the capture script
writes that file and it always stamps an integer, so this needs a hand edit
or a foreign writer. R1 says an unknown age is not a fresh one. Location:
`_update_display`, where `age` is `None` and every age check is skipped.

### 7.4 Choices that belong to the product owner

Re-read after the branch: two shrank to a default that can be recorded
without more code, five are unchanged.

**CHOICE-1 (unchanged). What "fresh" promises for the desktop source.** R1
bounds age at 20 minutes for both sources. The measured desktop cadence
makes that the right threshold for "the client is still alive", but the
incident shows 20 minutes is enough for the 5h window to go from a quarter
to exhausted, and the data shows a 59-point jump inside 5 minutes. Options:
keep the single threshold and document the claim as in section 5 (current),
or add a softer intermediate marker for desktop-sourced readings past their
median cadence, or show the age in the title itself. All stay within R9.

**CHOICE-2 (reduced). Tie-breaking, and a drop as evidence of a new
window.** FIXED-4 and FIXED-8 closed GAP-3 by keeping the measurement's
timestamp,
without any "highest reading wins" rule, so the tie-break no longer shapes a
fix and C13 stays on write time. What is left is the desktop-only feed,
which has no reset time: a new window is only visible there as a drop, the
baseline follows the drop, and a window opening between 80 % and 95 % right
after a higher reading loses its 80 % alert (A10, the 95 % one still
fires). Treating a large drop as a new window would restore it, at the cost
of the exception already noted (a server-side limit change lowers the
percentage with no reset) and of the noise guard the branch tests for.
Proposed default: keep the current behaviour unless A10 is observed.

**CHOICE-3 (unchanged). Countdown after a server-side reset shift.** When
the weekly percentage drops while the statusline's reset time is still
ahead (C14), the percentage is right and the countdown is wrong until the
next terminal message. A drop is strong but not certain evidence of a
rollover (same exception as CHOICE-2). Options: keep the countdown
(current), or blank it on a drop and let the next capture restore it. R4
and R5 lean toward blanking.

**CHOICE-4 (unchanged). Render cadence versus the freshness claim.** Age,
and now the age ceiling, are evaluated at render time only, so a title
without `~` can be older than 20 minutes by up to the refresh interval (D1,
D2), and after a wake the pre-sleep title can stand until the timer fires.
Options: re-evaluate the marker on a fixed short cadence without re-reading
the files, re-render on wake, or cap the interval options. All are local,
none touches R9.

**CHOICE-5 (reduced). Icon-only mode hides age.** Decided on
`fix/honest-freshness`: leave as is, the ring is a template image with no
tint to spare and the dropdown carries the signal. The first version asked
to revisit once an age ceiling existed. It does now: the ring empties once
a reading outlives its window, so the blind spot is bounded to a frozen
ring between 20 minutes and 5 hours old. Proposed default: record the
decision as settled.

**CHOICE-6 (unchanged). Several organisations in the desktop history.** The
last sample is taken whatever its organisation (ADR 0003, "not handled in
v1").

**CHOICE-7 (unchanged). Weekly alerts.** Only the 5h window notifies. The
weekly window is the one that locks a user out for days.

### 7.5 Wording only

- The `reset; awaiting Claude Code` row is shown to desktop-only users too
  (C4), where the next desktop sample resolves it.
- The `⚙` guide tells a user whose desktop file changed format to open the
  desktop app they already run (A7). The README already points to the two
  diagnostic commands.

## 8. Existing decisions this document keeps or asks to revise

Kept: ADR 0001 (statusline is the authorised feed and the only one with reset
times), ADR 0003 (desktop history as read-only secondary source, fresher wins,
alerts not gated on freshness), the 20-minute threshold and the `~` marker
from `honest-freshness.md`, the icon-mode decision (CHOICE-5, proposed as
settled in 7.4).

Updated on `fix/display-strategy-gaps`: ADR 0003 now states the age ceiling,
the new-window re-anchor on a reset time never seen, and the mixed merge
dated from the older source. `docs/CHANGELOG.md` lists each behaviour.

To revise:

- `statusline-data-source.md` still states the 15-minute threshold and
  describes the statusline as the only source. Both predate ADR 0003 and the
  freshness fix.
- `honest-freshness.md` lists the origin of the 02:40 capture as unknown.
  Section 3.2 explains it (window dropped at `resets_at`, script re-run).
  Its "out of scope" monotonic guard is FIXED-4 and FIXED-8 here.
- ADR 0003 states the desktop cadence as 5 to 15 minutes. The month of data
  behind this document shows the tail matters more than the mode: p90 is 45
  minutes. A sentence on the tail would make the "lag up to ~20 min" line
  honest.
- The tracker's module docstring still says the desktop refreshes "~5 min",
  and the comment above `_DESKTOP_HISTORY_FILE` says 5 to 15.

## 9. Invariant check

Every rule above is satisfied by reading two local files and writing inside
`~/.tokease`. No rule here asks for the Keychain, the network, a Claude Code
hook payload, or any change to the capture script's never-raise contract.
FIXED-4 already changed what the capture script writes (it keeps a
timestamp) and added one read of its own file, still without raising. The
FIXED-8 changed it again (keeping a timestamp when a window vanished) and one
option for GAP-4 would too (keeping a reset time), both inside the same
file and the same directory. FIXED-5 is in-memory state only. A rule that
would need the measurement time
from Claude Code itself is not available on the documented surface and is
not proposed.

One item outside this document but adjacent to it, from the launch backlog:
`_render_dynamic_icon` writes a PNG on every render from the main thread and
an `OSError` there is not caught by `_apply_usage`. It concerns the app's
own robustness, not the truth of the display.
