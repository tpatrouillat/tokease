# Launch Plan — Claude Usage Tracker

**Date:** 2026-03-11
**Status:** Production-ready

---

## Current State

- **67/67 tests passing** (0.38s, Python 3.13.5, pytest 9.0.2)
- Coverage spans: helpers, API responses, HTTP security, token cleanup, display logic, error states, edge cases
- All error paths tested (401, 403, 429, 500, timeouts, malformed JSON, truncated keychain)
- No TODO/FIXME/HACK comments in codebase

---

## Fixes Applied

None required. All tests passed on first run; code review found no issues.

---

## Project Scan Summary

- Python macOS menu bar app using `rumps` framework
- Single-file design (`tracker.py`, 338 lines)
- 67 comprehensive unit tests covering all code paths
- Reads OAuth token from `Claude Code-credentials` macOS Keychain entry
- Calls undocumented Anthropic API endpoint: `https://api.anthropic.com/api/oauth/usage`
- Menu bar shows: 5-hour utilization, weekly, Sonnet, extra usage with reset countdowns
- Configurable refresh intervals (1min, 5min, 30min, 1hr)
- Background threads prevent UI blocking
- py2app for standalone `.app` builds
- LaunchAgent support for auto-start

---

## Security Summary

| Area | Status | Notes |
|------|--------|-------|
| Secrets on disk | Clean | Zero-config design; no `.env` files; token from macOS Keychain only |
| Token handling | Excellent | Read into local variable, used once, cleared in `finally` block |
| HTTP redirects | Blocked | Custom `_NoRedirectHandler` prevents Bearer token leaking via 3xx |
| Input validation | Robust | `_safe_int()` clamps negatives, handles all edge cases |
| Exception handling | Good | No bare `except:`; specific types only; timeouts on subprocess + HTTP |
| Dependencies | Minimal | Single runtime dep (`rumps==0.4.0`); no known CVEs |
| Shell scripts | Safe | `set -euo pipefail`, quoted variables, no injection vectors |

---

## Blocking Issues for Production/Distribution

1. **Undocumented API dependency** — The `/api/oauth/usage` endpoint is not a public Anthropic API. It could change or disappear without notice, breaking the app entirely. There is no fallback data source.
2. **Hardcoded User-Agent** — Currently set to `claude-code/2.1.34`. If the endpoint begins rejecting outdated User-Agent strings, the app will stop working.
3. **Code signing** — The `.app` bundle is not signed or notarized. macOS Gatekeeper will block it for users who download it. Requires an Apple Developer account ($99/yr) to resolve.

---

## Nice-to-Have Features

| Priority | Feature | Effort |
|----------|---------|--------|
| High | **Code signing + notarization** — required for smooth distribution | Medium |
| Medium | **Rate-limit countdown** — show remaining wait time instead of just "will retry" | Small |
| Medium | **Notification on high usage** — alert when utilization exceeds threshold (e.g., 80%) | Medium |
| Medium | **Auto-update mechanism** — check for new versions on GitHub Releases | Medium |
| Low | **User-Agent version sync** — auto-detect or make configurable | Small |
| Low | **Dark mode icon variant** — adaptive menu bar icon | Small |
| Low | **Homebrew formula** — `brew install claude-usage-tracker` | Small |

---

## Distribution Checklist

- [x] All tests passing (67/67)
- [x] Security audit complete — no vulnerabilities
- [x] Dependencies pinned (`rumps==0.4.0`)
- [x] Build scripts verified (`build.sh`, `install.sh`)
- [x] Landing page ready (`docs/`)
- [x] README with installation instructions
- [x] LICENSE (MIT) included
- [x] `.gitignore` properly configured
- [ ] Code signing with Apple Developer certificate
- [ ] Notarization for Gatekeeper approval
- [ ] DMG or installer package for distribution
- [ ] GitHub Release with pre-built `.app` bundle
- [ ] Homebrew formula (optional)
- [ ] GitHub Actions workflow for automated releases (optional)

---

## Risk: Undocumented API Endpoint

The app depends entirely on `https://api.anthropic.com/api/oauth/usage`, which is an undocumented, internal Anthropic endpoint discovered from Claude Code's own traffic. Key risks:

- **Breaking changes** — The response schema could change at any time without deprecation notice
- **Endpoint removal** — The endpoint could be removed or moved behind a different auth mechanism
- **Rate limiting changes** — Current rate limits are unknown and could become more restrictive
- **ToS concerns** — Using undocumented endpoints may violate Anthropic's Terms of Service

**Mitigation:** The app handles all HTTP error codes gracefully and displays clear error states. If the endpoint breaks, users see a clear error rather than a crash. Monitor Anthropic's official API documentation for any public usage endpoint that could replace this.
