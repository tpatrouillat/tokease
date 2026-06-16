# ADR 0002 — Retrait du mode endpoint de la build v1.0

- **Statut** : Accepté (2026-06-16)
- **Décideur** : Thibault
- **Concerne** : `tracker.py` (acquisition des données), README, distribution Homebrew, positionnement
- **Révise** : [ADR 0001](0001-pivot-source-statusline.md) (qui conservait l'endpoint en `legacy`)

## Contexte

L'[ADR 0001](0001-pivot-source-statusline.md) a fait de la statusline Claude Code la
source par défaut, **tout en conservant l'ancien mode endpoint** comme `legacy`
(désactivé par défaut, derrière un avertissement). Ce mode legacy :

1. lit le token OAuth d'abonnement dans le Keychain ;
2. appelle un endpoint Anthropic non documenté avec un User-Agent imitant Claude Code.

Trois constats au moment de figer v1.0 :

- **Risque CGU non éteint.** Tant que le code de lecture du token est présent et
  activable, le projet *invite* l'utilisateur à risquer son compte Claude payant —
  exactement ce que l'ADR 0001 voulait éviter. Garder l'option, même éteinte, maintient
  le risque produit et juridique.
- **Le wedge se dilue.** Le positionnement de v1.0 est « le seul tracker de plafonds
  Claude Code qui ne lit JAMAIS ton token ». Une formule comme « le token ne quitte
  jamais ta machine » est *fausse* tant que le mode legacy existe (il lit le Keychain).
  Un produit « token-free » qui contient quand même un lecteur de token n'est pas
  crédible.
- **Surface inutile.** Le mode legacy ajoute du code, des chemins d'erreur et une
  surface de sécurité (manipulation de Bearer, blocage de redirections) pour une
  donnée — split par modèle + overage — qui n'est pas le cœur de valeur (le plafond
  restant), et que la statusline ne fournit de toute façon pas.

La donnée endpoint (split Sonnet/Opus, overage payant) reste accessible historiquement :
la build endpoint complète est figée dans git au tag `v0.9.0-endpoint`.

## Décision

**Retirer entièrement le mode endpoint de la build v1.0.** La **seule** source de
données est désormais la statusline Claude Code (champ documenté `rate_limits` via
stdin → `~/.tokease/usage.json`).

- Plus de sélecteur « Data source » dans les Réglages : il n'y a qu'une source.
- Plus de lecture du Keychain, plus d'appel d'endpoint, plus d'imitation de User-Agent
  dans aucun chemin de code v1.0.
- La build endpoint reste préservée et auditable au tag `v0.9.0-endpoint` ; elle n'est
  plus distribuée ni maintenue.
- Le positionnement assume le wedge **token-free** : « ne lit jamais ton token »,
  conforme par construction (et non par promesse).

## Conséquences

**Positives**
- **Wedge token-free vrai et défendable** : il n'existe plus aucun chemin où Tokease lit
  le token. La phrase « ne lit jamais ton token » devient littéralement exacte.
- **Risque CGU éteint** pour l'utilisateur : impossible d'activer par erreur un mode
  non autorisé.
- **Code et surface de sécurité réduits** : plus de manipulation de Bearer ni de logique
  anti-redirection à maintenir.
- Message produit plus simple : une seule source, une seule histoire.

**Négatives / limites assumées**
- **Perte du split par modèle et de l'overage** : la statusline ne les fournit pas →
  UI à **2 anneaux** (5 h + hebdo), sans ligne Sonnet/Opus ni overage. Acté : ce
  n'était pas le cœur de valeur (le plafond restant l'est).
- **Fraîcheur** : la donnée ne se met à jour que pendant que Claude Code tourne
  (inchangé depuis l'ADR 0001) — géré honnêtement par marquage « périmé » (stale) et
  détection des fenêtres déjà réinitialisées.
- **Prérequis durcis** : Claude Code ≥ 2.1.x + Pro/Max obligatoires (plus de repli
  endpoint pour les cas non couverts).

**Alternatives écartées**
- *Garder le mode legacy éteint par défaut* (statu quo ADR 0001) : maintient le risque
  CGU et casse le wedge token-free — c'est précisément ce que cet ADR corrige.
- *Supprimer aussi l'historique git endpoint* : inutile et destructeur ; le tag
  `v0.9.0-endpoint` documente d'où l'on vient sans risque pour les utilisateurs.

## Références

- [ADR 0001](0001-pivot-source-statusline.md) — pivot vers la statusline (révisé ici).
- Tag git de préservation : `v0.9.0-endpoint`.
- Doc officielle statusline (champs `rate_limits`) : https://code.claude.com/docs/en/statusline
