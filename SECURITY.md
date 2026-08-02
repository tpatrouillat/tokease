# Security Policy

Tokease reads local usage data written by official Claude clients (the Claude
Code statusline feed and the Claude desktop app's quota history file). It
**never reads your OAuth token, never opens your Keychain, never makes a network
call, and collects no telemetry** (see [`PRIVACY.md`](PRIVACY.md)). Security
reports are still very welcome.

## Reporting a vulnerability

Please **do not** open a public issue for a security problem.

1. Preferred: GitHub → **Security → Report a vulnerability** (private advisory)
   on this repository.
2. Fallback: open a regular issue saying only that you found a security problem
   and how to reach you — **without any technical details** — and a private
   channel will be arranged.

Include what you found, how to reproduce it, and the impact. Expect an initial
response within a few days. Once a fix ships, you'll be credited in the release
notes unless you prefer otherwise.

## Scope

In scope: the menu bar app (`tracker.py`), the statusline capture script
(`statusline/`), and the install scripts. Out of scope: vulnerabilities in
Claude Code, macOS, or third-party dependencies themselves (report those
upstream).

## Supported versions

Only the latest released version receives fixes.
