#!/usr/bin/env bash
# Copy the Tokease statusline capture script to a stable location (~/.tokease)
# and print the exact settings.json snippet. Never edits settings.json itself —
# Claude Code allows only one statusLine command and we won't clobber yours.
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)/tokease-statusline.py"
DEST_DIR="$HOME/.tokease"
DEST="$DEST_DIR/tokease-statusline.py"

if [ ! -f "$SRC" ]; then
  echo "error: $SRC not found" >&2
  exit 1
fi

mkdir -p "$DEST_DIR"
cp "$SRC" "$DEST"
echo "✓ Installed capture script to: $DEST"
echo

if ! command -v claude >/dev/null 2>&1; then
  echo "note: 'claude' not on PATH — make sure Claude Code >= 2.1.x is installed."
  echo
fi

cat <<'EOF'
Next: wire it into Claude Code.

If you DON'T already have a statusline, add this to ~/.claude/settings.json:

  {
    "statusLine": {
      "type": "command",
      "command": "python3 ~/.tokease/tokease-statusline.py"
    }
  }

If you DO have a statusline, paste this at the top of your existing script
instead (see statusline/README.md):

  input=$(cat)
  printf '%s' "$input" | TOKEASE_STATUSLINE_QUIET=1 python3 "$HOME/.tokease/tokease-statusline.py"

Then open Claude Code and send one message so rate_limits data is captured.
EOF
