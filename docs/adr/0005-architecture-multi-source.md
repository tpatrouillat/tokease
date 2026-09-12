# ADR 0005 — Adding a usage source without touching the token-free invariant

- **Status**: Proposed (2026-09-12)
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

**One reader per source, mirroring `_read_desktop_usage`**: a module-level
path constant, one function that returns a normalised dict or `None`, every
exception swallowed, absent on any anomaly (R5). The reader keeps exactly the
fields the dropdown shows and names nothing else in the file. It is bounded:
it never loads more of a file than it needs (the Codex reader reads a 256 KB
tail, not a 1.4 MB rollout).

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

**The public claims move in the same PR.** "Two local files" and "1,000
lines" are bound to the code; the integration spec lists every sentence that
changes. A source that cannot be described in one honest README line is not
admitted.

## Consequences

**Positive**
- The promise is unchanged in kind: still only vendor-written local files,
  still zero network paths, still one file to audit.
- Adding Codex is about 95 lines and touches no Claude code path beyond two
  keyword arguments.
- The rule is checkable: R9, a row in the matrix, a reader shaped like the
  desktop one, a literal in the tripwire, the README lines.

**Negative / accepted limits**
- The read surface widens from two quota files to a conversation log. The
  reader keeps four numbers from its tail, but it opens the user's Codex
  session file; README and `PRIVACY.md` must say so plainly rather than hide
  behind "read-only".
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

## References

- [`multi-provider-feasibility.md`](../specs/multi-provider-feasibility.md) — who passes R9
- [`codex-integration.md`](../specs/codex-integration.md) — the first source under this rule
- [`display-strategy.md`](../specs/display-strategy.md) — R1, R3, R4, R5, R9
