# Copepod Eval Suite

Suite d'évaluation du workflow Plan Mode copépodes.
Couvre les guards backend (mock), la compréhension du dataset (DU-only), la construction du Graph Context (GC-only), et le workflow complet Plan → Analyse (live).

---

## Structure

```
scripts/evals/
  run_copepod_plan_mode_eval.py      ← CLI principal + shim de rétro-compatibilité
  run_copepod_direct_analysis_eval.py
  run_copepod_offtopic_eval.py
  run_copepod_rejection_eval.py

  copepod/                           ← package de la suite
    harness.py         ← EvalHarness : session, TestClient, Langfuse, résultats
    fixtures.py        ← staging des fixtures TSV sans HTTP
    llm_driver.py      ← _run_llm_turn, tool specs, compact result
    system_messages.py ← prompts système injectés à l'éval
    eval_mock.py       ← run_mock_eval()
    eval_du.py         ← run_live_du_only_eval()
    eval_gc.py         ← run_live_gc_only_eval() + GcScenario manifest
    eval_live.py       ← run_live_eval()
    eval_smoke.py      ← run_langfuse_trace_smoke()
```

`run_copepod_plan_mode_eval.py` est un shim : il re-exporte tous les symboles du package `copepod/` pour que les tests pytest et les scripts Docker existants continuent de fonctionner sans modification.

---

## Commandes de lancement

Toutes les commandes s'exécutent depuis le container Docker :

```bash
# Guard depuis depuis Docker
docker exec -it idea_container bash

# À l'intérieur du container :
cd /app

# 1. Mock — aucun LLM, guards backend purs
python scripts/evals/run_copepod_plan_mode_eval.py --mock

# 2. DU-only — LLM réel, Phase 1 seulement
python scripts/evals/run_copepod_plan_mode_eval.py --live-du-only --push-langfuse

# 3. GC-only — LLM réel, Phase 2 seulement (DU déjà actif)
python scripts/evals/run_copepod_plan_mode_eval.py --live-gc-only --push-langfuse

# GC-only avec scénarios spécifiques
python scripts/evals/run_copepod_plan_mode_eval.py --live-gc-only --gc-scenarios rich,poor

# 4. Live complet — LLM réel, DU → GC → PLAN_READY
python scripts/evals/run_copepod_plan_mode_eval.py --live --push-langfuse

# 5. Trace smoke — vérifie que Langfuse reçoit bien une trace
python scripts/evals/run_copepod_plan_mode_eval.py --trace-smoke --push-langfuse

# Sortie JSON
python scripts/evals/run_copepod_plan_mode_eval.py --mock --json
```

**Règle avant tout live :** toujours lancer `--mock` → `--live-du-only` → `--live-gc-only` → `--live`.

---

## Modes en détail

### `--mock` — Guards backend, sans LLM

Fichier : `copepod/eval_mock.py`

Teste 12 invariants déterministes via `TestClient` + `InMemorySessionStore`, sans appel OpenAI.
Les fixtures TSV sont copiées directement dans le répertoire d'upload sans passer par le rate limiter HTTP.

Checks couverts :

| Nom | Ce qui est vérifié |
|---|---|
| `upload_ecotaxa_creates_data_understanding` | Upload EcoTaxa → DU draft créé, `source_type_guess == likely_ecotaxa` |
| `data_understanding_coverage_is_sufficient` | Couverture du DU marquée `sufficient` |
| `analyse_blocked_before_active_artifacts` | `/session/mode` renvoie 409 sans artifacts actifs |
| `graph_context_without_data_understanding_version_is_blocked` | GC sans `data_understanding_version_id` → rejeté |
| `phase_gate_blocks_graph_context_before_data_understanding_confirmation` | GC avant confirmation DU → bloqué |
| `plan_ready_button_not_emitted_before_minimum_turns` | `[PLAN_READY]` avant le minimum de tours → pas de bouton |
| `backend_phase_gate_blocks_premature_plan_ready_button` | Backend supprime le bouton même si le LLM émet `[PLAN_READY]` trop tôt |
| `data_understanding_confirmation_activates_artifact` | Confirmation utilisateur → DU passe en `active` |
| `graph_context_draft_links_to_active_du` | Draft GC référence le bon `version_id` DU |
| `plan_ready_after_graph_context_activation` | Activation GC → bouton SSE → `/session/mode` HTTP 200 |
| `upload_in_analyse_creates_draft_without_replan` | Re-upload en Analyse → nouveau DU draft, actifs inchangés |
| `analyse_blocked_when_graph_context_references_stale_data_understanding` | GC lié à DU périmé → 409 |
| `artifact_debug_routes_are_copepod_only` | Routes debug artifacts → 404 pour `agent_type=generic` |

---

### `--live-du-only` — Phase 1 seulement

Fichier : `copepod/eval_du.py`

LLM réel, arrêt après activation du Data Understanding. Ne teste pas Graph Context ni `[PLAN_READY]`.
Idéal pour valider la compréhension du dataset sans dépenser des tokens sur le workflow complet.

Checks couverts (9) :

| Nom | Ce qui est vérifié |
|---|---|
| `live_du_only_created_data_understanding_draft` | DU draft créé en Phase 1 |
| `live_du_only_waited_for_data_understanding_confirmation` | Aucun artifact activé avant confirmation |
| `live_du_only_phase1_efficient` | Phase 1 ≤ 10 rounds LLM |
| `live_du_only_payload_has_column_catalogue` | `column_catalogue` non vide dans le payload |
| `live_du_only_payload_has_sufficient_coverage` | Couverture `sufficient` |
| `live_du_only_describe_column_covered_all_unmatched` | `describe_column` ≥ nb de colonnes `unmatched` |
| `live_du_only_activated_data_understanding` | DU activé après confirmation |
| `live_du_only_no_graph_context_created` | Aucun GC créé dans ce mode |
| `live_du_only_no_internal_terms_in_llm_text` | Pas de termes internes (graph context, version_id…) dans le texte LLM |

---

### `--live-gc-only` — Phase 2 seulement

Fichier : `copepod/eval_gc.py`

LLM réel, DU actif injecté par le harness avant le premier tour. Valide uniquement la construction du Graph Context et le comportement conversationnel face à un contexte plus ou moins complet.

**Les scénarios sont déclarés dans le manifest `_GC_SCENARIOS`** (liste de `GcScenario`) — ajouter un scénario = une entrée dans la liste, sans toucher à la logique d'assertion.

#### Scénarios actifs

| Slug | Label | Attendu |
|---|---|---|
| `rich` | Contexte riche | GC draft créé, activé après confirmation, `[PLAN_READY]` émis |
| `poor` | Contexte pauvre | Question ciblée unique, pas de GC créé prématurément |
| `offtopic` | Hors sujet | Recentrage sans se re-présenter, question ciblée |
| `analysis-jump` | Saut vers analyse | Refus explicite Plan Mode, aucune Phase 1 |

Le scénario `join` a été retiré du pack pour éviter un signal trop bruité.

#### Checks produits (20 au total pour le pack actif)

Checks universels (tous les scénarios) :
- `gc_only_<slug>_never_reopened_phase1`
- `gc_only_<slug>_created_graph_context_draft`
- `gc_only_<slug>_did_not_emit_plan_ready` (si `expect_gc_draft=False`)
- `gc_only_<slug>_did_not_activate_graph_context` (si `expect_gc_draft=False`)

Checks conditionnels :
- `gc_only_<slug>_activated_graph_context` (si `expect_gc_activated`)
- `gc_only_plan_ready_after_gc_activation` (si `expect_gc_activated`)
- `gc_only_<slug>_asked_single_targeted_question_when_missing_fields` (si `expect_targeted_question`)
- `gc_only_refused_direct_analysis_request_before_gc` (si `expect_analysis_refusal`)

Cross-scénarios :
- `gc_only_no_internal_terms_in_llm_text`

#### Ajouter un scénario GC

```python
# Dans copepod/eval_gc.py, ajouter une entrée à _GC_SCENARIOS :
GcScenario(
    slug="units-ambiguous",
    label="Unités ambiguës",
    seed_paths=[ECOTAXA, ECOPART],
    user_messages=["Je veux un graphe de profondeur, mais les unités sont à définir."],
    expect_targeted_question=True,
    question_fallback_keywords=["unité", "mètre"],
),
```

---

### `--live` — Workflow complet

Fichier : `copepod/eval_live.py`

LLM réel, DU → GC → PLAN_READY → Analyse. 14 checks au total sur 3 phases.
À ne lancer qu'après que `--mock`, `--live-du-only` et `--live-gc-only` passent.

---

### `--trace-smoke`

Fichier : `copepod/eval_smoke.py`

Envoie une requête minimale et vérifie qu'une trace Langfuse est bien créée avec `level=DEFAULT`.
Requiert Langfuse actif. Ne passe pas par EvalHarness — crée sa propre trace directement.

---

## Comment ajouter des tests

### Règle de base

- Si le comportement doit exister en prod → corriger le prompt ou le backend d'abord.
- Si le comportement sert uniquement à rendre le test observable → le fix va dans le harness ou la scorecard, jamais dans le prompt.
- Si un scénario est bruité ou coûteux → le retirer du pack live plutôt que de forcer le modèle avec un prompt artificiel.

### Ajouter un check mock (guard backend)

Dans `copepod/eval_mock.py`, à l'intérieur du `with EvalHarness(...) as ctx:`, appeler `ctx.result` :

```python
# 1. Préparer l'état
my_artifact = ctx.tools["create_data_understanding_draft"](ctx.session_key, {...})

# 2. Décrire le check
ctx.result(
    "mon_nouveau_check",          # nom unique, snake_case
    my_artifact["status"] == "draft",  # condition booléenne
    f"Artifact créé avec status {my_artifact['status']!r}.",  # message lisible
    {"case_type": "edge"},        # "common" pour happy path, "edge" pour cas limites
)
```

Pas d'appel OpenAI. Le check apparaît dans le rapport et dans les scores Langfuse.

### Ajouter un check live DU

Dans `copepod/eval_du.py`, après un tour LLM :

```python
ctx.result(
    "live_du_only_mon_check",
    bool(du_payload.get("ma_clé")),
    "Description courte.",
    {"case_type": "edge", "model": ctx.model_name},
)
```

Convention de nommage : préfixer par `live_du_only_`.

### Ajouter un scénario GC

Dans `copepod/eval_gc.py`, ajouter une entrée à `_GC_SCENARIOS` :

```python
GcScenario(
    slug="units-ambiguous",            # identifiant court, kebab-case
    label="Unités ambiguës",           # label humain pour les logs
    seed_paths=[ECOTAXA, ECOPART],     # fixtures à injecter comme DU actif
    user_messages=[
        "Je veux un graphe de profondeur, mais les unités sont à définir.",
    ],
    expect_targeted_question=True,     # le LLM doit poser une question ciblée
    question_fallback_keywords=["unité", "mètre"],  # mots-clés de fallback
),
```

Les champs disponibles dans `GcScenario` :

| Champ | Défaut | Effet |
|---|---|---|
| `should_confirm_gc` | `False` | Si `True`, envoie le 2e message utilisateur pour confirmer le GC |
| `expect_gc_draft` | `False` | Vérifie qu'un GC draft a été créé |
| `expect_gc_activated` | `False` | Vérifie que le GC a été activé |
| `expect_plan_ready` | `False` | Vérifie que `[PLAN_READY]` a été émis |
| `expect_targeted_question` | `False` | Vérifie que le LLM pose une question ciblée |
| `question_fallback_keywords` | `[]` | Mots-clés acceptés si la détection heuristique échoue |
| `strict_no_self_intro` | `False` | Interdit au LLM de se re-présenter |
| `expect_analysis_refusal` | `False` | Vérifie que le LLM refuse un saut direct vers Analyse |
| `check_tool_calls_for_draft` | `False` | Cherche le draft dans les tool calls (cas où il est visible au tour 2) |

La logique d'assertion est entièrement générique — ajouter le scénario suffit.

### Ajouter un check live complet

Dans `copepod/eval_live.py`, après le tour de phase concerné :

```python
ctx.result(
    "live_mon_check",
    condition,
    "Description.",
    {"case_type": "live", "model": ctx.model_name},
)
```

Convention de nommage : préfixer par `live_`.

### Tester un check sans LLM

Tout check peut d'abord être câblé dans `--mock` avec une valeur fixe pour vérifier que le pipeline harness → Langfuse fonctionne avant d'activer la version live.

### Vérifier avant de fusionner

```bash
# 1. Pytest unitaire — aucun appel réseau
pytest tests/test_copepod_plan_mode_eval_runner.py -q

# 2. Mock — guards backend
python scripts/evals/run_copepod_plan_mode_eval.py --mock

# 3. Live ciblé si le check est dans DU-only ou GC-only
python scripts/evals/run_copepod_plan_mode_eval.py --live-du-only --push-langfuse
python scripts/evals/run_copepod_plan_mode_eval.py --live-gc-only --push-langfuse
```

---

## Architecture interne

### `EvalHarness` (`harness.py`)

Context manager qui encapsule tout ce dont une suite a besoin :

```python
with EvalHarness(
    suite="gc-only",
    log_prefix="live_gc_only_eval_",
    tags=["eval", "copepod", "plan-mode", "live", "gc-only"],
    mode="live-gc-only",
    push_langfuse=push_langfuse,
    lf_file_hint="EcoTaxa+EcoPart",
) as ctx:
    ctx.session_id    # str — ID de session unique
    ctx.session_key   # str — clé Redis-style
    ctx.store         # InMemorySessionStore
    ctx.tools         # dict[str, Callable] — tools chargés
    ctx.client        # TestClient FastAPI
    ctx.trace         # Langfuse trace (ou None si désactivé)
    ctx.model_name    # str — depuis settings.LLM_MODEL
    ctx.log(msg)      # écrit dans le log fichier + stdout
    ctx.result(name, passed, detail, metadata)  # enregistre un résultat
    ctx.report        # dict — rapport final (propriété, nouveau dict à chaque appel)
```

À `__exit__`, le harness ferme la trace Langfuse et pousse les scores si `push_langfuse=True`.

### `_run_llm_turn` (`llm_driver.py`)

Boucle d'exécution LLM → tool calls → résultat, jusqu'à `max_tool_rounds` (défaut 40).
Paramètre `log_fn: Callable[[str], None]` pour brancher `ctx.log`. Paramètre `log_fh` maintenu pour rétro-compatibilité avec les scripts sibling.

`describe_column` est limité à un seul round par phase pour éviter les boucles séquentielles.

### Fixtures (`fixtures.py`)

Les fixtures TSV vivent dans `assistant-copepodes-specs/data_exploration/examples_tsv/`.
`_stage_fixture(session_id, path)` les copie dans `static/eval-user/<session_id>/uploads/` sans passer par l'endpoint HTTP `/upload` (évite le rate limiter SlowAPI).

---

## Langfuse

- Langfuse self-hosted sur `http://localhost:3001` (Apple Silicon, `platform: linux/amd64`).
- Si `.env` contient `http://langfuse:3000` (nom de service Docker), le harness replie sur `localhost:3001`.
- SDK : `langfuse==2.60.3` (compatible serveur v2 — ne pas upgrader vers v4 sans migrer le serveur).
- Scores : booléens poussés par le harness à `__exit__` si `--push-langfuse` est passé.
- Trace URL imprimée en fin de run quand Langfuse est actif.

Pour inspecter un run :
1. Ouvrir l'URL de trace imprimée après le run.
2. Repérer le premier score `false`.
3. Ouvrir la génération correspondante : texte LLM + tool calls + résultats.
4. Classer : dérive prompt / garde backend cassé / problème scientifique.

---

## Prérequis locaux

```bash
# Dans le container Docker (image idea_container)
pip install pytest  # si pas encore installé

# Variables d'environnement nécessaires pour --live / --push-langfuse
LLM_MODEL=...
OPENAI_API_KEY=...
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_SECRET_KEY=...
LANGFUSE_HOST=http://localhost:3001
```

---

## Docs de référence

| Fichier | Contenu |
|---|---|
| `docs/copepod-test-operations.md` | Routine de test, niveaux, loop Analyse-Éval-Fix |
| `docs/copepod-plan-mode-eval-coverage.md` | Contrat de couverture complet + lacunes connues |
| `docs/copepod-gc-only-live-eval.md` | Spécification détaillée des scénarios GC |
| `docs/copepod-langfuse-evals.md` | Stratégie Langfuse, méthodes d'évaluation, setup |
| `docs/copepod-eval-status-2026-05-27.md` | Scores détaillés + historique des runs |
