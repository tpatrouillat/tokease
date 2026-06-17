#!/usr/bin/env bash
#
# Tokease — Désinstallation (install depuis les sources / LaunchAgent).
#
# Retire tout ce que install.sh + statusline/install-statusline.sh ont créé :
#   - le LaunchAgent (auto-start) et tout process tracker en cours
#   - le bloc `statusLine` Tokease dans ~/.claude/settings.json (backup d'abord)
#   - le dossier de données capturées ~/.tokease/
# Ne touche NI à ton install Claude Code, NI à ton abonnement.
#
# Installé via Homebrew à la place ? Utilise :
#   brew services stop tokease && brew uninstall tokease
#
set -euo pipefail

LAUNCH_AGENT_PLIST="$HOME/Library/LaunchAgents/com.tpatrouillat.tokease.plist"
TOKEASE_DIR="$HOME/.tokease"
SETTINGS="$HOME/.claude/settings.json"
STATUSLINE_MARK="tokease-statusline.py"

echo "Tokease — désinstallation"
echo

# 1. LaunchAgent + process en cours
if [ -f "$LAUNCH_AGENT_PLIST" ]; then
  launchctl unload "$LAUNCH_AGENT_PLIST" 2>/dev/null || true
  rm -f "$LAUNCH_AGENT_PLIST"
  echo "✓ LaunchAgent retiré"
fi
pkill -f "tracker.py" 2>/dev/null || true

# 2. Bloc statusLine dans settings.json — uniquement si c'est le nôtre
if [ -f "$SETTINGS" ] && grep -q "$STATUSLINE_MARK" "$SETTINGS" 2>/dev/null; then
  if command -v jq >/dev/null 2>&1; then
    backup="$SETTINGS.bak.$(date +%Y%m%d-%H%M%S)"
    cp "$SETTINGS" "$backup"
    tmp="$SETTINGS.tokease.tmp"
    if jq 'del(.statusLine)' "$SETTINGS" > "$tmp"; then
      mv "$tmp" "$SETTINGS"
      echo "✓ Bloc statusLine retiré de $SETTINGS (backup : $backup)"
    else
      rm -f "$tmp" "$backup"
      echo "! jq a échoué — retire le bloc \"statusLine\" à la main dans $SETTINGS" >&2
    fi
  else
    echo "! 'jq' absent — retire le bloc \"statusLine\" à la main dans $SETTINGS"
  fi
elif [ -f "$SETTINGS" ]; then
  echo "note: si tu as collé le snippet Tokease dans TON propre script statusline,"
  echo "      retire-le là (settings.json ne pointe pas directement vers Tokease)."
fi

# 3. Données capturées
if [ -d "$TOKEASE_DIR" ]; then
  rm -rf "$TOKEASE_DIR"
  echo "✓ $TOKEASE_DIR supprimé"
fi

echo
echo "Désinstallation terminée."
echo "Install depuis les sources ? Supprime aussi le dossier cloné (venv inclus)."
