#!/usr/bin/env bash
# Installe le script de capture statusline de Tokease dans ~/.tokease et propose
# de câbler automatiquement le bloc `statusLine` dans ~/.claude/settings.json.
# On ne remplace JAMAIS une statusLine.command existante (Claude Code n'en
# autorise qu'une) : si tu en as déjà une, on affiche le snippet à coller.
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
cp "$SRC" "$DEST"
echo "✓ Capture script installé : $DEST"
echo

if ! command -v claude >/dev/null 2>&1; then
  echo "note: 'claude' absent du PATH — assure-toi que Claude Code >= 2.1.x est installé."
  echo
fi

# Snippet affiché quand on n'écrit pas (settings absent traité, snippet manuel).
print_manual_snippet() {
  cat <<EOF

À ajouter dans ~/.claude/settings.json :

  {
    "statusLine": {
      "type": "command",
      "command": "$COMMAND"
    }
  }

Si tu as DÉJÀ une statusline, colle plutôt ce bloc en haut de ton script
(voir statusline/README.md) :

  input=\$(cat)
  printf '%s' "\$input" | TOKEASE_STATUSLINE_QUIET=1 python3 "\$HOME/.tokease/tokease-statusline.py"
EOF
}

# Écrit le bloc statusLine via jq (JSON garanti valide). Idempotent : si la clé
# existe déjà, on n'écrase rien. Backup horodaté avant toute modification.
write_with_jq() {
  local existing
  existing="$(jq -r '.statusLine.command // empty' "$SETTINGS" 2>/dev/null || true)"
  if [ -n "$existing" ]; then
    echo "Une statusLine.command existe déjà dans $SETTINGS — on n'écrase pas."
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
    echo "✓ Bloc statusLine ajouté à $SETTINGS (backup : $backup)"
  else
    rm -f "$tmp" "$backup"   # aucune modif effectuée → pas de backup orphelin
    echo "error: jq a échoué — settings.json laissé intact." >&2
    print_manual_snippet
  fi
}

# Cas settings.json absent : on le crée avec un JSON minimal valide.
create_settings() {
  local backup=""
  mkdir -p "$(dirname "$SETTINGS")"
  if command -v jq >/dev/null 2>&1; then
    printf '{}' | jq --arg cmd "$COMMAND" \
      '.statusLine = {"type": "command", "command": $cmd}' > "$SETTINGS"
  else
    # Fallback sans jq : le fichier n'existe pas, on écrit un bloc complet sûr.
    cat > "$SETTINGS" <<EOF
{
  "statusLine": {
    "type": "command",
    "command": "$COMMAND"
  }
}
EOF
  fi
  echo "✓ $SETTINGS créé avec le bloc statusLine."
}

echo "Étape suivante : câbler le script dans Claude Code."
read -r -p "Écrire automatiquement le bloc statusLine dans ~/.claude/settings.json ? (y/N) " reply
echo

case "$reply" in
  [Yy]*)
    if [ ! -f "$SETTINGS" ]; then
      create_settings
    elif command -v jq >/dev/null 2>&1; then
      write_with_jq
    else
      # settings.json existe mais pas de jq : on ne risque pas de corrompre un
      # JSON existant à la main → on affiche le snippet à coller.
      echo "note: 'jq' absent — pour ne pas corrompre un settings.json existant,"
      echo "      on n'écrit pas automatiquement. Installe jq, ou colle le bloc :"
      print_manual_snippet
    fi
    ;;
  *)
    print_manual_snippet
    ;;
esac

echo
echo "Puis ouvre Claude Code et envoie un message : la donnée rate_limits"
echo "n'apparaît qu'après la 1re réponse API d'une session."
