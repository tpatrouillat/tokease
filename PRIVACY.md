# Privacy

Tokease is local-only and collects nothing. Here is exactly what it does and
doesn't touch.

## What it reads

- `~/.tokease/usage.json` — the `rate_limits` windows (`five_hour`,
  `seven_day`: used percentage + reset time) that the Tokease statusline capture
  script writes from the data **Claude Code hands to its statusline**.
- `~/Library/Application Support/Claude/plan-usage-history.json` — the quota
  samples the **official Claude desktop app** writes locally for its own use
  (read-only; Tokease never writes to or modifies anything under the Claude
  app's folder).

## What it never does

- **Never reads your OAuth token** and **never opens the macOS Keychain.**
- **Never calls any Anthropic endpoint** (or any other server). Tokease makes no
  network requests at all: it only reads local files. The one exception is the
  Support menu, which opens GitHub in your browser when *you* click it.
- **No telemetry, no analytics, no account, no tracking.** Nothing leaves your
  machine.
- Stores no credentials or secrets on disk.

## What it stores

- App preferences (display mode, refresh interval, alert toggle) in the standard
  macOS `NSUserDefaults` for the app.
- The captured usage windows in `~/.tokease/usage.json`, a best-effort error
  log in `~/.tokease/statusline.err`, and the rendered menu bar icon in
  `~/.tokease/tokease-icon.png`.

To remove the app's files, run `uninstall.sh`, which deletes `~/.tokease/`, the
LaunchAgent, and the Tokease `statusLine` block (with a backup). Homebrew users:
run it first (`bash "$(brew --prefix)/opt/tokease/libexec/uninstall.sh"`), then
`brew uninstall tokease`. `brew uninstall` alone removes the app but leaves
`~/.tokease/` and the statusline wiring in place.

The `NSUserDefaults` preferences (display mode, refresh interval, alert and
weekly-title toggles) are left in place by macOS convention. For the `.app`
bundle they live under `com.tpatrouillat.tokease` (`defaults delete
com.tpatrouillat.tokease`). For Homebrew or source installs they live under
Python's shared `org.python.python` domain: delete the individual keys
(`defaults delete org.python.python display_mode`, and likewise
`alerts_enabled`, `interval_secs`, `title_weekly`) rather than the whole
domain, which other Python apps may share.

Not affiliated with Anthropic.
