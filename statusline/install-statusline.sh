#!/usr/bin/env bash
# Installs the Tokease statusline capture script into ~/.tokease and offers to
# wire the `statusLine` block into ~/.claude/settings.json automatically.
# We NEVER replace an existing statusLine.command (Claude Code allows only
# one): if you already have one, we print the snippet to paste instead.
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)/tokease-statusline.py"
DEST_DIR="$HOME/.tokease"
DEST="$DEST_DIR/tokease-statusline.py"
SETTINGS="$HOME/.claude/settings.json"
COMMAND="python3 ~/.tokease/tokease-statusline.py"

if [ ! -f "$SRC" ]; then
  echo "error: $SRC not found" >&2
  exit 1
fi

mkdir -p "$DEST_DIR"
chmod 700 "$DEST_DIR" 2>/dev/null || true  # usage data is private, not readable by other accounts
cp "$SRC" "$DEST"
echo "✓ Capture script installed: $DEST"
echo

if ! command -v claude >/dev/null 2>&1; then
  echo "note: 'claude' not found in PATH — make sure Claude Code >= 2.1.x is installed."
  echo
fi

# Snippet printed when we don't write (missing settings handled, manual snippet).
print_manual_snippet() {
  cat <<EOF

Add this to ~/.claude/settings.json:

  {
    "statusLine": {
      "type": "command",
      "command": "$COMMAND"
    }
  }

If you ALREADY have a statusline, paste this block at the top of your script
instead (see statusline/README.md):

  input=\$(cat)
  printf '%s' "\$input" | TOKEASE_STATUSLINE_QUIET=1 python3 "\$HOME/.tokease/tokease-statusline.py"
EOF
}

# Writes the statusLine block via jq (guaranteed valid JSON). Idempotent: if
# the key already exists, we overwrite nothing. Timestamped backup before any
# modification.
write_with_jq() {
  local existing
  existing="$(jq -r '.statusLine.command // empty' "$SETTINGS" 2>/dev/null || true)"
  if [ -n "$existing" ]; then
    echo "A statusLine.command already exists in $SETTINGS — not overwriting."
    print_manual_snippet
    return 0
  fi
  local backup="$SETTINGS.bak.$(date +%Y%m%d-%H%M%S)"
  cp "$SETTINGS" "$backup"
  local tmp="$SETTINGS.tokease.tmp"
  if jq --arg cmd "$COMMAND" \
        '.statusLine = {"type": "command", "command": $cmd}' \
        "$SETTINGS" > "$tmp"; then
    mv "$tmp" "$SETTINGS"
    echo "✓ statusLine block added to $SETTINGS (backup: $backup)"
  else
    rm -f "$tmp" "$backup"   # no change was made → no orphan backup
    echo "error: jq failed — settings.json left untouched." >&2
    print_manual_snippet
  fi
}

# settings.json missing: create it with a minimal valid JSON.
create_settings() {
  local backup=""
  mkdir -p "$(dirname "$SETTINGS")"
  if command -v jq >/dev/null 2>&1; then
    printf '{}' | jq --arg cmd "$COMMAND" \
      '.statusLine = {"type": "command", "command": $cmd}' > "$SETTINGS"
  else
    # No-jq fallback: the file doesn't exist, so writing a full safe block is fine.
    cat > "$SETTINGS" <<EOF
{
  "statusLine": {
    "type": "command",
    "command": "$COMMAND"
  }
}
EOF
  fi
  echo "✓ $SETTINGS created with the statusLine block."
}

echo "Next step: wire the script into Claude Code."
read -r -p "Write the statusLine block into ~/.claude/settings.json automatically? (y/N) " reply || reply="n"  # EOF (non-interactive) → manual snippet
echo

case "$reply" in
  [Yy]*)
    if [ ! -f "$SETTINGS" ]; then
      create_settings
    elif command -v jq >/dev/null 2>&1; then
      write_with_jq
    else
      # settings.json exists but no jq: we won't risk corrupting an existing
      # JSON by hand → print the snippet to paste.
      echo "note: 'jq' not found — to avoid corrupting an existing settings.json,"
      echo "      we don't write automatically. Install jq, or paste the block:"
      print_manual_snippet
    fi
    ;;
  *)
    print_manual_snippet
    ;;
esac

echo
echo "Then open Claude Code and send a message: the rate_limits data"
echo "only appears after the first API response of a session."
