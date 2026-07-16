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

**État : terminé le 15 juillet 2026.** `SourceDecision` et `SourceAffinity` couvrent les sept sources, filtrent le modèle et gardent l'exécution avec la même politique. Une source externe doit être nommée à sa première utilisation, puis reste active jusqu'à une bascule explicite ou au chargement réussi d'un fichier. Un identifiant nu ne sélectionne jamais sa source.

**Goal :** une **seule** décision de source déterministe, cohérente entre code, prompt et tests. Premier slice qui touche directement la confusion fichier/EcoTaxa.

**Changement :**
- `SourcePolicy` structurée (fichier / EcoTaxa / EcoPart / Amundsen / Bio-ORACLE / OGSL / SQL), adossée au registre de l'étape 2.
- Trancher la règle métier : un `project_id` nu autorise-t-il EcoTaxa, oui ou non ? Aligner `source_scope.py`, le prompt et les tests sur la décision retenue.
- Le bloc de routage du prompt est **généré** depuis la politique (plus de regex + prose indépendantes).

**Test gate :**
- [x] Le test rouge « projet 17498 » de l'étape 1 devient vert.
- [x] Décision de source **identique** dans le code, le prompt généré et les tests, sur un jeu paramétré de formulations ambiguës.
- [x] Replay offline : `SC-LAB` / `SC-ECOTAXA` restent à 100 %; un smoke agent réel confirme l'héritage EcoTaxa puis la bascule fichier. Le benchmark live N ≥ 5 n'a pas été relancé.

---

### Étape 4 — Correction des contradictions de routage

**Goal :** éliminer les instructions incompatibles que l'agent reçoit aujourd'hui (audit P0 §4.2, P1.8), qui le font hésiter.

**État : contrat 4A écrit, mais enforcement fichier incomplet; 4B et sa garde exécutable 4B.1 terminées le 16 juillet 2026; 4C fermée le 16 juillet 2026.** La règle numérique canonique est injectée une seule fois : valeur fournie par un tool spécialisé → reprise directe; nouvelle valeur dérivée d'une table → pandas; valeur absente → inconnue, jamais inventée. Le smoke EcoTaxa spécialisé valide la première branche, mais le smoke combiné tableau→carte a montré que l'agent peut encore calculer une agrégation simple depuis les lignes de `load_file` sans appeler pandas. Cette dette devient 4A.1. Le routage graphique reste sémantique, mais le harness classifie l'artefact demandé au premier appel graphique, mémorise une décision typée par tour et bloque fail-closed les sorties non visuelles ou ambiguës. La séquence planner → writer → rendu est vérifiée sur les ToolResults réussis du tour courant. La contradiction OGSL de `environmental_join.md` (4C) est levée : une seule règle déterministe choisit l'outil par la clé de jointure de la table chargée — `query_ogsl` pour station/temps/profondeur, `enrich_with_ogsl` pour latitude/longitude. Seule la dette 4A.1 reste ouverte dans cette étape.

**Changement :**
- Remplacer « toute valeur numérique exige pandas » par « toute valeur **dérivée** ou non fournie par un tool spécialisé exige une exécution contrôlée » — un `count_ecotaxa_taxa` se consomme directement.
- Limiter le workflow `graph_planner` + `graph_writer` aux demandes **visuelles** (pas une table ou un calcul sans figure).
- Clarifier OGSL : une seule règle `query_ogsl` vs `enrich_with_ogsl` (contradiction interne de `environmental_join.md`).
- Une seule règle « extraction puis skill » ou « skill puis extraction » par source.

**Test gate :**
- [x] 4A — Le test rouge « pandas vs tools spécialisés » devient vert; smoke EcoTaxa spécialisé sans pandas validé.
- [ ] 4A.1 — Une nouvelle agrégation dérivée des lignes d'un fichier doit obligatoirement passer par `run_pandas` ou un tool spécialisé; le smoke réel actuel termine `exit 1` sur cette assertion.
- [x] 4B — Dans ce même smoke réel, « Donne un tableau… » voit sa tentative graphique bloquée; la demande de carte charge planner/writer puis produit la figure.
- [x] 4C — Le test rouge OGSL devient vert; règle OGSL unique validée sur l'agent réel (station/temps → `query_ogsl`, lat/lon → `enrich_with_ogsl`, 2/2).
- [x] 4B — Une demande numérique simple ne charge plus les skills graphiques; les appels réels capturés contiennent uniquement pandas.
- [x] 4A — Pas de régression offline sur les 3 scénarios : niveaux 1 et 2 à 100 %.
- [x] 4B — Pas de régression offline sur les 3 scénarios : niveaux 1 et 2 à 100 %; suite complète verte.
- [x] 4B.1 — Classification structurée à la demande, une seule fois par tour même si les appels sont parallèles; tentative adversariale tabulaire bloquée et carte rendue par l'agent réel.

**Verdict du smoke combiné :** preuves 4B.1 vertes, campagne globale non verte. Le processus a terminé sur `AssertionError` parce qu'aucun `run_pandas` n'a été observé au tour tableau. Ne pas utiliser cette campagne comme preuve de clôture 4A tant que 4A.1 n'est pas corrigée en TDD puis retestée sur l'agent.

---

### Étape 5 — `TurnContext` + carte d'état de session

**État : terminé le 16 juillet 2026** (une robustesse de rechargement multi-fichiers reste en suivi ouvert). Un `TurnContext` typé (`tools/turn_context.py`) est reconstruit en début de tour et regroupe l'état persistant lu depuis le store : dataset chargé/actif, sous-ensembles de zone vivants (variable+zone+lignes), et périmètre de source autorisé. La capsule d'état (`build_dataset_state_capsule`) est sa **projection** destinée au modèle :
- elle énumère les sous-ensembles de zone (l'agent lit quelle variable `df_in_*` correspond à quelle zone au lieu de la ré-inférer — cause racine cartes-samples-labrador) ;
- elle liste **tous les fichiers chargés** (`LOADED FILES` : variable, chemin, lignes) dès qu'il y en a plusieurs, pour que l'agent cible le bon `df_file_*` par son nom sans deviner ni recharger ;
- elle affiche `ACTIVE SOURCE SCOPE` (sources autorisées du tour), rendant la décision/`source_lock` de source **lisible comme état** et non plus seulement appliquée en silence.

Le middleware construit le `TurnContext` une fois par tour et enregistre ses champs dans l'audit de contexte. Le portage stateful du `source_lock` était déjà largement couvert par l'affinité de source (qui retire une source exclue de l'état actif) ; il est désormais aussi **visible** dans la carte d'état.

**Workflow multi-fichiers (validé sur l'agent réel le 16 juillet 2026).** Chaque `load_file` crée une variable `df_file_<stem>` distincte ; l'agent cible le bon fichier par son nom, et une **jointure crée un nouveau df persistant** : un `merge`/`join`/`concat` dans `run_pandas` est stocké comme dataset `df_join_*` (`persisted=true`, réutilisable au tour suivant), tandis qu'une agrégation simple reste éphémère (`_is_join_code` dans `tools/data_tools.py`). Smoke réel : deux fichiers joints → `df_join_*` → réutilisé au tour suivant (« 3 lignes »).

**Suivi ouvert — rechargement multi-fichiers :** malgré l'instruction « ne recharge pas » de la capsule, l'agent tend encore à rappeler `load_file` à chaque tour. Bénin en local, mais **risque en prod** : recharger un chemin d'upload expiré (`/tmp/webui_uploads/…`) échouerait alors que le df est déjà en session. Correctif proposé, non fait : rendre `load_file` idempotent (retourner la variable existante quand le même chemin est déjà chargé, et le df existant si le chemin n'est plus lisible).

**Goal :** l'agent **lit** son état au lieu de le ré-inférer depuis l'historique. Cœur du problème « l'agent se perd entre fichier/EcoTaxa/dérivé ».

**Changement :**
- `TurnContext` typé reconstruit en début de tour : `loaded_dataset`, dérivés vivants (avec leur zone), `explicit_source`, `source_lock`, budget. Persistant vs éphémère séparés (checkpoint/store vs expire au tour).
- La capsule passe de « df actif » à **carte d'état complète** : source de travail, dérivés+zone, périmètre/verrou.
- `source_lock` réellement porté en état (aujourd'hui seulement en prose — faiblesse P1 de l'audit).

**Test gate :**
- [x] `SC-LAB` : la carte des dérivés+zone et le périmètre de source sont injectés; smoke réel multi-zone → la carte demandée part du bon sous-ensemble (Baffin) et `authorized_sources=['file']` observé dans l'audit. Le suivi N ≥ 5 formel reste une mesure de campagne, non un blocage de correction.
- [x] `SC-ENRICH` : **aucune régression** — capsule/`TurnContext` en lecture seule; suites `turn_context`/`session_context`/`run_pandas`/`geo`/`agent_factory`/red-team vertes (127 tests) et les chemins d'enrichissement partent toujours de la bonne table.
- [x] La carte d'état reste sous son budget : capsule ~1 126 caractères (~300 tokens) mesurée sur l'agent réel, plafond 2 000 caractères, roster borné à 12 entrées.
- [x] Multi-fichiers : `LOADED FILES` nomme chaque fichier chargé; smoke réel → l'agent joint les bons `df_file_*` par nom et la jointure crée un `df_join_*` persistant réutilisé au tour suivant. Tests `test_run_pandas_join_persistence.py` + capsule verts.

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

**État : allowlist locale fail-closed terminée le 16 juillet 2026 ; versionnement/frontmatter/découpe encore à faire.** `load_skill` valide l'allowlist locale **avant** tout accès Hub : le Hub ne peut plus introduire un nom de skill absent localement, il sert seulement une version d'un skill déjà autorisé (fallback Hub→local visible en provenance). Le contrat rouge de l'étape 1 est devenu vert et le happy path graphique reste validé sur l'agent réel.

**Goal :** activation de skills bornée, tracée et ordonnée par tour.

**Changement :**
- Allowlist locale validée **avant** tout accès Hub ; enveloppe `name`/`source`/`environment`/`version`/`hash`/`content` ; fallback Hub→local visible en observabilité.
- Frontmatter commun imposé : `name`, `version`, `triggers`, `forbidden_when`, `requires`, `next_tool`, `max_tokens` — préconditions dans les métadonnées exécutables, pas en prose.
- Découper les skills > 3 000 tokens (`ecotaxa_navigation` ~8.5k, `graph_writer` ~10k) ou justifier.
- La partie graphique de l'automate est déjà imposée en 4B.1 depuis les ToolResults du tour courant. L'étape 8 conserve la normalisation générale des événements de skills et leur versionnement.

**Test gate :**
- [x] Skill hors allowlist locale jamais chargé depuis le Hub (test rouge de l'étape 1 vert) ; happy path graphique (`graph_planner`/`graph_writer` → `run_graph`) validé sur l'agent réel.
- [x] `run_graph` impossible hors séquence du tour courant (résolu en 4B.1).
- [ ] Chaque skill a le frontmatter commun ; aucun skill > 3 000 tokens sans exemption documentée.

---

### Étape 9 — Isolation du code libre *(P0 sécurité, ordonnancement technique après les fondations)*

**Goal :** `run_pandas`/`run_graph` exécutés sans surface d'action excessive (OWASP moindre privilège).

**État : premier tranchant « moindre privilège namespace » terminé le 16 juillet 2026 ; l'isolation processus complète reste à faire.** `run_pandas`/`run_graph` exécutent désormais le code du modèle dans un espace de noms restreint (`tools/code_sandbox.py`) : allowlist d'imports (libs scientifiques + quatre contrats d'analyse `core.*` sans credentials) et retrait de `open`/`eval`/`exec`/`compile`/`input`/`breakpoint`. `core.llm_config` et les clients de sources restent inatteignables — le code ne peut plus lire `os.environ`, ouvrir un socket, lancer un subprocess ni ouvrir un fichier via `import`/`open`. Restent ouverts pour compléter l'étape : l'egress niveau bibliothèque (`pd.read_csv(url)`), les échappatoires d'introspection, les quotas CPU/mémoire/temps et le FS lecture seule — tout cela exige le worker processus jetable.

**Priorité :** cette faiblesse reste **P0 sécurité** dès l'audit. Son numéro indique seulement l'ordre de dépendances du chantier principal ; tout déploiement exposé doit la traiter ou désactiver ces tools avant d'attendre l'étape 9.

**Changement :** worker jetable, FS lecture seule sauf répertoire d'artefacts, **aucun secret**, réseau coupé par défaut, quotas CPU/mémoire/temps/sortie, imports explicitement autorisés, datasets par références contrôlées, validation des artefacts, destruction après appel.

**Test gate :**
- [x] Tests d'évasion secret/réseau/subprocess/`open` rouges deviennent verts (`tests/harness_redteam/test_code_isolation_contracts.py`).
- [~] Pas de credentials accessibles depuis le code exécuté (secrets bloqués via l'allowlist d'imports) ; **quotas et coupure réseau bibliothèque restants** (worker processus).
- [x] Pas de régression fonctionnelle sur les analyses/graphes : suites `run_pandas`/`run_graph` vertes et smoke agent réel (pandas groupby + carte cartopy) sous namespace restreint.

---

### Étape 10 — Réduction du prompt

**Goal :** une fois les politiques exécutables, alléger le prompt permanent (cible ≤ 3 500 tokens).

**Changement :** retirer les listes de tools lourds et les séquences déjà imposées en code ; garder identité, périmètre scientifique, règles de vérité, ton, contrat de réponse.

**Test gate :**
- [ ] Evals avant/après **chaque** suppression, pas de régression sur les 3 scénarios.
- [ ] Prompt permanent ≤ 3 500 tokens ; coût fixe total < 40 % de `MAX_CONTEXT_TOKENS`.

---

### Étape 11 — Nettoyage legacy & documentation

**État : terminé le 16 juillet 2026.** `agents/copepod_prompt.py` (sans consommateur) est archivé hors du package actif dans `docs/legacy/copepod_prompt_DEPRECATED.py` avec bannière de dépréciation. Les blocs `copepod_mode_*` n'existaient plus qu'en bytecode orphelin (`.pyc`), supprimés ; aucune source `.py` « mode » active ne subsiste. Le commentaire `serve.py` et les entrées `LANGSMITH_API_KEY` d'`AGENTS.md`/`CLAUDE.md`/`ARCHITECTURE.md` reflètent désormais un prompt lu localement et un pull Hub réservé aux skills. Les inventaires périmés (`~53 tools`, `create_react_agent`, `42 tests`, `~64 lignes`) sont corrigés en 59/62 tools, `create_agent`, ~104 modules de test et ~187 lignes de prompt dans `AGENTS.md`/`CLAUDE.md`/`SPEC.md`. `scripts/dev/push_prompt.py` porte une dépréciation explicite (aucun consommateur runtime).

**Goal :** supprimer les pièges qui font modifier au mauvais endroit (audit P2, §8).

**Changement :** archiver `agents/copepod_prompt.py` hors du package actif ; retirer/renommer `core/instruction_renderer/blocks/copepod_mode_*` (le vocabulaire de « mode » contredit la règle « pas de mode ») ; corriger `AGENTS.md`/`CLAUDE.md`/`CONTEXT.md`/`ARCHITECTURE.md`/`SPEC.md`/`README.md` + commentaire `serve.py` (chemin Hub inexistant) ; déprécier explicitement `scripts/dev/push_prompt.py` tant qu'aucun consommateur runtime, ou rétablir un chemin de lecture versionné et testé.

**Test gate :**
- [x] Grep « mode analyse/plan » et « pull Hub » ne renvoie plus de source active trompeuse (docs datés d'audit exclus, ce sont des instantanés).
- [x] Inventaires (59/62) cohérents partout ; test de parité doc de l'étape 2 vert ; `agent.py`/`serve.py` importent toujours et un tour agent réel passe après le nettoyage.

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
| 3 — Décision de source | ✅ terminé | offline : 12 tours, 100 % | offline : 13 tours, 100 %; smoke réel 3/3 | ✅ |
| 4 — Contradictions de routage | 🟡 en cours | — | 4A/4B/4B.1/4C fermées; smoke OGSL réel 2/2 | 🟡 4A.1 ouvert |
| 5 — TurnContext + carte d'état | ✅ terminé | capsule = df actif seul | TurnContext typé; dérivés+zone et périmètre de source dans la capsule; réel `authorized=file`, ~300 tokens | ✅ |
| 6 — Filtrage dynamique | ⬜ à faire | — | — | ⬜ |
| 7 — Confirmations | ⬜ à faire | — | — | ⬜ |
| 8 — Skills versionnés | 🟡 en cours | Hub sert un skill non listé | allowlist fail-closed avant Hub; contrat vert; happy path réel OK | 🟡 versionnement/frontmatter restants |
| 9 — Isolation code | 🟡 en cours | exec avec builtins complets (secrets/réseau/FS) | namespace restreint : imports allowlistés, secrets bloqués; escapes verts, smoke réel OK | 🟡 worker processus/quotas restants |
| 10 — Réduction prompt | ⬜ à faire | — | — | ⬜ |
| 11 — Nettoyage legacy | ✅ terminé | docs périmées (53 tools, react_agent, pull Hub) | prompt legacy archivé; inventaires 59/62; parité doc verte | ✅ |
