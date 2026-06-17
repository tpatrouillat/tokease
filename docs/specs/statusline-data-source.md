# Spec — Source de données « statusline »

Réf. : [ADR 0001](../adr/0001-pivot-source-statusline.md) et
[ADR 0002](../adr/0002-retrait-mode-endpoint.md). Décrit le contrat entre le script de
statusline (producteur) et l'app menu bar (consommateur).

> Depuis l'[ADR 0002](../adr/0002-retrait-mode-endpoint.md), la statusline est la
> **seule** source de données : le mode endpoint est retiré de v1.0 (figé au tag
> `v0.9.0-endpoint`). Tokease ne lit donc jamais le token.

## Vue d'ensemble

```
Claude Code  ──(JSON stdin à chaque tick)──▶  tokease-statusline.py  ──(écriture atomique)──▶  ~/.tokease/usage.json
                                                                                                      │
                                                                              tracker.py (toutes les N s) ──┘  lit, affiche
```

## Producteur — `statusline/tokease-statusline.py`

Invoqué par Claude Code comme commande de statusline. À chaque exécution :

1. lit le JSON sur stdin (`{ ..., "rate_limits": { "five_hour": {...}, "seven_day": {...} } }`) ;
2. extrait les fenêtres présentes (chacune peut être absente — cf. doc Claude Code :
   `rate_limits` n'apparaît qu'**après le 1er échange** de la session, abonnés Pro/Max) ;
3. écrit `~/.tokease/usage.json` de façon **atomique** (écriture dans un fichier temp
   du même dossier puis `os.replace`) pour que le lecteur ne voie jamais un fichier
   partiel ;
4. imprime une ligne de statusline minimale (ou rien) — l'affichage statusline n'est
   pas le but, la capture l'est.

Contraintes : Python 3 stdlib uniquement (pas de `jq`), ne **jamais** échouer
bruyamment (un crash polluerait la statusline de Claude Code) — toute erreur est
avalée silencieusement côté script **mais** rien n'est écrit si le JSON est invalide.

## Format de fichier `~/.tokease/usage.json` (schema 1)

```json
{
  "schema": 1,
  "captured_at": 1739000000,
  "source": "claude-code-statusline",
  "five_hour": { "used_percentage": 23.5, "resets_at": 1738425600 },
  "seven_day": { "used_percentage": 41.2, "resets_at": 1738857600 }
}
```

- `captured_at` : epoch s au moment de l'écriture (sert au calcul de péremption).
- chaque fenêtre est **optionnelle** ; `used_percentage` ∈ [0,100], `resets_at` epoch s.
- pas de split sonnet/opus ni d'overage : non fournis par la statusline.

## Consommateur — `tracker.py`

`get_usage()` lit le fichier `~/.tokease/usage.json` (source unique, statusline) et
normalise vers la forme interne attendue par `_update_display`
(`{"five_hour": {"utilization": …, "resets_at": ISO}, …}`, `used_percentage`→`utilization`,
epoch→ISO), en ajoutant `_meta`. Il n'y a plus d'aiguillage de source : le mode endpoint
a été retiré (cf. [ADR 0002](../adr/0002-retrait-mode-endpoint.md)).

### États d'erreur

| Code | Déclencheur | Affichage |
|------|-------------|-----------|
| `nostatusline` | fichier absent | titre ⚙ + guide 3 étapes dans le menu (non câblé) |
| `waiting` | fichier présent, aucune fenêtre captée | « Waiting for Claude Code… » |
| `error` | fichier illisible / JSON invalide | « ? » |

### Fraîcheur & reset

- **Péremption** : si `now − captured_at > 15 min`, marquer la donnée « périmée »
  (ligne *Updated* préfixée ⚠) — signal que Claude Code ne tourne pas.
- **Fenêtre réinitialisée** : si `resets_at < now`, la fenêtre a roulé depuis la
  capture → le `used_percentage` stocké n'est plus valide. On affiche « (reset) » et
  on ne dessine pas l'anneau comme s'il était à jour.

### Rendu

- **2 anneaux** (5 h externe, hebdo interne).
- pas de split Sonnet / Opus ni d'overage : non fournis par la statusline, et le mode
  endpoint qui les exposait a été retiré (cf. [ADR 0002](../adr/0002-retrait-mode-endpoint.md)).

## Câblage côté utilisateur (friction #2)

Claude Code n'autorise **qu'une** commande de statusline (`settings.json` →
`statusLine.command`). Deux cas :

1. **Pas de statusline existante** : pointer `statusLine.command` sur
   `python3 ~/.tokease/tokease-statusline.py` (l'installeur copie le script là).
2. **Statusline existante** : insérer le *snippet* de capture (3 lignes) au début du
   script existant — il écrit le fichier puis laisse l'affichage d'origine intact.
   (On ne modifie jamais `settings.json` automatiquement : risque d'écraser une
   statusline existante.)

Détails et snippet : `statusline/README.md`.
