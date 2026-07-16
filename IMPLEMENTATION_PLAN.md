# Plan d'implémentation — renforcement du harness IDEA

**Date :** 15 juillet 2026
**Docs de référence :** [`AUDIT_SYSTEM_PROMPT_SKILLS_TOOLS_2026-07-15.md`](AUDIT_SYSTEM_PROMPT_SKILLS_TOOLS_2026-07-15.md) (état actuel) · [`HARNESS_BEST_PRACTICES_2026-07-15.md`](HARNESS_BEST_PRACTICES_2026-07-15.md) (architecture cible)
**Objectif global :** déplacer les invariants critiques du system prompt vers un control plane déterministe, observable et testable — **sans jamais tout faire d'un coup**.

---

## Principe directeur

On avance **une étape à la fois**. Chaque étape est une tranche verticale minimale qui suit la même boucle :

1. **Isoler** un seul changement (le plus petit qui a du sens).
2. **Mesurer** le comportement de l'agent sur les scénarios de référence, **avant et après**, sur plusieurs essais (la variance LLM est réelle).
3. **Garder** le changement seulement s'il améliore ou laisse stable la trajectoire ; sinon revenir.
4. **Passer à la suite** uniquement quand le *test gate* est vert.

**Règle d'or :** ne jamais retirer un verrou du system prompt tant que la version code équivalente n'est pas verte et mesurée. On ne laisse jamais prompt **et** code deviner en même temps.

---

## Scénarios de référence

Séquences figées, rejouées à l'identique pour mesurer chaque étape. À compléter, base de départ :

| ID | Scénario | Ce qu'il stresse |
|---|---|---|
| `SC-LAB` | cartes-samples-labrador, tours 1-7 | confusion fichier / EcoTaxa / dérivé de zone, verrou TSV-only, honnêteté du « 0 » |
| `SC-ENRICH` | enrichissement Amundsen + Bio-ORACLE sur fichier chargé | non-régression des chemins critiques d'enrichissement |
| `SC-ECOTAXA` | requête EcoTaxa explicite (projet nommé) | le routage source autorisé fonctionne toujours |

Chaque scénario est rejoué **N ≥ 5 fois** par mesure (variance).

---

## Métriques suivies (à chaque étape pertinente)

| Dimension | Métriques |
|---|---|
| Routage | source correcte (X/N), tool correct appelé, tool interdit proposé/exécuté |
| Sécurité | refus corrects, confirmations contournées, identifiants non fondés acceptés |
| Contexte | tokens fixes (prompt + schémas), tools exposés/tour |
| Efficacité | appels de tools par tâche, retries, latence |
| Robustesse | succès multi-essais, états invalides atteints |
| Résultat | outcome correct, provenance, artefacts valides |

---

## Étapes

### Étape 0 — Instrument de mesure *(aucun changement runtime)*

**Goal :** disposer d'un harnais de rejeu reproductible et d'une **baseline chiffrée** du comportement actuel. Prérequis absolu : « mesurer à chaque étape » est impossible sans lui.

**Livrables :**
- `evals/replay_harness.py` : rejoue un scénario (thread + store isolés, `SESSION_STORE_DIR` jetable, `user_id` unique) et capture par tour → tools exposés au modèle, tools appelés + args, **source/df réellement utilisée**, refus, réponse finale, tokens/coût.
- Scénarios `SC-LAB`, `SC-ENRICH`, `SC-ECOTAXA` figés en fixtures.
- `evals/baseline_YYYY-MM-DD.json` : métriques actuelles sur N ≥ 5 essais/scénario.

**Test gate :**
- [ ] Le rejeu d'un scénario régénère un rapport de trajectoire structuré identique en forme, run-à-run.
- [ ] Baseline produite : pour `SC-LAB`, taux « part du bon fichier » chiffré ; tokens fixes mesurés ; tools moyens/tour mesurés.
- [ ] Isolation vérifiée : aucun écrit dans le store de prod, aucune trace LangSmith de test.

---

### Étape 1 — Tests rouges qui exposent les failles *(aucune correction)*

**Goal :** rendre la dette connue **exécutable et rouge**, versionnée, avant de toucher au runtime (Phase 0 du best-practices).

**Changement :** dossier `tests/harness_redteam/` avec les tests de cohérence transversale qui échouent aujourd'hui :
- cohérence prompt ↔ `source_scope.py` sur « projet 17498 » (contradiction P0 de l'audit) ;
- opération lourde (`query_ecotaxa`, `query_ecopart`, `query_amundsen_ctd`, `query_bio_oracle`, `export_deliverable`) exécutable sans confirmation liée aux arguments ;
- `run_graph` possible hors séquence `planner → writer → run_graph` du tour courant ;
- budget fixe prompt + schémas sous seuil ;
- parité inventaire : catalogue runtime (59/62) vs `TOOLS.md`/`ARCHITECTURE.md`/`AGENTS.md`.

**Test gate :**
- [ ] Chaque test échoue **pour la bonne raison** (message qui pointe la faille réelle).
- [ ] Marqués `xfail(strict=True)` avec référence à l'étape qui les rendra verts — CI reste vert.

---

### Étape 2 — Décision de source exécutable + trancher « projet 17498 »

**Goal :** une **seule** décision de source déterministe, cohérente entre code, prompt et tests. Premier slice qui touche directement la confusion fichier/EcoTaxa.

**Changement :**
- `SourcePolicy` structurée (fichier / EcoTaxa / EcoPart / Amundsen / Bio-ORACLE / OGSL / SQL) — **extension de `tool_catalog.py`**, pas un registre concurrent.
- Trancher la règle métier : un `project_id` nu autorise-t-il EcoTaxa, oui ou non ? Aligner `source_scope.py`, le prompt et les tests sur la décision retenue.
- Le bloc de routage du prompt est **généré** depuis la politique (plus de regex + prose indépendantes).

**Test gate :**
- [ ] Le test rouge « projet 17498 » de l'étape 1 devient vert.
- [ ] Décision de source **identique** dans le code, le prompt généré et les tests, sur un jeu paramétré de formulations ambiguës.
- [ ] `SC-LAB` / `SC-ECOTAXA` : routage de source **stable ou amélioré** vs baseline (pas de régression), N ≥ 5.

---

### Étape 3 — `TurnContext` + carte d'état de session

**Goal :** l'agent **lit** son état au lieu de le ré-inférer depuis l'historique. Cœur du problème « l'agent se perd entre fichier/EcoTaxa/dérivé ».

**Changement :**
- `TurnContext` typé reconstruit en début de tour : `loaded_dataset`, dérivés vivants (avec leur zone), `explicit_source`, `source_lock`, budget. Persistant vs éphémère séparés (checkpoint/store vs expire au tour).
- La capsule passe de « df actif » à **carte d'état complète** : source de travail, dérivés+zone, périmètre/verrou.
- `source_lock` réellement porté en état (aujourd'hui seulement en prose — faiblesse P1 de l'audit).

**Test gate :**
- [ ] `SC-LAB` tours 4-7 : « part du bon df » ≥ baseline + amélioration mesurable ; `source_lock` TSV-only respecté sur N ≥ 5 essais.
- [ ] `SC-ENRICH` : **aucune régression** (les enrichissements Amundsen/Bio-ORACLE partent toujours de la bonne table).
- [ ] La carte d'état reste sous son budget (≤ 1 000 tokens cible).

---

### Étape 4 — Filtrage dynamique des tools *(≤ 15/tour)*

**Goal :** réduire le budget fixe et la compétition entre tools proches. Plus gros levier — et le plus risqué (change ce que le modèle voit).

**Changement :** `PolicyEngine` produit une allowlist par tour à partir de la `SourcePolicy` et du `TurnContext` ; le middleware `wrap_model_call` remplace `request.tools` par le sous-ensemble pertinent.

**Test gate :**
- [ ] Tools exposés/tour ≤ 15 (alerte à 12) sur tous les scénarios.
- [ ] Tokens fixes (prompt + schémas) < 40 % de `MAX_CONTEXT_TOKENS`.
- [ ] **Aucune régression** de trajectoire sur `SC-LAB` / `SC-ENRICH` / `SC-ECOTAXA`, N ≥ 5 (un tool nécessaire jamais masqué à tort).

---

### Étapes suivantes *(axe orthogonal à « se perdre » — à détailler le moment venu)*

Ces étapes traitent la sécurité et la robustesse, pas la confusion de routage. À faire **après** le cœur (0-4).

- **Étape 5 — Confirmations exécutables.** `HumanInTheLoop`/interrupt LangGraph lié à l'identité du tool + hash des arguments ; refus fail-closed. *Gate :* aucun tool lourd exécutable sans grant exact ; approve/edit/reject/expiration testés.
- **Étape 6 — Skills fail-closed versionnés.** Allowlist locale avant Hub ; provenance + hash ; `loaded_skills` remplacé par événements horodatés/turn ; automate `planner → writer → run_graph`. *Gate :* skill hors allowlist jamais chargé ; `run_graph` impossible hors séquence du tour.
- **Étape 7 — Isolation du code libre.** `run_pandas`/`run_graph` dans un worker sans réseau, sans secrets, avec quotas. *Gate :* tests d'évasion rouges deviennent verts ; pas de credentials/réseau accessibles depuis le code exécuté.
- **Étape 8 — Réduction du prompt.** Retirer les listes/séquences désormais imposées en code ; garder identité, périmètre scientifique, règles de vérité, ton, contrat de réponse. *Gate :* evals avant/après chaque suppression, pas de régression.

---

## Definition of Done (global)

Le remodelage est réussi quand :

1. Aucun invariant critique ne dépend uniquement du system prompt.
2. Chaque tour expose ≤ 15 tools (normalement 6-12).
3. Une opération lourde sans approval exact est impossible.
4. Le choix de source est identique dans le registre, le middleware et les tests.
5. Les skills sont allowlistés, versionnés, activés par tour ; workflow graphique fail-closed.
6. Les tools retournent un statut structuré commun (`ToolResult`).
7. Le code produit par le modèle s'exécute sans credentials, sans réseau, avec quotas.
8. Le coût fixe reste < 40 % de la fenêtre configurée.
9. Une suite de trajectoires multi-essais bloque toute régression de routage ou de sécurité.

---

## Suivi d'avancement

| Étape | Statut | Baseline | Après | Gate |
|---|---|---|---|---|
| 0 — Instrument de mesure | ⬜ à faire | — | — | ⬜ |
| 1 — Tests rouges | ⬜ à faire | — | — | ⬜ |
| 2 — Décision de source | ⬜ à faire | — | — | ⬜ |
| 3 — TurnContext + carte d'état | ⬜ à faire | — | — | ⬜ |
| 4 — Filtrage dynamique | ⬜ à faire | — | — | ⬜ |
| 5 — Confirmations | ⬜ à faire | — | — | ⬜ |
| 6 — Skills versionnés | ⬜ à faire | — | — | ⬜ |
| 7 — Isolation code | ⬜ à faire | — | — | ⬜ |
| 8 — Réduction prompt | ⬜ à faire | — | — | ⬜ |
