# ADR 0003 — Source secondaire : historique d'usage de l'app desktop Claude

- **Statut** : Accepté (2026-07-20)
- **Décideur** : Thibault
- **Concerne** : `tracker.py` (acquisition), README (prérequis), invariant privacy

## Contexte

La source statusline (ADR 0001) ne « tick » que pendant une session Claude Code
**en terminal** (TUI). L'extension VS Code en panneau graphique n'exécute jamais
`statusLine.command` — limitation assumée par Anthropic (issue
[#55643](https://github.com/anthropics/claude-code/issues/55643) fermée « not
planned »). Or l'usage principal de Thibault (et vraisemblablement d'une part
croissante des utilisateurs) passe par l'extension → `usage.json` se périme dès
qu'aucune session terminal ne tourne, et Tokease affiche du « stale » en continu.

Pistes investiguées et écartées (2026-07-20, doc officielle + tests machine) :
- **Hooks** : aucun payload ne contient `rate_limits`.
- **Transcripts** (`~/.claude/projects/*.jsonl`) : tokens par message, jamais les
  fenêtres de quota.
- **OpenTelemetry** : métriques tokens/coût uniquement, pas de fenêtres 5 h/7 j.
- **Caches Claude Code** (`~/.claude.json`, `~/.claude/**`) : rien de structurel.

**Découverte.** L'app **desktop Claude** (`/Applications/Claude.app`) échantillonne
le quota du plan **toutes les 5 minutes** tant qu'elle tourne, et le persiste dans :

```
~/Library/Application Support/Claude/plan-usage-history.json
```

Format observé (version 2) : `{"version": 2, "samples": [{"t": <epoch ms>,
"org": "<uuid>", "u": {"fh": <% 5h>, "sd": <% 7j>}}, …]}`. Vérifié en réel :
284 échantillons sur ~29 h, cadence médiane 300 s, valeurs cohérentes avec la
statusline. La donnée est fraîche **même quand on n'utilise que l'extension VS
Code** (et même lors d'usage Claude.ai/Desktop, puisque c'est le quota du compte).

## Décision (proposée)

Ajouter `plan-usage-history.json` comme **source secondaire en lecture seule**,
fusionnée avec la statusline par fraîcheur :

- la **statusline reste la source primaire** (plus riche : elle seule fournit
  `resets_at`) ;
- si l'échantillon desktop est plus récent que `captured_at`, ses pourcentages
  (`fh` → five_hour, `sd` → seven_day) prennent le dessus pour l'affichage ;
- parsing **défensif** : `version != 2`, clé absente, JSON invalide, fichier
  manquant → on ignore silencieusement la source et on retombe sur la statusline
  (jamais de crash, jamais d'erreur visible) ;
- **lecture seule stricte** : aucune écriture hors `~/.tokease` (invariant
  inchangé), zéro réseau, zéro Keychain.

## Conséquences

**Positives**
- Donnée quasi continue (pas de trou de 20 h) dès que l'app desktop tourne —
  couvre l'usage extension VS Code, Claude.ai et Desktop, pas seulement le CLI.
- Invariant privacy intact : on lit un fichier local écrit par l'app d'Anthropic
  pour son propre usage ; pas de token, pas d'appel réseau, pas d'imitation.
  Risque ToS bien moindre que l'endpoint (ADR 0001/0002) : aucun accès serveur.

**Négatives / limites assumées**
- **Format non documenté** : interne à l'app desktop, peut changer sans préavis
  → d'où le parsing défensif + garde sur `version`, et la statusline en filet.
- **Pas de `resets_at`** : les heures de reset ne viennent que de la statusline ;
  affichées seulement si une capture statusline récente existe.
- **Prérequis** : app desktop Claude installée et lancée (menubar). À documenter
  dans le README comme « recommandé pour la fraîcheur », pas obligatoire.
- **Multi-org** : le champ `org` doit être respecté si plusieurs orgs apparaissent
  (on prend l'échantillon le plus récent, org affichée non gérée en v1).

**Conformité ToS (analyse vérifiée le 2026-07-20)**
- Les Consumer Terms (8 oct. 2025) n'interdisent ni la lecture de fichiers
  locaux créés par les apps Anthropic, ni rien d'analogue : la clause reverse
  engineering vise la décompilation (« reduce our Services to human-readable
  form » — un JSON en clair l'est déjà), les clauses automated access/scraping
  visent l'accès aux **Services** (serveurs), pas au disque de l'utilisateur.
- La clarification de février 2026 est scopée au **routage de requêtes vers les
  serveurs d'Anthropic avec un token d'abonnement** (« route requests through
  Free, Pro, or Max plan credentials ») — Tokease ne fait aucun appel réseau.
- Précédent direct : ccusage & co. lisent les JSONL locaux non documentés de
  Claude Code depuis mi-2025, à grande échelle, sans aucun enforcement connu —
  y compris après la purge OAuth de janvier-février 2026.
- Classification retenue : source statusline = autorisée (surface documentée) ;
  source desktop = zone grise faible, aucune violation identifiable des termes
  actuels. À re-vérifier si Anthropic fait évoluer ses Terms.

**Alternatives écartées**
- *Mode terminal de l'extension* (`"claudeCode.useTerminal": true`) : fonctionne
  mais impose un changement d'usage à l'utilisateur ; conservé comme conseil
  README, pas comme solution produit.
- *Feature request upstream* (exposer `rate_limits` aux hooks ou dans un cache
  documenté) : à ouvrir quand même (cf. issue
  [#20636](https://github.com/anthropics/claude-code/issues/20636)), horizon
  incertain.

## Références

- Issue #55643 (statusline extension VS Code, « not planned ») :
  https://github.com/anthropics/claude-code/issues/55643
- Issue #20636 (exposer les rate limits hors statusline) :
  https://github.com/anthropics/claude-code/issues/20636
- Doc statusline (contrat `rate_limits`) : https://code.claude.com/docs/en/statusline
- ADR 0001 (pivot statusline) · ADR 0002 (retrait endpoint)
