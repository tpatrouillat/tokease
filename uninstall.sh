#!/usr/bin/env bash
#
# Tokease — Uninstall (source install / LaunchAgent).
#
# Removes everything install.sh + statusline/install-statusline.sh created:
#   - the LaunchAgent (auto-start) and any running tracker process
#   - the Tokease `statusLine` block in ~/.claude/settings.json (backup first)
#   - the captured-data directory ~/.tokease/
# Touches NEITHER your Claude Code install NOR your subscription.
#
# Installed via Homebrew instead? Use:
#   brew services stop tokease && brew uninstall tokease
#
set -euo pipefail

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
LAUNCH_AGENT_PLIST="$HOME/Library/LaunchAgents/com.tpatrouillat.tokease.plist"
TOKEASE_DIR="$HOME/.tokease"
SETTINGS="$HOME/.claude/settings.json"
STATUSLINE_MARK="tokease-statusline.py"

echo "Tokease — uninstall"
echo

# 1. LaunchAgent + running process
if [ -f "$LAUNCH_AGENT_PLIST" ]; then
  launchctl unload "$LAUNCH_AGENT_PLIST" 2>/dev/null || true
  rm -f "$LAUNCH_AGENT_PLIST"
  echo "✓ LaunchAgent removed"
fi
# Scoped to THIS directory's tracker.py (= the path the LaunchAgent runs),
# so we don't kill an unrelated tracker.py running elsewhere. pkill -f matches
# an extended regex, so escape the path's metacharacters first.
SELF_DIR_RE=$(printf '%s' "$SELF_DIR/tracker.py" | sed 's/[.[\$()*+?{|^]/\\&/g')
pkill -f "$SELF_DIR_RE" 2>/dev/null || true

# 2. statusLine block in settings.json — only if it is ours
if [ -f "$SETTINGS" ] && grep -q "$STATUSLINE_MARK" "$SETTINGS" 2>/dev/null; then
  if command -v jq >/dev/null 2>&1; then
    backup="$SETTINGS.bak.$(date +%Y%m%d-%H%M%S)"
    cp "$SETTINGS" "$backup"
    tmp="$SETTINGS.tokease.tmp"
    if jq 'del(.statusLine)' "$SETTINGS" > "$tmp"; then
      mv "$tmp" "$SETTINGS"
      echo "✓ statusLine block removed from $SETTINGS (backup: $backup)"
    else
      rm -f "$tmp" "$backup"
      echo "! jq failed — remove the \"statusLine\" block by hand in $SETTINGS" >&2
    fi
  else
    echo "! 'jq' not found — remove the \"statusLine\" block by hand in $SETTINGS"
  fi
elif [ -f "$SETTINGS" ]; then
  echo "note: if you pasted the Tokease snippet into YOUR own statusline script,"
  echo "      remove it there (settings.json does not point directly at Tokease)."
fi

# 3. Captured data
if [ -d "$TOKEASE_DIR" ]; then
  rm -rf "$TOKEASE_DIR"
  echo "✓ $TOKEASE_DIR deleted"
fi

echo
echo "Uninstall complete."
echo "Installed from source? Also delete the cloned directory (venv included)."
