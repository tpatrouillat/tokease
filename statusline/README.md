# Tokease — Claude Code statusline setup

Tokease's default (authorized) mode reads usage that **Claude Code itself**
hands to its statusline script — no OAuth token, no API call. This guide wires
that up. Requires **Claude Code ≥ 2.1.x** and a **Pro/Max** plan (the
`rate_limits` fields only appear for subscribers).

See [`../docs/adr/0001-pivot-source-statusline.md`](../docs/adr/0001-pivot-source-statusline.md)
for the why.

## Quick setup (no existing statusline)

1. Copy the capture script to a stable location and print the wiring snippet:

   ```bash
   bash statusline/install-statusline.sh
   ```

   (This copies the script to `~/.tokease/`, then **offers** to add the
   `statusLine` block to your `settings.json` for you — with a timestamped
   backup, and never overwriting an existing statusline. Answer `n` to just
   print the snippet and do step 2 yourself.)

2. If you answered `n` (or have no `jq`), add this to `~/.claude/settings.json`
   manually:

   ```json
   {
     "statusLine": {
       "type": "command",
       "command": "python3 ~/.tokease/tokease-statusline.py"
     }
   }
   ```

3. Open Claude Code and send one message (the `rate_limits` data appears only
   after the first API response of a session). The Tokease menu bar should pick
   it up within its refresh interval.

## You already have a statusline?

Claude Code allows only **one** `statusLine.command`, so don't overwrite yours.
Instead paste this capture block at the **top** of your existing statusline
script — it writes the Tokease file, then your own rendering continues:

```sh
# --- Tokease capture (paste at the very top) ---
input=$(cat)                       # read stdin once
printf '%s' "$input" | TOKEASE_STATUSLINE_QUIET=1 python3 "$HOME/.tokease/tokease-statusline.py"
# --- end Tokease capture ---
# ...then use "$input" wherever your script previously read stdin.
```

`TOKEASE_STATUSLINE_QUIET=1` makes the capture script write the file without
printing anything, so it doesn't interfere with your statusline's output.

## How it behaves

- The menu bar shows data **as of the last time Claude Code refreshed its
  statusline**. When Claude Code is closed, it shows the last known value with a
  timestamp, and flags it as stale after 15 minutes.
- Only the **5-hour** and **weekly** windows are available (2 rings). Per-model
  (Sonnet/Opus) splits and paid overage aren't exposed by the statusline feed,
  so Tokease doesn't show them — by design, it never reads your token.

## Troubleshooting

- Menu bar shows **⚙** (with a 3-step setup guide in the dropdown) → the file
  `~/.tokease/usage.json` doesn't exist yet. Finish steps 1–2, then send a
  message in Claude Code.
- Menu bar shows **"Waiting for Claude Code activity…"** → wired correctly, but
  no `rate_limits` captured yet. Send a message in Claude Code.
- Errors are logged to `~/.tokease/statusline.err`.
- Confirm your version: `claude --version` (needs ≥ 2.1.x).
