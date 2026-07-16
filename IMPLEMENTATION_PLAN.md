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

Chaque scénario est évalué dans deux pistes complémentaires :

- **Piste A — replay offline déterministe (CI)** : modèle scripté, adaptateurs de sources simulés, réseau et tracing coupés. Elle vérifie les invariants, la forme des trajectoires et les régressions exactes. Un seul passage suffit pour les assertions déterministes ; plusieurs passages peuvent confirmer l'absence de fuite d'état.
- **Piste B — benchmark live** : modèle réel et intégrations explicitement sélectionnées. Chaque scénario est rejoué **N ≥ 5 fois** pour mesurer la variance, la qualité de routage, les tokens, le coût et la latence. Cette piste est séparée de la CI et produit un rapport daté.

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

**État : terminé le 15 juillet 2026.** Résultats et limites : [`BASELINE_HARNESS_2026-07-15.md`](BASELINE_HARNESS_2026-07-15.md).

**Goal :** disposer d'un harnais de rejeu reproductible et d'une **baseline chiffrée** du comportement actuel. Prérequis absolu : « mesurer à chaque étape » est impossible sans lui.

**Livrables :**
- `evals/replay_harness.py` : moteur commun qui rejoue un scénario (thread + store isolés, `SESSION_STORE_DIR` jetable, `user_id` unique) et capture par tour → tools exposés au modèle, tools appelés + args, **source/df réellement utilisée**, refus, réponse finale, tokens/coût.
- Scénarios `SC-LAB`, `SC-ENRICH`, `SC-ECOTAXA` figés en fixtures.
- Piste A : runner offline déterministe et rapport de référence versionné, sans dépendance à une API, une source externe ou LangSmith.
- Piste B : `evals/baseline_YYYY-MM-DD.json`, produit par une commande live explicite sur N ≥ 5 essais/scénario ; le rapport distingue modèle, versions, sources simulées/réelles et conditions d'exécution.
- Les **trois niveaux d'évaluation** cadrés dès le départ (best-practices §6), même si seul le niveau 1-2 est instrumenté maintenant :
  - **Niveau 1 — invariants déterministes** : tool non visible non exécutable, source verrouillée non contournable, identifiant ancien rejeté, résultat error/empty jamais présenté comme success.
  - **Niveau 2 — trajectoire** : tools visibles au départ, appels + args, décisions de politique, transitions, nombre de tours/appels, tokens/coût, état final.
  - **Niveau 3 — qualité scientifique & UX** : exactitude des tableaux/métriques, traçabilité des sources, absence d'interprétation non demandée, ton clinique, concision (grader LLM + calibration humaine périodique).

**Test gate :**
- [x] Le replay offline d'un scénario régénère un rapport de trajectoire structuré identique en forme et en contenu normalisé, run-à-run.
- [x] Baseline offline produite : pour `SC-LAB`, taux « part du bon fichier » chiffré ; tokens fixes mesurés ; tools moyens/tour mesurés.
- [x] La commande du benchmark live impose N ≥ 5, n'est jamais lancée implicitement par la CI et annote clairement les dépendances externes utilisées.
- [x] Isolation vérifiée : aucun écrit dans le store de prod, aucune trace LangSmith de test.
- [x] Les graders de niveau 1 et 2 tournent sur les 3 scénarios ; le niveau 3 est cadré (rubric) même si calibré plus tard.

---

### Étape 1 — Tests rouges qui exposent les failles *(aucune correction)*

**État : contrats capturés le 15 juillet 2026.** Les 7 échecs diagnostiques et leur propriétaire sont documentés dans [`HARNESS_REDTEAM_CONTRACTS_2026-07-15.md`](HARNESS_REDTEAM_CONTRACTS_2026-07-15.md). La vérification en mode `--runxfail` confirme les raisons d'échec ; l'exécution CI normale n'a pas été répétée à la demande de l'utilisateur.

**Goal :** rendre la dette connue **exécutable et rouge**, versionnée, avant de toucher au runtime (Phase 0 du best-practices).

**Changement :** dossier `tests/harness_redteam/` avec les tests de cohérence transversale qui échouent aujourd'hui :
- cohérence prompt ↔ `source_scope.py` sur « projet 17498 » (contradiction P0 de l'audit) ;
- contradiction « toute valeur numérique = pandas » vs tools spécialisés qui renvoient déjà des nombres (`count_ecotaxa_taxa`, `summarize_ecotaxa_projects`…) ;
- opération lourde (`query_ecotaxa`, `query_ecopart`, `query_amundsen_ctd`, `query_bio_oracle`, `export_deliverable`) exécutable sans confirmation liée aux arguments ;
- `run_graph` possible hors séquence `planner → writer → run_graph` du tour courant ;
- skill hors allowlist locale chargeable depuis le Hub ;
- budget fixe prompt + schémas sous seuil ;
- parité inventaire : catalogue runtime (59/62) vs `TOOLS.md`/`ARCHITECTURE.md`/`AGENTS.md`.

**Test gate :**
- [x] Chaque test échoue **pour la bonne raison** (message qui pointe la faille réelle).
- [x] Marqués `xfail(strict=True)` avec référence à l'étape qui les rendra verts. La validation CI normale reste à constater lors du prochain passage contrôlé.

---

### Étape 2A — Fondation : registre déclaratif unique

**État : terminé le 15 juillet 2026.** Les 62 tools possèdent une politique immuable validée et un schéma Pydantic strict (`strict=True`, `extra="forbid"`). Les défauts EcoPart `project_id=105` ont été supprimés. `ToolCatalog.policy()` reste la source de vérité et l'inventaire de `TOOLS.md` est généré. Les confirmations sont déclarées mais ne deviennent exécutables qu'à l'étape 7.

**Goal :** poser la **source de vérité unique** des tools sur laquelle reposent les politiques suivantes, sans cumuler ce refactor avec une migration de tous les retours.

**Changement :**
- `ToolPolicy` par tool (**extension de `tool_catalog.py`**, pas un registre concurrent) : `family`, `source`, `risk`, `read_only`, `mutates_session`, `remote_io`, `expensive`, `reversible`, `requires_confirmation`, `required_skill`, `allowed_workflows`, `max_calls_per_turn`, `result_schema`. Schémas d'entrée **Pydantic stricts** (pas d'argument ambigu, pas de défaut dangereux — ex. plus de `project_id=105` implicite).
- Le registre **génère** : métadonnées runtime, table de présentation UI, sections de `TOOLS.md`, matrice de confirmation, tests de parité, filtres de tools. Le prompt ne recopie plus cette matrice.

**Test gate :**
- [x] Test de parité registre ↔ catalogue runtime vert ; `TOOLS.md` généré, 0 divergence (le test rouge inventaire de l'étape 1 devient vert).
- [x] Aucun tool n'a de défaut dangereux (schémas stricts validés au démarrage).
- [x] Baseline offline stable (refactor sans régression de trajectoire).

### Étape 2B — Migration progressive vers `ToolResult`

**État : terminé le 15 juillet 2026.** Les 62 tools utilisent le contrat LangChain `content_and_artifact`; leur artefact porte un `ToolResult` validé et le replay lit exclusivement ce statut structuré. Aucun adaptateur de résultat legacy ne subsiste.

**Goal :** remplacer les retours textuels ambigus par une enveloppe structurée, famille par famille, sans migration « big bang ».

**Changement :** `ToolResult` commun (`status` ∈ success/empty/blocked/error/cancelled, `summary`, `data_ref`, `artifact_refs`, `provenance`, `persisted`, `retryable`, `method`, `metrics`). Migration séquentielle par famille de tools, avec adaptateur temporaire explicite pour les tools non encore migrés. Ordre recommandé : fichier/dataframe → sources distantes → graphes/livrables → SQL/RAG/skills.

**Test gate :**
- [x] Chaque famille migrée possède ses tests de contrat et conserve sa trajectoire de référence avant de passer à la suivante.
- [x] Chaque tool retourne un `ToolResult` et l'instrument de l'étape 0 lit `status` sans parser « Erreur »/« Aucun résultat ».
- [x] Aucun adaptateur temporaire : aucun retour legacy ne traverse le runtime.
- [x] Baseline offline stable après la migration complète.

---

### Étape 3 — Décision de source exécutable + trancher « projet 17498 »

**Goal :** une **seule** décision de source déterministe, cohérente entre code, prompt et tests. Premier slice qui touche directement la confusion fichier/EcoTaxa.

**Changement :**
- `SourcePolicy` structurée (fichier / EcoTaxa / EcoPart / Amundsen / Bio-ORACLE / OGSL / SQL), adossée au registre de l'étape 2.
- Trancher la règle métier : un `project_id` nu autorise-t-il EcoTaxa, oui ou non ? Aligner `source_scope.py`, le prompt et les tests sur la décision retenue.
- Le bloc de routage du prompt est **généré** depuis la politique (plus de regex + prose indépendantes).

**Test gate :**
- [ ] Le test rouge « projet 17498 » de l'étape 1 devient vert.
- [ ] Décision de source **identique** dans le code, le prompt généré et les tests, sur un jeu paramétré de formulations ambiguës.
- [ ] `SC-LAB` / `SC-ECOTAXA` : routage de source **stable ou amélioré** vs baseline (pas de régression), N ≥ 5.

---

### Étape 4 — Correction des contradictions de routage

**Goal :** éliminer les instructions incompatibles que l'agent reçoit aujourd'hui (audit P0 §4.2, P1.8), qui le font hésiter.

**Changement :**
- Remplacer « toute valeur numérique exige pandas » par « toute valeur **dérivée** ou non fournie par un tool spécialisé exige une exécution contrôlée » — un `count_ecotaxa_taxa` se consomme directement.
- Limiter le workflow `graph_planner` + `graph_writer` aux demandes **visuelles** (pas une table ou un calcul sans figure).
- Clarifier OGSL : une seule règle `query_ogsl` vs `enrich_with_ogsl` (contradiction interne de `environmental_join.md`).
- Une seule règle « extraction puis skill » ou « skill puis extraction » par source.

**Test gate :**
- [ ] Les tests rouges « pandas vs tools spécialisés » et OGSL de l'étape 1 deviennent verts.
- [ ] `SC-LAB` : une demande numérique simple ne déclenche plus le chargement des ~12k tokens de skills graphiques (mesuré).
- [ ] Pas de régression de routage sur les 3 scénarios.

---

### Étape 5 — `TurnContext` + carte d'état de session

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

### Étape 6 — Filtrage dynamique des tools *(≤ 15/tour)*

**Goal :** réduire le budget fixe et la compétition entre tools proches. Plus gros levier — et le plus risqué (change ce que le modèle voit).

**Changement :** `PolicyEngine` produit une allowlist par tour à partir de la `SourcePolicy` et du `TurnContext` ; le middleware `wrap_model_call` remplace `request.tools` par le sous-ensemble pertinent.

**Test gate :**
- [ ] Tools exposés/tour ≤ 15 (alerte à 12) sur tous les scénarios.
- [ ] Tokens fixes (prompt + schémas) < 40 % de `MAX_CONTEXT_TOKENS`.
- [ ] **Aucune régression** de trajectoire sur `SC-LAB` / `SC-ENRICH` / `SC-ECOTAXA`, N ≥ 5 (un tool nécessaire jamais masqué à tort).

---

### Étape 7 — Confirmations exécutables *(axe sécurité)*

**Goal :** rendre CT-AG-06 réelle : aucune opération lourde sans approbation liée à l'action.

**Changement :** `ToolGuardMiddleware` comme **point de validation central fail-closed** (tool connu ? visible ? source compatible ? args valides ? identifiants fondés ? budget ? étape de workflow ? confirmation valide ?). `ApprovalGrant` lié à `tool_name` + `canonical_args_hash` + expiration, via `HumanInTheLoop`/interrupt LangGraph. Le champ `requires_confirmation` du registre (étape 2A) pilote le déclenchement. Le protocole d'interruption/reprise est propagé jusqu'à FastAPI SSE et Open WebUI : événement d'approbation structuré, reprise idempotente du même thread, reconnexion sans double exécution et statut final observable.

**Test gate :**
- [ ] Aucun tool lourd exécutable sans grant exact (tests rouges confirmation de l'étape 1 verts).
- [ ] approve / edit / reject / reprise / expiration testés ; modifier un argument invalide le grant.
- [ ] Pause/reprise/reconnexion SSE testées de bout en bout ; une reprise répétée n'exécute jamais l'opération deux fois.
- [ ] Une métadonnée absente provoque un refus explicite (fail-closed).

---

### Étape 8 — Skills fail-closed, versionnés, normalisés *(axe sécurité)*

**Goal :** activation de skills bornée, tracée et ordonnée par tour.

**Changement :**
- Allowlist locale validée **avant** tout accès Hub ; enveloppe `name`/`source`/`environment`/`version`/`hash`/`content` ; fallback Hub→local visible en observabilité.
- Frontmatter commun imposé : `name`, `version`, `triggers`, `forbidden_when`, `requires`, `next_tool`, `max_tokens` — préconditions dans les métadonnées exécutables, pas en prose.
- Découper les skills > 3 000 tokens (`ecotaxa_navigation` ~8.5k, `graph_writer` ~10k) ou justifier.
- `loaded_skills: list[str]` remplacé par événements horodatés/`turn_id` ; automate `planner → writer → run_graph` imposé en code, fail-closed.

**Test gate :**
- [ ] Skill hors allowlist locale jamais chargé depuis le Hub (test rouge de l'étape 1 vert).
- [ ] `run_graph` impossible hors séquence du tour courant.
- [ ] Chaque skill a le frontmatter commun ; aucun skill > 3 000 tokens sans exemption documentée.

---

### Étape 9 — Isolation du code libre *(P0 sécurité, ordonnancement technique après les fondations)*

**Goal :** `run_pandas`/`run_graph` exécutés sans surface d'action excessive (OWASP moindre privilège).

**Priorité :** cette faiblesse reste **P0 sécurité** dès l'audit. Son numéro indique seulement l'ordre de dépendances du chantier principal ; tout déploiement exposé doit la traiter ou désactiver ces tools avant d'attendre l'étape 9.

**Changement :** worker jetable, FS lecture seule sauf répertoire d'artefacts, **aucun secret**, réseau coupé par défaut, quotas CPU/mémoire/temps/sortie, imports explicitement autorisés, datasets par références contrôlées, validation des artefacts, destruction après appel.

**Test gate :**
- [ ] Tests d'évasion (accès secret, réseau, FS hors artefacts) rouges deviennent verts.
- [ ] Pas de credentials ni réseau accessibles depuis le code exécuté ; quotas appliqués.
- [ ] Pas de régression fonctionnelle sur les graphes/analyses des 3 scénarios.

---

### Étape 10 — Réduction du prompt

**Goal :** une fois les politiques exécutables, alléger le prompt permanent (cible ≤ 3 500 tokens).

**Changement :** retirer les listes de tools lourds et les séquences déjà imposées en code ; garder identité, périmètre scientifique, règles de vérité, ton, contrat de réponse.

**Test gate :**
- [ ] Evals avant/après **chaque** suppression, pas de régression sur les 3 scénarios.
- [ ] Prompt permanent ≤ 3 500 tokens ; coût fixe total < 40 % de `MAX_CONTEXT_TOKENS`.

---

### Étape 11 — Nettoyage legacy & documentation

**Goal :** supprimer les pièges qui font modifier au mauvais endroit (audit P2, §8).

**Changement :** archiver `agents/copepod_prompt.py` hors du package actif ; retirer/renommer `core/instruction_renderer/blocks/copepod_mode_*` (le vocabulaire de « mode » contredit la règle « pas de mode ») ; corriger `AGENTS.md`/`CLAUDE.md`/`CONTEXT.md`/`ARCHITECTURE.md`/`SPEC.md`/`README.md` + commentaire `serve.py` (chemin Hub inexistant) ; déprécier explicitement `scripts/dev/push_prompt.py` tant qu'aucun consommateur runtime, ou rétablir un chemin de lecture versionné et testé.

**Test gate :**
- [ ] Grep « mode analyse/plan » et « pull Hub » ne renvoie plus de source active trompeuse.
- [ ] Inventaires (59/62) cohérents partout ; test de parité doc de l'étape 2 vert.

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
| 0 — Instrument de mesure | ✅ terminé | offline + live datées | harness reproductible | ✅ |
| 1 — Tests rouges | ✅ terminé | 7 dettes reproduites | 6 contrats futurs `xfail`, inventaire résolu | ✅ |
| 2 — Registre + `ToolResult` | ✅ terminé | offline : 33 654 tokens fixes | offline : 24 392; trajectoires 100 % | ✅ |
| 3 — Décision de source | ⬜ à faire | — | — | ⬜ |
| 4 — Contradictions de routage | ⬜ à faire | — | — | ⬜ |
| 5 — TurnContext + carte d'état | ⬜ à faire | — | — | ⬜ |
| 6 — Filtrage dynamique | ⬜ à faire | — | — | ⬜ |
| 7 — Confirmations | ⬜ à faire | — | — | ⬜ |
| 8 — Skills versionnés | ⬜ à faire | — | — | ⬜ |
| 9 — Isolation code | ⬜ à faire | — | — | ⬜ |
| 10 — Réduction prompt | ⬜ à faire | — | — | ⬜ |
| 11 — Nettoyage legacy | ⬜ à faire | — | — | ⬜ |
