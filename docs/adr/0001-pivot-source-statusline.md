# ADR 0001 — Pivot de la source de données : endpoint OAuth → statusline Claude Code

> **Mise à jour 2026-06-16 :** la décision de conserver l'endpoint en legacy est révisée par [ADR 0002](0002-retrait-mode-endpoint.md) — l'endpoint est retiré de v1.0.

- **Statut** : Accepté (2026-06-14)
- **Décideur** : Thibault
- **Concerne** : `tracker.py` (acquisition des données d'usage), distribution, README

## Contexte

Tokease affiche la consommation du plan Claude (fenêtre 5 h, hebdo) dans la barre
de menus macOS. Jusqu'ici, la donnée était obtenue ainsi :

1. lecture du token OAuth d'abonnement dans le Keychain (`Claude Code-credentials`) ;
2. appel de `https://api.anthropic.com/api/oauth/usage` avec ce Bearer + un
   User-Agent imitant `claude-code/*`.

**Problème (bloquant).** Les *Consumer Terms* d'Anthropic, clarifiés en février 2026,
restreignent l'usage du token OAuth d'abonnement (Free/Pro/Max) à **Claude Code et
Claude.ai uniquement** ; tout autre outil est non autorisé, avec un blocage côté
serveur (jan. 2026) et une application au niveau du compte (avr. 2026). Le mécanisme
ci-dessus viole donc probablement ces conditions, et l'imitation du User-Agent sert
précisément à contourner le blocage serveur. Lancer publiquement reviendrait à
inviter des utilisateurs à risquer leur compte Claude payant.

**Élément nouveau (mai 2026).** Depuis Claude Code **2.1.x**, Claude Code transmet
lui-même, sur l'entrée standard de tout script de *statusline*, les champs suivants
(documentés officiellement) pour les abonnés Pro/Max :

```
rate_limits.five_hour.used_percentage   (+ resets_at, epoch s)
rate_limits.seven_day.used_percentage   (+ resets_at, epoch s)
```

La donnée qui n'existait que dans l'endpoint risqué est désormais **fournie par
Claude Code lui-même**, dans une surface d'intégration supportée.

## Décision

Faire de la **statusline la source de données par défaut et autorisée** :

- un script (`statusline/tokease-statusline.py`) que l'utilisateur branche sur la
  statusline de Claude Code capte `rate_limits` depuis stdin et l'écrit, en écriture
  atomique, dans `~/.tokease/usage.json` (horodaté `captured_at`) ;
- `tracker.py` lit ce fichier à chaque rafraîchissement et l'affiche.

La donnée étant remise par Claude Code, on reste dans le périmètre « usage **avec**
Claude Code » → **conforme aux conditions**. On ne lit plus le token, on n'appelle
plus l'endpoint, on n'imite plus le User-Agent dans ce mode.

L'ancien mode **endpoint est conservé** comme `legacy`, sélectionnable dans les
Réglages, **désactivé par défaut**, derrière un avertissement ToS explicite. La
version endpoint complète est par ailleurs figée dans git au tag `v0.9.0-endpoint`.

## Conséquences

**Positives**
- Conforme aux conditions d'Anthropic ; aucun risque pour le compte de l'utilisateur.
- Champ `rate_limits` officiellement documenté → contrat stable, bien moins fragile
  que l'endpoint non documenté.
- Plus de lecture de token ni d'imitation de User-Agent dans le mode par défaut.

**Négatives / limites assumées**
- **Fraîcheur** : la donnée ne se met à jour que pendant que Claude Code tourne (la
  statusline ne « tick » que sur activité). Claude Code fermé → dernière valeur connue.
  Atténué par un horodatage visible, un marquage « périmé » et la détection des
  fenêtres déjà réinitialisées (on n'affiche pas un vieux % comme s'il était frais).
- **2 anneaux au lieu de 3** : la statusline n'expose pas le détail par modèle
  (sonnet/opus) ni l'overage payant → lignes affichées en `n/a` dans ce mode.
- **Friction d'installation** : Claude Code n'autorise qu'une seule commande de
  statusline. Pour les utilisateurs qui en ont déjà une, on fournit un *snippet* à
  insérer plutôt qu'un remplacement (cf. spec). Le pitch « zéro config » s'affaiblit.
- **Prérequis** : Claude Code ≥ 2.1.x.

**Alternatives écartées**
- *Endpoint OAuth par défaut* : non autorisé (le blocage initial).
- *Admin Usage & Cost API* : autorisée mais cible les clients API/Console et
  Enterprise, pas les plafonds d'abonnement Pro/Max → autre produit.
- *Logs locaux (façon ccusage)* : autorisé mais montre la consommation, pas le
  plafond restant → cœur de valeur perdu.
- *Programme OAuth tiers officiel* : n'existe pas à ce jour.

## Références

- Doc officielle statusline (champs `rate_limits`) : https://code.claude.com/docs/en/statusline
- The Register (clarification du ban, fév. 2026) : https://www.theregister.com/2026/02/20/anthropic_clarifies_ban_third_party_claude_access/
- Usage & Cost API (Admin) : https://platform.claude.com/docs/en/manage-claude/usage-cost-api
