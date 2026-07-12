# Privacy

Tokease is local-only and collects nothing. Here is exactly what it does and
doesn't touch.

## What it reads

- `~/.tokease/usage.json` — the `rate_limits` windows (`five_hour`,
  `seven_day`: used percentage + reset time) that the Tokease statusline capture
  script writes from the data **Claude Code hands to its statusline**.

## What it never does

- **Never reads your OAuth token** and **never opens the macOS Keychain.**
- **Never calls any Anthropic endpoint** (or any other server). Tokease makes no
  network requests at all — it only reads a local file.
- **No telemetry, no analytics, no account, no tracking.** Nothing leaves your
  machine.
- Stores no credentials or secrets on disk.

## What it stores

- App preferences (display mode, refresh interval, alert toggle) in the standard
  macOS `NSUserDefaults` for the app.
- The captured usage windows in `~/.tokease/usage.json`, a best-effort error
  log in `~/.tokease/statusline.err`, and the rendered menu bar icon in
  `~/.tokease/tokease-icon.png`.

To remove the app's files, run `uninstall.sh` (or `brew uninstall tokease`),
which deletes `~/.tokease/`, the LaunchAgent, and the statusline wiring. The
`NSUserDefaults` preferences (display mode, refresh interval, alert toggle) are
left in place by macOS convention; clear them with
`defaults delete com.tpatrouillat.tokease` if you want a fully clean slate.

Not affiliated with Anthropic.
