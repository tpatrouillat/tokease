# Phase 0 Reconnaissance — Tokease Repository Inventory

Date: 2026-09-09  
Scope: Public Python CLI / macOS menu bar app (v1.0)  
Status: Shipped, distributed via Homebrew

---

## Brain / ADR Context

**Product Promise:** Tokease reads Claude usage quota **without ever reading an authentication token**. This is the foundational invariant, verified in CI by a regression test (`TokenFreeInvariantTest` in tests/test_tracker.py) that reads the AST of every shipped file.

**ADRs (one-line summaries):**
- **ADR 0001** (2026-06-14): Pivot data source from OAuth endpoint → Claude Code statusline (`rate_limits` field), authorized by construction since Claude Code hands over the data.
- **ADR 0002** (2026-06-16): Remove endpoint mode entirely from v1.0; statusline is now the only source. Eliminates ToS risk and token-read code paths, making the "token-free" claim defensible by code inspection.
- **ADR 0003** (2026-07-20): Add Claude desktop app's `plan-usage-history.json` as a secondary read-only source, merged by freshness; statusline is primary (only source of reset times), desktop fills gaps when fresher. Covers VS Code extension usage where statusline doesn't tick.
- **ADR 0004** (2026-09-04): In-memory guard (`_predates_last_reset`) to void desktop samples measured before a 5h window reset that the statusline already reported, closing scenario C7 (pre-reset over-estimate).

**Stated Claims (README):**
- One 1,000-line Python file (`tracker.py`) plus optional 178-line capture script (`statusline/tokease-statusline.py`).
- No HTTP client imported anywhere; zero network calls, no update checks, no telemetry.
- Reads only two local files: desktop app quota history (zero-config) and statusline `rate_limits` (optional, adds reset countdowns).

---

## 1. Repository Tree (Depth ~3, Excluding .git/venv/node_modules)

```
/home/user/tokease/
├── tracker.py                          # Main app (1,000 lines)
├── setup.py                            # py2app configuration
├── pyproject.toml                      # Ruff config (target-version, linting rules)
├── requirements.txt                    # Dependencies (rumps, Pillow)
├── sonar-project.properties           # SonarCloud config
├── build.sh                            # Build .app bundle with py2app
├── install.sh                          # Install to venv + LaunchAgent + statusline setup
├── uninstall.sh                        # Remove LaunchAgent, ~/.tokease/, settings.json wiring
├── CLAUDE.md                           # Brain context imports
├── AGENTS.md                           # Project guidance (2 KiB)
├── README.md                           # 15 KiB, main documentation
├── ROADMAP.md                          # v1.0/v1.1 scope (10 KiB)
├── SECURITY.md, PRIVACY.md, LICENSE    # Legal / trust docs
├── CONTRIBUTING.md                     # Dev setup, commit conventions
│
├── .github/
│   ├── workflows/ci.yml               # CI: ruff lint + pytest on py3.10-3.13
│   ├── dependabot.yml                 # Automated dependency updates
│   └── ISSUE_TEMPLATE/ + PULL_REQUEST_TEMPLATE.md
│
├── assets/
│   ├── menubar-template.png           # Icon template bundled by py2app
│   ├── icon.icns                       # macOS app icon
│   ├── build-logos.py                 # Asset build script
│   ├── build-menubar-icon.py          # Dynamic icon renderer (companion to tracker.py)
│   └── logo-*.png, favicon-*.png      # Marketing assets
│
├── docs/
│   ├── adr/                           # 4 ADRs (0001-0004), markdown
│   ├── specs/                         # Implementation specs (display-strategy.md, statusline-data-source.md, honest-freshness.md)
│   ├── CHANGELOG.md                   # Version history
│   ├── index.html, privacy.html, terms.html  # Generated web docs
│   ├── screenshot.png                 # Menu bar demo
│   └── og-image.png, sitemap.xml, robots.txt
│
├── statusline/
│   ├── tokease-statusline.py         # Capture script (178 lines), reads Claude Code stdin → ~/.tokease/usage.json
│   ├── install-statusline.sh         # Wiring helper for settings.json
│   └── README.md                      # Statusline setup guide
│
└── tests/
    └── test_tracker.py               # 2,222 lines, 188 test methods, 29 test classes
```

---

## 2. Lines of Code by Language/File

| File | Lines | Type | Notes |
|------|-------|------|-------|
| `tracker.py` | 1,000 | Python | Main app, claimed 1,000-line target |
| `tests/test_tracker.py` | 2,222 | Python | 188 test methods, 29 test classes; mocks rumps, tests both sources and display logic |
| `statusline/tokease-statusline.py` | 178 | Python | Capture script, reads Claude Code stdin JSON, writes atomically to `~/.tokease/usage.json` |
| `setup.py` | 41 | Python | py2app configuration (app metadata, icon, bundle ID) |
| `pyproject.toml` | 12 | TOML | Ruff linting config (target-version py310, security rules) |
| `build.sh` | 64 | Bash | py2app build orchestration; outputs `dist/Tokease.app` |
| `install.sh` | ~150 | Bash | Venv setup, optional LaunchAgent, statusline helper |
| `uninstall.sh` | ~80 | Bash | Clean up ~/.tokease/, LaunchAgent, settings.json wiring |
| `statusline/install-statusline.sh` | ~60 | Bash | Copy capture script, offer to wire settings.json with jq or sed |
| `assets/build-*.py` | 2 × ~100 | Python | Logo/icon generation (not shipped) |
| **Total tracked code** | **~3,900** | | tracker.py + statusline + tests + setup; ~1,450 shipped lines |

---

## 3. Dependency List

**Direct dependencies (from requirements.txt):**
- `rumps==0.4.0` — macOS menu bar app wrapper (NSStatusItem abstraction)
- `Pillow==12.3.0` — Dynamic icon rendering (ring arcs)

**PyObjC (implicit via rumps):**
- `PyObjC` — Foundation/AppKit bindings; imported by rumps for menu bar
  - Used by tracker.py for `AppHelper.callAfter` (main-thread marshalling)
  - Used for `NSUserDefaults` (settings persistence)
  - Used for `NSBundle` (Dock-icon suppression)

**Build/CI dependencies:**
- `py2app` (build.sh only) — Convert tracker.py to Tokease.app
- `pytest==9.1.1` (CI only) — Test runner
- `ruff==0.15.22` (CI) — Linter; Python 3.10+ target, security rules (flake8-bandit)

**No dependencies for:**
- HTTP / network (no urllib, requests, httpx, etc.)
- OAuth (no keychain read, no token handling)
- API calls (no endpoint consumption)

---

## 4. Entry Points

**Primary entry point (menu bar app):**
- **File:** `/home/user/tokease/tracker.py` (lines 999–1000)
- **Trigger:** `if __name__ == "__main__": App().run()`
- **Invocation paths:**
  1. **From source/Homebrew:** `python tracker.py` (called by LaunchAgent or `brew services`)
  2. **From py2app `.app` bundle:** launched via Finder/Dock, runs frozen Python bytecode with bundled assets
  3. **Manual:** `python3 /path/to/tracker.py` from any terminal

**Secondary entry point (statusline capture):**
- **File:** `/home/user/tokease/statusline/tokease-statusline.py` (lines 173–178)
- **Trigger:** `if __name__ == "__main__": … sys.exit(0)`
- **Invocation:** Claude Code pipes JSON to stdin via `statusLine.command` in settings.json
- **Location after install:** `~/.tokease/tokease-statusline.py` (copied by `statusline/install-statusline.sh`)

**Build scripts (not runtime):**
- `build.sh` — Produces `dist/Tokease.app` via py2app
- `install.sh` — Venv setup + LaunchAgent + optional statusline wiring
- `uninstall.sh` — Cleanup (~/. tokease/, LaunchAgent, settings.json edits)
- `statusline/install-statusline.sh` — Copy capture script, edit settings.json

**No console_scripts or setuptools entry points** (py2app builds a standalone `.app` instead).

---

## 5. External Services / Network Calls

**Zero network calls in shipped code.**

Evidence (grep results):
- No `urllib`, `requests`, `http`, or `socket` imports anywhere
- `tracker.py` line 189: single URL reference is `STAR_URL = "https://github.com/tpatrouillat/tokease"` (used for browser.open() when user clicks "Star" in menu, read-only, no API)
- `statusline/tokease-statusline.py`: no network imports, no HTTP

**File reads only:**
1. `~/.tokease/usage.json` — Written by the capture script; read by `tracker.py`
2. `~/Library/Application Support/Claude/plan-usage-history.json` — Written by Claude desktop app; read read-only by `tracker.py`

**Subprocess calls (macOS integration only):**
- `/usr/bin/osascript` (lines 251–282 in tracker.py) — Invoke AppleScript for launch-at-login setup (controlled input, security-reviewed)
- No `subprocess` calls in statusline script

**No endpoints, no API keys, no token reads.**

---

## 6. Environment Variables

**Referenced in shipped code:**

| Variable | File | Line(s) | Purpose | Set by |
|----------|------|---------|---------|--------|
| `RESOURCEPATH` | tracker.py | 74 | Path to bundled assets in py2app frozen bundle | py2app (macOS bundle loader) |
| `TOKEASE_STATUSLINE_QUIET` | statusline/tokease-statusline.py | 168 | Suppress statusline output when used as a snippet | User/integration (optional) |

**Not read anywhere:**
- No auth tokens, API keys, or secrets from env
- No `ANTHROPIC_*`, `CLAUDE_*`, or sensitive env vars

---

## 7. Test Files & Coverage

**Location:** `/home/user/tokease/tests/test_tracker.py` (2,222 lines, 188 test methods)

**Test classes (by functional area):**

| Class | Test Count | Coverage |
|-------|------------|----------|
| `TestSafeInt` | 10 | Safe integer parsing (None, negative, overflow, bool) |
| `TestDisplayPct` | 7 | Percentage display formatting (rounding, clamping, none-handling) |
| `TestFmtReset` | 11 | Reset time formatting (ISO parsing, relative time, timezone) |
| `TestAppDisplay` | 5 | Full menu bar display with partial data (5h, 7d, missing fields) |
| `TestAppErrorStates` | 3 | Error handling and recovery paths |
| `TestIntervalManagement` | 5 | Refresh interval settings, persistence, fallback |
| `TestMainThreadMarshalling` | 2 | AppKit safety (main-thread dispatch of UI updates) |
| `TestResetRefreshScheduling` | 4 | Timer scheduling for upcoming resets |
| `TestConstants` | 6 | Hard-coded values (thresholds, timeouts) |
| `TestEdgeCases` | 7 | Boundary conditions (no data, malformed JSON, clock skew) |
| `TestErrorClearsStaleIcon` | 3 | Stale marker behavior on errors |
| `TestMaybeNotify` | 8 | Threshold alerts (80%, 95%, once-per-window) |
| `TestApplyDisplayModes` | 3 | Display mode toggles (icon, %, both) |
| `TestPreResetGuard` | 6 | ADR 0004 guard: void pre-reset desktop samples (C7 scenario) |
| `TestIconWriteFailure` | 2 | Icon rendering failures (disk full, permission) |
| `TestCorruptedSettings` | 2 | NSUserDefaults corrupted data fallback |
| `TestUnknownBuckets` | 1 | Unknown fields in JSON (ignore gracefully) |
| `TestSectionPresentNullReset` | 2 | Section display when reset_time is null |
| `TestEpochToIso` | 3 | Epoch-to-ISO conversion |
| `TestStatuslineSource` | ~10 | Statusline JSON parsing, window extraction, merge |
| `TestDesktopSource` | ~8 | Desktop JSON parsing, version guard, defensive reads |
| `TestStatuslineDisplay` | ~10 | Statusline-driven display (freshness, reset times) |
| `TestStatuslineErrorStates` | ~4 | Error log file handling |
| `TestStatuslineScript` | ~10 | Capture script atomicity, stdin parsing, carry-over logic |
| `TestStatuslineRenderLine` | ~8 | Statusline text rendering |
| `TestRenderIcon` | ~8 | Dynamic icon generation, Pillow absent fallback |
| `TestFreshnessLabel` | ~8 | "Updated X min ago" label formatting |
| `TestStaleTitleMarker` | ~6 | "~42%" stale indicator logic |
| `TestStrategyGaps` | ~4 | Gap scenarios (C7, merge behavior, reset detection) |

**Test framework:** unittest (CI runs via pytest too; can run with `python -m pytest` or `python -m unittest discover`)

**Mocking strategy:** No real API calls; rumps and Foundation objects mocked via `FakeApp`, `FakeMenuItem`, `FakeTimer` test doubles

**Regression test:** `TokenFreeInvariantTest` (in test_tracker.py) — reads AST of every shipped file, verifies no token-reading code, no HTTP client imports. This is the CI tripwire that guards the product promise.

---

## 8. CI Configuration

**File:** `/home/user/tokease/.github/workflows/ci.yml`

**Trigger:** Every PR + every push to main

**Jobs:**

1. **Lint (ruff)**
   - OS: ubuntu-latest
   - Python: 3.13
   - Command: `ruff check .`
   - Ruff version: pinned to 0.15.22 (unpinned 0.16 broke CI in the past)
   - Config: `pyproject.toml` (target-version py310, security rules S*, exclude assets/venv/docs)

2. **Test (pytest)**
   - OS: ubuntu-latest
   - Python versions: 3.10, 3.11, 3.12, 3.13 (fail-fast: false → all versions run)
   - Command: `python -m pytest -q`
   - Dependencies: pytest 9.1.1, Pillow 12.3.0 (rumps mocked, no need to install)
   - Coverage: no formal coverage gate, but 188 tests cover most paths

**Permissions:** Read-only (GITHUB_TOKEN scoped to contents:read)

**Concurrency:** Cancel earlier runs when you push again quickly (saves CI minutes)

**SonarCloud:** Configured via `sonar-project.properties`
- Targets Python 3.10–3.13
- Source: entire repo (except assets/, venv/, dist/, graphify-out/)
- Tests: tests/ directory

---

## 9. Git Signals

**Recent activity (last 10 commits):**
```
8ec42db docs: règles Brain/graphify dans AGENTS.md, symlinks outils ignorés
3dbc71a docs: charger le brief Brain (context.md) depuis CLAUDE.md
79c4ebb docs: README sous-promettait le hash-pinning déjà shippé en v1.0.6
21f6edc docs: 1,000-line claim, pas 970 (tracker.py a grandi avec v1.0.6)
f48ea95 fix(display): round instead of truncate the shown percentage; v1.0.6
b476a2b docs: cadrage post-challenge avant Show HN (used/remaining, claim 1148 lignes, ADR ToS)
3e959b7 release: v1.0.5 (#35)
df03837 fix(compteur): tracker.py était repassé à 974 lignes (#34)
2a1c5e0 docs: deux claims du README que l'audit produit a démentis (#33)
acb4fb2 fix(reset): la date de reset hebdo s'affichait en UTC (#32)
```

**File churn (top 30, commits touching each file):**
```
29  tracker.py                          # Main app, active development
25  tests/test_tracker.py              # Test suite, grows with features
17  docs/index.html                    # Generated web docs
17  README.md                          # Frequent edits (claims, fixes)
15  docs/CHANGELOG.md                  # Versioning
13  ROADMAP.md                         # Planning, scope changes
10  docs/specs/display-strategy.md     # Implementation detail spec
7   setup.py                           # Bundle config tweaks
7   docs/adr/0003-source-secondaire-plan-usage-desktop.md  # Major feature
5   statusline/tokease-statusline.py  # Refinements (carry-over logic)
5   install.sh                         # Setup improvements
5   AGENTS.md                          # Guidance updates
```

**Untouched files (6+ months):**
- None. All tracked files touched within the last 6 months.
  - Oldest commits: logo assets, favicon, legal docs (LICENSE, SECURITY.md) — all updated within v1.0 cycle for consistency.

**Age distribution:**
- Active files (weekly–monthly): tracker.py, tests/test_tracker.py, README.md, ROADMAP.md
- Stable files (touched once for v1.0): ADRs (now frozen as decisions), setup.py, build.sh
- Generated/archival (dated on docs rebuild): index.html, CHANGELOG.md

---

## Summary Statistics

| Metric | Value |
|--------|-------|
| Total tracked files | ~50 (Python + Bash + Markdown + config) |
| Shipped code lines | ~1,450 (tracker + statusline + setup) |
| Test code lines | 2,222 |
| Test coverage (methods) | 188 tests, 29 classes |
| External dependencies | 2 (rumps, Pillow) + PyObjC (indirect) |
| Network calls | 0 (zero) |
| Token reads | 0 (verified by CI test) |
| HTTP clients imported | 0 (verified by grep) |
| ADRs (decisions recorded) | 4 (complete, frozen) |
| CI matrix | Python 3.10–3.13, ubuntu-latest |
| Platform support | macOS only (rumps dependency) |
| License | MIT |

