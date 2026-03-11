# Launch Plan — Claude Usage Tracker

**Date:** 2026-03-11
**Status:** Production-ready

---

## Security & Code Audit Summary

**Overall Score: 9.2/10**

### Findings

| Area | Status | Notes |
|------|--------|-------|
| Hardcoded secrets | Clean | Token read from macOS Keychain only, cleared in `finally` block |
| Injection vulnerabilities | Clean | Subprocess uses list args; no `eval()`/`exec()` |
| HTTP security | Excellent | Custom `_NoRedirectHandler` blocks 3xx to prevent Bearer token leakage |
| Input validation | Robust | `_safe_int()` clamps negatives, handles all edge cases |
| Exception handling | Good | No bare `except:`; specific types only; timeouts on subprocess + HTTP |
| Dependencies | Minimal | Single runtime dep (`rumps==0.4.0`); no known CVEs |
| Shell scripts | Safe | `set -euo pipefail`, quoted variables, no injection vectors |
| Landing page (docs/) | Clean | No XSS; static content only; semantic HTML with ARIA labels |

### Fixes Applied This Session

- **Pinned `rumps` dependency** from `>=0.4.0` to `==0.4.0` for reproducible builds

---

## Test Results

- **67/67 tests passing** (0.13s)
- Coverage spans: helpers, API responses, HTTP security, token cleanup, display logic, error states, edge cases
- All error paths tested (401, 403, 429, 500, timeouts, malformed JSON, truncated keychain)

---

## Core Features — Status

| Feature | Status | Notes |
|---------|--------|-------|
| OAuth token from Keychain | Done | With regex fallback for truncation |
| API usage fetching | Done | All HTTP error codes handled |
| 5-hour utilization display | Done | Drives menu bar title |
| Weekly utilization display | Done | |
| Sonnet weekly display | Done | |
| Extra/overage tracking | Done | Shows $/limit with percentage |
| Configurable refresh interval | Done | 1m / 5m / 30m / 1h |
| Manual refresh | Done | |
| Background threading | Done | Daemon thread, non-blocking |
| Native .app bundle | Done | py2app build with LaunchAgent |
| Landing page | Done | Responsive, accessible |

---

## Missing / Blocking for Launch

None identified. The app is feature-complete for its scope (macOS menu bar usage tracker).

---

## Nice-to-Have Improvements

| Priority | Feature | Effort |
|----------|---------|--------|
| Medium | **Rate-limit countdown** — show remaining wait time instead of just "will retry" | Small |
| Medium | **Notification on high usage** — alert when utilization exceeds threshold (e.g., 80%) | Medium |
| Low | **User-Agent version sync** — currently hardcoded to `claude-code/2.1.34`; consider auto-detecting | Small |
| Low | **Pre-commit hooks** — prevent accidental secret commits | Small |
| Low | **Keyboard shortcut** — add global hotkey to trigger refresh | Small |
| Low | **Dark mode icon variant** — adaptive menu bar icon for dark/light mode | Small |

---

## Architecture Notes

- **Single-file app** (`tracker.py`, 338 lines) — appropriate for scope
- **No database** — stateless, fetches fresh data each interval
- **No network persistence** — token never stored as instance attribute
- **Minimal dependencies** — only `rumps` + Python stdlib
- **Undocumented API** — `/api/oauth/usage` is not a public endpoint; may change without notice (disclosed in README)

---

## Launch Checklist

- [x] All tests passing
- [x] Security audit complete — no vulnerabilities
- [x] Dependencies pinned
- [x] Build scripts verified (build.sh, install.sh)
- [x] Landing page live-ready
- [x] README complete with installation instructions
- [x] LICENSE (MIT) included
- [x] .gitignore properly configured
- [ ] Consider adding GitHub release workflow (optional)
- [ ] Consider adding Homebrew formula (optional)
