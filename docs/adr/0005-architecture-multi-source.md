# ADR 0005 — Adding a usage source without touching the token-free invariant

- **Status**: Proposed (2026-09-12; revised 2026-09-13 after the Codex challenge: R9 is necessary, not sufficient; readers are fail-closed; public claims describe what the reader does). The first source under this rule, Codex, is **not being built**: Brain decision 0005 was signed on 2026-09-13 as option C — wait for a quota-only file upstream rather than read a conversation log. This ADR therefore describes the rule a future source must satisfy, not work in progress
- **Decision maker**: Thibault
- **Affects**: `tracker.py` (acquisition and dropdown), `tests/test_tracker.py` (`TokenFreeInvariantTest`), README, `PRIVACY.md`
- **Builds on**: [ADR 0002](0002-retrait-mode-endpoint.md) (no token, no network), [ADR 0003](0003-source-secondaire-plan-usage-desktop.md) (read a vendor's own local file, defensively)

## Context

Tokease reads two Claude feeds and merges them into one reading per window.
The feasibility matrix ([`multi-provider-feasibility.md`](../specs/multi-provider-feasibility.md))
finds one other tool, Codex, whose client writes its quota to a local file.
The four others only expose theirs behind an authenticated endpoint, which
ADR 0002 removed for good.

The question is not "how to read Codex" (that is
[`codex-integration.md`](../specs/codex-integration.md)) but what rule lets a
new source in, so the next one does not reopen the promise, and so the code
does not grow a provider framework for two sources.

## Decision

**A source is admitted only if it passes R9 as written** (`display-strategy.md`):
a local file the vendor's own client writes for its own use, read as is, no
token, no network, no Keychain, writes confined to `~/.tokease`. A tool that
fails this is "not integrable", never "to be worked around". The matrix is the
record of who passes; a new candidate gets a row there first.

**R9 is necessary, not sufficient.** R9 says where the file comes from and
what the reader may not do (token, network, Keychain, writes outside
`~/.tokease`). It says nothing about what else the file holds. A source
whose file contains only quota (the Claude desktop history, the statusline
capture) is admitted by R9 alone. A source whose file contains anything
else, a conversation log, tool outputs, a working directory, changes the
public promise even when the reader keeps four numbers, because the reader
deserialises those lines before discarding them. Its admission is a
**product decision recorded in Brain** (`projects/Tokease/decisions/`), not
a rule this ADR can grant. Codex is the first such source: gated on Brain
decision 0005.

**One reader per source, mirroring `_read_desktop_usage`**: a module-level
path constant, one function that returns a normalised dict or `None`, every
exception swallowed, absent on any anomaly (R5). The reader keeps exactly the
fields the dropdown shows, plus the discriminator that identifies the right
record when the file holds several kinds (`limit_id == "codex"` for Codex,
which the vendor's own client also filters on), and names nothing else in
the file. It is bounded: it never loads more of a file than it needs (the
Codex reader reads a 512 KB tail, not a 5.6 MB rollout), and the bound is
measured on the event the reader stops at, not on a neighbouring one. It is
**fail-closed**: it reads the one file that holds the newest data and
returns absent when that file gives nothing. It never substitutes an older
file, because the older file's number predates usage the reader cannot see,
and would be shown as fresh.

**Providers are never merged.** `_merge_usage` reconciles two feeds of one
account; a second vendor is another account with its own windows, its own
"Updated" line and its own stale marker. It gets its own block in the
dropdown, hidden when absent. Title, rings, alerts and the error glyphs stay
Claude, which is the product, until Brain decides otherwise.

**No abstraction before a third source.** Two readers and two display
blocks are two functions each. A `Provider` class, a registry or a plugin
list would be written for a source that does not exist; the matrix says the
next one is at best a vendor change away. The existing helpers
(`_window_row`, `_freshness_label`) take a client name as a keyword instead
of being duplicated.

**The tripwire grows with the source.** Each source adds to
`TokenFreeInvariantTest` the literal that names its credential file
(`auth.json` for Codex, next to `Claude Code-credentials`), so a future
reader cannot name it either. The guard stays AST-based and the "small
enough to read" argument stays the real proof.

**The public claims move in the same PR, and describe what the reader
does.** "Two local files" and "1,000 lines" are bound to the code; the
integration spec lists every sentence that changes. The sentence says what
the function does to the file (loads a tail, parses it from the end,
discards what it crosses), not only what it keeps: a reader that
deserialises conversation lines before dropping them is described as doing
so. A source that cannot be described in one honest README line is not
admitted.

## Consequences

**Positive**
- The technical promise is unchanged: still only vendor-written local
  files, still zero token, zero network paths, still one file to audit. The
  read-surface promise is not, and this ADR does not pretend it is (see
  the first accepted limit below, and Brain 0005).
- Adding Codex is about 88 lines and touches no Claude code path beyond two
  keyword arguments. The fail-closed rule made the reader smaller (no
  candidate loop), not larger.
- The rule is checkable: R9, a row in the matrix, a reader shaped like the
  desktop one, a literal in the tripwire, the README lines.

**Negative / accepted limits**
- The read surface widens from two quota files to a conversation log. The
  reader loads the tail of the user's Codex session file and deserialises
  its lines, conversation and tool output included, until it meets the last
  quota event; it keeps four numbers and drops the rest. README and
  `PRIVACY.md` must say exactly that, not "read-only" and not "never reads
  the conversation". Whether the product accepts this by default, behind an
  opt-in, or waits for a quota-only file upstream is Brain decision 0005,
  not this ADR.
- Fail-closed costs coverage: when the newest rollout carries no usable
  quota event (Codex Desktop builds seen here write `rate_limits: null`),
  the block is absent rather than fed by an older session. Measured at 31 %
  of September wall time on the dev machine (spec § 1.2).
- Each vendor format is undocumented (same grey level as ADR 0003). One more
  break point per source; absent-on-anomaly is the only failure mode.
- Heterogeneous windows (5 h, 7 d, 30 d, or one window only) mean the
  dropdown labels come from the data, not from a fixed pair. The title and
  rings cannot take a second provider without a product decision.
- Without an abstraction, a third source means a third reader and a third
  block by hand. That is the moment to abstract, not before.

**Rejected alternatives**
- *A generic `Provider` interface now*: one implementation per vendor plus a
  registry for two sources is a framework for a hypothetical. Rejected until
  a third source exists.
- *Folding Codex windows into `five_hour` / `seven_day` and merging*: makes
  `_merge_usage` look applicable across accounts, and breaks on the plans
  with one window or a 30-day window. Rejected (matrix § 3).
- *An opt-in network mode with the user's token for the other four tools*:
  exactly what ADR 0002 removed. A product decision for Brain if ever wanted,
  not a technical option here.
- *A second provider in the title or the rings*: a product choice about what
  Tokease is; out of scope for an architecture ADR.
- *Falling back to an older rollout when the newest yields nothing* (the
  5-candidate walk of the first draft): shows a superseded reading under a
  fresh "Updated" line. Rejected; absent instead, tested by
  `test_newest_rollout_without_reading_is_absent` (spec § 3).
- *Admitting Codex by R9 alone, with "same argument as the desktop history"
  in the README*: the argument was false, the file is not a quota file.
  Rejected; the admission is a product decision (Brain 0005).

## References

- [`multi-provider-feasibility.md`](../specs/multi-provider-feasibility.md) — who passes R9
- [`codex-integration.md`](../specs/codex-integration.md) — the first source under this rule
- [`display-strategy.md`](../specs/display-strategy.md) — R1, R3, R4, R5, R9
- Brain `projects/Tokease/decisions/0005-lecture-du-journal-codex.md` — the product decision that gates Codex (proposed, unsigned)
