# Spec — honest freshness across the two sources

Date: 2026-09-02. Status: implemented on branch `fix/honest-freshness`.

## The incident

On 2026-09-01 the menu bar showed **26 %** for the 5-hour window while the
quota was in fact exhausted. Reconstructed from the two local files:

| Time (local) | Desktop sample, 5h | Statusline capture |
|---|---|---|
| 22:56 | 17 % | none (VS Code extension + Cowork never run the statusline) |
| 23:11 | 26 % | none |
| 23:26 | *missing* | none |
| 23:41 | 100 % | none |
| 02:40 next day | — | `seven_day: 0 %`, no `five_hour` at all; origin explained in `display-strategy.md` § 3.2 |

Root causes, all confirmed against the code:

1. **The desktop cadence is bimodal, not the flat ~5 min the README claims.**
   Re-measured on 1086 samples over a month: half the gaps are 5 min, a quarter
   are 15 min, 6 % exceed 20 min, and the app skips samples while idle. (The
   first pass read this as "typically 15 min", which the distribution does not
   support: the median is 5 min.) The incident gap was 30 min, so a reading can
   look live while being far behind.
2. **The title carries no staleness signal.** Only the dropdown "Updated" line
   flags stale data. The number in the menu bar is what the user reads.
3. **The merge is asymmetric.** `_merge_usage` returns the statusline capture
   wholesale when it is fresher and carries *any* window. A partial capture
   (weekly only) therefore throws away the desktop's 5h reading: the 02:40
   capture made the app show `— / 0 %` until the next desktop sample.
   The reverse direction (window missing from the desktop) is already handled
   per window, with a freshness guard.

## Changes

### A. Symmetric per-window merge

When the statusline is fresher but lacks a window that the desktop feed has,
fill that window from the desktop reading, guarded the same way as the
existing direction: only when the desktop sample is not stale. `_meta` stays
that of the fresher source.

Implemented without going through `_merge_window`: that helper exists to
reconcile a desktop percentage with a statusline `resets_at`, and in this
direction the statusline has no entry for the window at all, so there is
nothing to reconcile. A guarded copy is the whole fix.

### B. Staleness visible in the title and the ring

When the merged data is older than the stale threshold, the title must say so
(proposal: `~26%`, same marker in the "5h / weekly" title variant), and the
dropdown line keeps its current wording. The ring may stay as is.

Threshold: **20 min**, up from 15. The knee in the measured distribution sits
between 15 and 18 min (the share of gaps exceeding the threshold drops from
15 % to 6 % there), so 15 flags the app's own 15 min cadence as stale while 20
covers it with jitter to spare and still fires within 30 min. The ring stays
as is.

### C. Documentation

README and ADR 0003: replace "every ~5 minutes" by the measured cadence and
state the resulting worst-case lag plainly. The sentence "Stale data is always
visibly flagged" becomes true only once B ships.

## Out of scope

The monotonic guard on `_apply_usage` and the origin of the 02:40 capture were
out of scope here. Both are settled in `display-strategy.md`: the origin in
section 3.2 (Claude Code drops a window at its `resets_at` and re-runs the
statusline without it), the guard as FIXED-4 and FIXED-8.

Also left alone: a merged reading reports the `_meta` of its fresher source,
so a window filled from the other source can be older than the "Updated" line
says. Both merge directions share that approximation, and narrowing it means a
third freshness rule for a bounded 20 min error. Recorded in ADR 0003 instead.

## Rules for the fix

- Every behavioural change ships with a test that **fails before the patch**,
  proven by reverting the patch and running the test (lesson from PR #15,
  whose fix was dead code).
- Diff kept minimal, no refactor. ruff + pytest green. Branch + PR, no merge.
