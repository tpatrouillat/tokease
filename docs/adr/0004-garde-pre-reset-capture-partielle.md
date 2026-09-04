# ADR 0004 — Pre-reset guard for a 5h window filled from the desktop feed

- **Status**: Accepted (2026-09-04) — option A
- **Decision maker**: Thibault
- **Affects**: `tracker.py` (`_update_display` or `_merge_usage`), possibly
  `statusline/tokease-statusline.py` and the `usage.json` contract
  (`docs/specs/statusline-data-source.md`)
- **Relates to**: ADR 0001 (statusline feed), ADR 0003 (desktop feed), spec
  display-strategy section 7.3 GAP-4, scenario C7

## Context

Claude Code drops a rate-limit window once its `resets_at` passes, and re-runs
the statusline without it. The capture that lands in `usage.json` then carries
the other window only, and no reset time for the one that ended. That is the
documented origin of the partial capture in the 26 % incident.

Since FIXED-8 that capture keeps the timestamp of the measurement it repeats,
so it is usually older than the desktop sample and the desktop wins the merge
wholesale. Where it is newer, the fill copies the desktop 5h window into it.
Either way the 5h window shown comes from the desktop feed, and the desktop
feed carries no reset time.

The gap is C7. If the desktop sample was taken **before** the reset that
Claude Code just reported, its 5h percentage describes the window that ended,
often at or near 100 %, and it is shown as fresh with no countdown until the
next desktop sample lands. The measured desktop cadence over a month of
samples on one machine is a median gap of 5 minutes, p75 15 minutes and **p90
45 minutes**, with 5 % of gaps above 4 hours. So the error is not bounded by
"a few minutes": for one sample in ten it stands for three quarters of an
hour or more.

Neither existing guard helps. The age ceiling of R3 needs the reading to have
outlived its window, and this sample is minutes old. FIXED-3 changed the date
shown under the number, not the number. `_merge_window` already voids a
desktop sample that predates a known reset, but only when the statusline
window still carries that reset time, which the reset-drop capture no longer
does.

This is the mirror image of the founding incident: an over-estimate rather
than an under-estimate, so it costs the user caution rather than a surprise
lockout. It is less harmful and it is still false with confidence, which the
strategy's governing constraint rules out.

The evidence the guard needs is the reset time the vanished window carried.
The app holds it in memory today as `_last_reset`, and FIXED-5 clears it as
soon as a reading with no reset time arrives after it has passed. The
question is where that evidence should live.

## Options

**A. In-memory guard in `_update_display`.** Before `_window_row`, if the 5h
window carries no `resets_at`, `_last_reset` is set and in the past, and the
reading's `captured_at` is at or before `_last_reset`, treat the window as
void (`— (reset; awaiting a newer sample)` or the existing reset row). Order
matters: the guard reads `_last_reset` before `_maybe_notify` would clear it,
and a voided window skips `_maybe_notify`, so `_last_reset` survives until a
sample taken after the reset arrives. That ordering is implicit and nothing in
the code states it, which is the main cost of this option. Closes C7 for a
running app. Does not survive a restart inside the gap, and needs the
statusline to have seen the window's reset time before it vanished. No file
format change. About six lines and three tests (voided while the sample
predates the reset, shown once a later sample arrives, untouched when
`_last_reset` is None or ahead).

**B. Persist the vanished window's reset time in `usage.json`.** When a
payload lacks a window the current file has, the script keeps that window's
`resets_at` under an additive key (name to choose, for example
`dropped: {five_hour: {resets_at}}`), and `_read_statusline_usage` exposes it
so `_merge_usage` and `_merge_window` can void a desktop sample that predates
it, in both merge branches. Two clauses are needed, not one:

- **Carry-over.** At the next render the file no longer holds the window, it
  holds `dropped`, so a rule keyed on "the file has the window" stops firing
  and the field is lost after a single render. Claude Code re-runs the
  statusline several times a minute, so the script must carry `dropped`
  forward from one file to the next for as long as the window stays absent.
- **Expiry.** Nothing has to clean the field up. The guard only fires while
  the desktop sample is at or before the recorded reset, so once that reset is
  behind the desktop feed a forgotten `dropped` is inert. No state leak, no
  cleanup path to write and test.

The guard becomes a pure function of the two files, testable through
`fetch_usage`, and survives a restart. Changes the file contract (additive
field, `schema` stays 1 or bumps, `statusline-data-source.md` to update).
Inside R9: same file, same directory, the script still never raises. With the
carry-over clause, about twenty lines across the script and the reader, plus
tests on both sides.

**C. Accept the gap.** Document C7 as a known over-estimate, bounded by one
desktop cadence: median 5 minutes, p90 45 minutes, and above 4 hours for 5 %
of gaps. No code, no contract change. Defensible, since the error is on the
cautious side and the user sees a number that was true a moment earlier. The
cost is that the spec keeps one scenario where the menu bar is confidently
wrong, which is the thing the whole document exists to remove.

## Decision

**A**, the in-memory guard, implemented in `_predates_last_reset` and called
from `_update_display` before the notify path.

B and A close the same scenario and neither is more correct. B buys one thing
A does not have: the guard survives a restart inside the gap. It costs a field
in a documented file contract and a carry-over clause inside the capture
script, whose governing rule is that it must never raise and never disturb
Claude Code. Paying in that script, for a window that lasts one desktop
cadence and only matters if the app restarts inside it, is the wrong trade.
A keeps every new line inside the app, where an exception is contained, and it
is six lines against twenty.

The objection to A was an implicit call order that nothing stated. That is
answered rather than accepted: the helper's docstring says why it must run
before `_maybe_notify`, and `test_voided_window_keeps_the_reset_on_file_for_the_next_render`
fails if a later edit moves the call after it.

The limit A leaves is documented, not hidden: after a restart inside the gap,
`_last_reset` is empty and the stale desktop percentage shows again until the
next sample. Option B stays on the table if that restart case is ever observed
in the wild.

## Consequences

C7 closes for a running app: a desktop sample measured at or before a reset
the terminal already reported shows `— (reset; awaiting a newer sample)`
instead of a confident percentage, and raises no alert. The `usage.json`
contract is unchanged, the capture script is untouched, and the R9 invariant
holds (two local files read, `~/.tokease` written).

The costs: `_last_reset` dies with the process, so a restart inside the gap
reopens C7 until the next desktop sample; and `_update_display` now has a call
order that matters, pinned by a test rather than by convention.

Six lines in `tracker.py`, six tests. Three of them were run red against the
previous code and green after, and the patch was reverted to confirm they hold
it up.
