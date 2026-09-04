# Tokease — guidance projet

> **Ce repo porte le *comment*.** Le *pourquoi* — cadrage produit, décisions, état du lancement — vit dans Brain :
> `../../brain/projects/Tokease/` · règles du workspace `../../brain/AGENTS.md` · conventions Python (`../../brain/knowledge/tooling/conventions/python.md`).
> Le contexte machine (arborescence, MCP, routage des sorties) est chargé automatiquement depuis `~/.claude/CLAUDE.md`, qui importe `../../brain/context/cartographie.md`. Les autres chemins ci-dessus ne se chargent pas tout seuls : les ouvrir en début de session. Chemins locaux à la machine de dev.

App **menu bar macOS** qui suit l'usage et le quota Claude Code. Python 3.14 · rumps · Pillow · py2app. Pas de web, pas de Supabase.

Livré en v1.0 et public. Distribution par Homebrew via le tap `tpatrouillat/homebrew-tap` : toute release touche les deux repos.

## Build & Verify

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
ruff check .
python -m pytest
```

## Points d'attention

- Le lecteur de quota ne doit **jamais** lire un token d'authentification : c'est la promesse publique du produit (ADR 0003), vérifiée en CI.
- Deux sources d'usage, la plus fraîche gagne : historique de quota de l'app Claude Desktop (zéro-config) et statusline Claude Code (optionnelle, seule à donner les comptes à rebours).
- Le repo est public : aucun secret, et les claims du README engagent le produit.
