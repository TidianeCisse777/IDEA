# Dynamic Tool Filtering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Exposer au modèle au plus 15 tools déterminés par la source, l'état de session et l'étape du workflow, tout en bloquant avant exécution les tools absents de l'allowlist courante.

**Architecture:** Étendre `ToolPolicy` avec un groupe d'exposition exhaustif, puis ajouter un moteur pur `tools/tool_exposure.py`. `_ContextMiddleware` applique sa décision après le filtre de source et avant le calcul du budget de contexte; les wrappers d'exécution réutilisent la même décision comme garde fail-closed.

**Tech Stack:** Python 3.13, LangChain 1.x `AgentMiddleware`, LangGraph `create_agent`, Pydantic/LangChain tools, pytest.

## Global Constraints

- Aucun second modèle, embedding ou mécanisme provider-specific.
- Le catalogue runtime reste à 59 tools obligatoires, 62 avec SQL.
- Chaque tool possède un groupe d'exposition validé; aucun groupe par défaut implicite.
- Noyau permanent exact : `load_file`, `load_skill`, `query_copepod_knowledge_base`.
- EcoPart, Amundsen CTD, Bio-ORACLE et OGSL exposent uniquement leur enrichissement canonique après demande explicite sur un fichier chargé.
- EcoTaxa est découpé en sept sous-toolsets et n'expose jamais ses 28 tools ensemble.
- Toute allowlist contient au plus 15 tools; overflow → noyau + découverte EcoTaxa si autorisée.
- Un tool non visible est bloqué avant exécution.
- TDD strict pour chaque comportement; benchmark live N ≥ 5 jamais lancé implicitement.

---

### Task 1: Métadonnée exhaustive de groupe d'exposition

**Files:**
- Modify: `tools/tool_catalog.py`
- Modify: `tests/test_tool_policy_registry.py`

**Interfaces:**
- Produces: `ToolExposureGroup`, `ToolPolicy.exposure_group`, politiques exhaustives pour les 62 tools.
- Consumes: `TOOL_PRESENTATION`, `_TOOL_PROFILE_BY_NAME`, validation actuelle du catalogue.

- [ ] **Step 1: Write the failing registry tests**

Ajouter des assertions qui exigent un groupe valide pour les 62 politiques, les quatre enrichissements canoniques et la liste fermée `hidden_legacy`.

```python
def test_every_policy_has_a_valid_exposure_group():
    from tools.tool_catalog import TOOL_EXPOSURE_GROUPS, TOOL_POLICIES

    assert len(TOOL_POLICIES) == 62
    assert all(policy.exposure_group in TOOL_EXPOSURE_GROUPS for policy in TOOL_POLICIES.values())


def test_enrichment_and_legacy_groups_are_explicit():
    from tools.tool_catalog import TOOL_POLICIES

    assert TOOL_POLICIES["enrich_ecotaxa_with_ecopart_remote"].exposure_group == "enrichment_ecopart"
    assert TOOL_POLICIES["enrich_with_amundsen_ctd"].exposure_group == "enrichment_amundsen"
    assert TOOL_POLICIES["enrich_with_bio_oracle"].exposure_group == "enrichment_bio_oracle"
    assert TOOL_POLICIES["enrich_with_ogsl"].exposure_group == "enrichment_ogsl"
    assert TOOL_POLICIES["query_bio_oracle"].exposure_group == "hidden_legacy"
```

- [ ] **Step 2: Run RED**

Run: `pytest tests/test_tool_policy_registry.py -q`  
Expected: FAIL because `ToolPolicy` has no `exposure_group`.

- [ ] **Step 3: Implement the exhaustive catalog metadata**

Ajouter le literal, le champ immuable et une table `_EXPOSURE_GROUP_BY_NAME` couvrant exactement `TOOL_PRESENTATION`. Étendre `_build_policy()` et `validate_catalog()` pour refuser l'absence, l'excès ou un groupe invalide.

- [ ] **Step 4: Run GREEN**

Run: `pytest tests/test_tool_policy_registry.py -q`  
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add tools/tool_catalog.py tests/test_tool_policy_registry.py
git commit -m "feat: classify every tool by exposure group"
```

### Task 2: Moteur pur de sélection déterministe

**Files:**
- Create: `tools/tool_exposure.py`
- Create: `tests/test_tool_exposure.py`

**Interfaces:**
- Consumes: `TurnContext`, `SourceDecision`, `ToolPolicy`, `successful_calls_in_current_turn()`.
- Produces: `TurnSignals`, `ToolExposureDecision`, `build_turn_signals(messages)`, `decide_tool_exposure(available_names, policies, turn_context, source_decision, messages, max_tools=15)`.

- [ ] **Step 1: Write failing tests for the permanent core and local state**

Les tests utilisent des `HumanMessage`, un `TurnContext` synthétique et les vraies `TOOL_POLICIES`. Ils exigent : noyau exact sans fichier, ajout de `run_pandas` avec fichier, géographie/taxonomie uniquement sur intention, workflow graph/deliverable uniquement après `ToolResult(success)` du tour.

- [ ] **Step 2: Run RED**

Run: `pytest tests/test_tool_exposure.py -q`
Expected: ERROR importing missing `tools.tool_exposure`.

- [ ] **Step 3: Implement typed signals and the minimal core decision**

Créer des dataclasses gelées. Extraire le texte du dernier `HumanMessage`, les appels réussis du tour via `successful_calls_in_current_turn()`, puis sélectionner les groupes `core`, `file_analysis`, `geography`, `taxonomy`, `visualization` et `deliverable`.

- [ ] **Step 4: Run the local-state tests GREEN**

Run command: `pytest tests/test_tool_exposure.py -q`
Expected: local-state tests pass.

- [ ] **Step 5: Add failing enrichment tests**

Pour chaque source, paramétrer les quatre cas : source seule, enrichissement sans fichier, fichier + enrichissement explicite, tool legacy forcé. Le cas positif doit contenir exactement un tool de la famille.

- [ ] **Step 6: Run enrichment tests RED**

Run: `pytest tests/test_tool_exposure.py -q`  
Expected: FAIL because enrichment groups are not selected yet.

- [ ] **Step 7: Implement enrichment predicates**

Reconnaître les verbes français/anglais d'enrichissement et intersecter les sources demandées avec `SourceDecision.authorized_sources`. Sélectionner seulement :

```python
ENRICHMENT_TOOL_BY_SOURCE = {
    "ecopart": "enrich_ecotaxa_with_ecopart_remote",
    "amundsen": "enrich_with_amundsen_ctd",
    "bio_oracle": "enrich_with_bio_oracle",
    "ogsl": "enrich_with_ogsl",
}
```

- [ ] **Step 8: Add failing EcoTaxa matrix tests**

Tester les sept intentions, le fallback Découverte, l'identifiant nu, l'affinité, l'union de deux groupes et la limite de deux groupes.

- [ ] **Step 9: Run EcoTaxa tests RED**

Run: `pytest tests/test_tool_exposure.py -q`  
Expected: FAIL because EcoTaxa subgroup routing is absent.

- [ ] **Step 10: Implement EcoTaxa subgroup selection and overflow fallback**

Ajouter des patterns bornés pour `discovery`, `samples`, `geo_time`, `taxonomy`, `schema`, `audit`, `export`. Sans pattern : `ecotaxa_discovery`. Préserver l'ordre du catalogue et refuser toute décision supérieure à 15 par fallback déterministe.

- [ ] **Step 11: Run all pure-engine tests GREEN**

Run: `pytest tests/test_tool_exposure.py tests/test_tool_policy_registry.py -q`  
Expected: all tests pass.

- [ ] **Step 12: Commit**

```bash
git add tools/tool_exposure.py tests/test_tool_exposure.py tools/tool_catalog.py tests/test_tool_policy_registry.py
git commit -m "feat: add deterministic per-turn tool policy engine"
```

### Task 3: Filtrage pré-modèle et audit des économies

**Files:**
- Modify: `agent.py`
- Modify: `tests/test_agent_factory.py`

**Interfaces:**
- Consumes: `decide_tool_exposure()`, filtre de source existant, `_tool_schema_tokens()`.
- Produces: requête finale avec `tools=exposed_tools`; audit avant/après source/politique et tokens économisés.

- [ ] **Step 1: Write failing middleware tests**

Étendre la fixture `Request` pour vérifier :

```python
assert [tool.name for tool in prepared["tools"]] == [
    "load_file",
    "load_skill",
    "query_copepod_knowledge_base",
    "find_ecotaxa_projects",
    "list_ecotaxa_projects",
]
assert audit["tool_exposure_count"] <= 15
assert audit["approx_tokens_tool_schemas_after"] < audit["approx_tokens_tool_schemas_before"]
```

Les noms exacts attendus suivent l'ordre réel du catalogue fourni par la fixture.

- [ ] **Step 2: Run RED**

Run: `pytest tests/test_agent_factory.py -q`  
Expected: FAIL because local tools outside the active groups remain visible and audit fields are absent.

- [ ] **Step 3: Integrate the engine before token budgeting**

Dans `_prepare_request()` : conserver `original_tools`, appliquer `filter_tools_for_decision()`, calculer `ToolExposureDecision`, construire `exposed_tools`, puis seulement calculer `tool_schema_tokens` et `history_budget`. Enregistrer les champs d'audit définis par la spécification.

- [ ] **Step 4: Preserve backward compatibility for `request.override`**

Le fallback `TypeError` reste sans mutation des messages/checkpoints. Il doit enregistrer `tool_filter_override_supported=False`; le chemin normal enregistre `True`.

- [ ] **Step 5: Run GREEN and adjacent regressions**

Run: `pytest tests/test_agent_factory.py tests/test_source_scope.py tests/test_turn_context.py -q`  
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add agent.py tests/test_agent_factory.py
git commit -m "feat: filter model tools from deterministic turn policy"
```

### Task 4: Garde d'exécution sync/async

**Files:**
- Modify: `agent.py`
- Create: `tests/test_tool_exposure_middleware.py`

**Interfaces:**
- Consumes: même `ToolExposureDecision` que le filtrage pré-modèle; `catalog.names` transmis au middleware par `make_agent()`.
- Produces: `_tool_exposure_rejection(request)` et blocage `ToolResult(status="blocked")` avec provenance `tool_exposure_policy`.

- [ ] **Step 1: Write failing sync and async guard tests**

Tester : enrichissement canonique autorisé, `query_bio_oracle` caché bloqué, `run_graph` bloqué avant writer, appel sync/async identique, garde de source prioritaire conservée.

- [ ] **Step 2: Run RED**

Run: `pytest tests/test_tool_exposure_middleware.py -q`  
Expected: FAIL because hidden tools still reach the handler.

- [ ] **Step 3: Implement shared exposure rejection**

Passer `catalog_names=catalog.names` à `_ContextMiddleware`. Reconstruire `TurnContext` et `SourceDecision` depuis `request.state["messages"]`, calculer la décision et refuser tout nom absent. Ajouter cette garde après source/identifiants et avant la garde graphique.

- [ ] **Step 4: Run GREEN and graph regressions**

Run: `pytest tests/test_tool_exposure_middleware.py tests/test_output_intent_middleware.py tests/test_agent_factory.py -q`  
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add agent.py tests/test_tool_exposure_middleware.py
git commit -m "feat: block tools hidden by per-turn exposure policy"
```

### Task 5: Replay, budget contract and documentation

**Files:**
- Modify: `evals/replay_harness.py`
- Modify: `tests/harness_redteam/test_budget_and_inventory_contracts.py`
- Modify: `tests/test_replay_harness.py`
- Modify: `IMPLEMENTATION_PLAN.md`
- Modify: `ARCHITECTURE.md`
- Modify: `TOOLS.md`

**Interfaces:**
- Consumes: nouveaux champs de l'audit de contexte.
- Produces: rapport normalisé de tools exposés et tokens avant/après; contrat de coût basé sur la requête réelle plutôt que le catalogue complet.

- [ ] **Step 1: Write failing replay and budget tests**

Exiger la présence normalisée de `tools_exposed`, `tool_exposure_groups`, `tool_exposure_count`, `policy_overflow`, `approx_tokens_tool_schemas_before/after/saved`. Remplacer le calcul red-team sur les 62 schémas par la pire décision représentative de la matrice déterministe.

- [ ] **Step 2: Run RED**

Run: `pytest tests/test_replay_harness.py tests/harness_redteam/test_budget_and_inventory_contracts.py -q`  
Expected: FAIL because replay does not capture the new audit and the budget still prices le catalogue complet.

- [ ] **Step 3: Implement replay normalization and update the contract**

Lire les nouveaux champs sans parser les réponses textuelles. Le contrat garde `xfail(strict=True)` uniquement si le system prompt + la plus grosse allowlist valide dépassent encore 40 %; sinon retirer le marqueur.

- [ ] **Step 4: Update generated and narrative docs**

Documenter que les 59/62 tools restent enregistrés mais que ≤15 sont présentés à chaque appel. Régénérer l'inventaire si le générateur inclut le nouveau groupe, puis mettre à jour le statut de l'étape 6 sans fermer le benchmark live avant son exécution.

- [ ] **Step 5: Run deterministic gates**

Run: `pytest tests/test_tool_exposure.py tests/test_tool_exposure_middleware.py tests/test_tool_policy_registry.py tests/test_agent_factory.py tests/test_replay_harness.py tests/harness_redteam -q`  
Expected: all non-future contracts pass; confirmation step 7 remains xfailed.

- [ ] **Step 6: Run offline reference scenarios**

Run: `python evals/replay_harness.py --mode offline --scenario all`  
Expected: SC-LAB, SC-ENRICH and SC-ECOTAXA levels 1 and 2 remain at 100 %, with every model call at ≤15 tools.

- [ ] **Step 7: Run full regression suite**

Run: `pytest tests/ -q`  
Expected: no failures; live EcoTaxa/PostgreSQL tests may remain skipped; only future strict xfails remain.

- [ ] **Step 8: Commit**

```bash
git add evals/replay_harness.py tests/test_replay_harness.py tests/harness_redteam/test_budget_and_inventory_contracts.py IMPLEMENTATION_PLAN.md ARCHITECTURE.md TOOLS.md
git commit -m "docs: close deterministic tool filtering gates"
```

## Deferred Live Gate

Après les gates déterministes et uniquement avec commande explicite : rejouer `SC-LAB`, `SC-ENRICH` et `SC-ECOTAXA` N ≥ 5 avec le modèle réel. Ne pas déclarer l'étape 6 entièrement fermée tant que le rapport daté ne confirme pas qu'aucun tool nécessaire n'est masqué.

---

## Correctif géographique — capacités toujours visibles

### Task 6: Supprimer la pré-détection géographique lexicale

**Files:**
- Modify: `tools/tool_exposure.py`
- Modify: `tests/test_tool_exposure.py`

**Interfaces:**
- Consumes: `decide_tool_exposure(...)` et les groupes existants `geography` / `ecotaxa_geo_time`.
- Produces: une allowlist où `geography` est toujours actif et où EcoTaxa ajoute toujours `ecotaxa_geo_time`, sans `_GEOGRAPHY_PATTERN` ni `TurnSignals.geography_requested`.

- [ ] **Step 1: Write the failing Hudson and source-matrix tests**

```python
def test_geography_tools_are_always_visible_without_lexical_detection():
    for text in ("Bonjour", "Baie d’Hudson", "secteur scientifique alpha"):
        decision = _decision(text)
        assert "get_zone_info" in decision.tool_names
        assert "filter_dataframe_by_zone" in decision.tool_names

def test_ecotaxa_always_includes_geo_time_with_at_most_one_other_group():
    decision = _decision("Audite le projet EcoTaxa", sources=("ecotaxa",))
    assert "ecotaxa_geo_time" in decision.active_groups
    assert "ecotaxa_audit" in decision.active_groups
    assert len(decision.tool_names) <= 15
```

- [ ] **Step 2: Run RED**

Command: `pytest tests/test_tool_exposure.py -q`

Expected: FAIL because neutral/Hudson text does not expose `geography` and EcoTaxa audit omits `ecotaxa_geo_time`.

- [ ] **Step 3: Implement the minimal policy change**

Delete `_GEOGRAPHY_PATTERN` and `TurnSignals.geography_requested`. Initialize groups with `['core', 'geography']`. For EcoTaxa, select the first non-geographic intent or discovery, then prepend `ecotaxa_geo_time`. Update overflow fallback to preserve `geography` and, for EcoTaxa, `ecotaxa_geo_time` plus discovery when the combination fits.

- [ ] **Step 4: Run GREEN and the middleware regression**

Run: `pytest tests/test_tool_exposure.py tests/test_tool_exposure_middleware.py tests/test_agent_factory.py -q`
Expected: PASS; every decision remains at 15 tools maximum.

- [ ] **Step 5: Validate the real Hudson curl once**

Run the existing `curl-neolabs-2014-2020` request for Hudson, then query `/debug/context-audit`.
Expected: `geography` in `tool_exposure_groups`, `get_zone_info` and `filter_dataframe_by_zone` in `tools_exposed`, no overflow.

- [ ] **Step 6: Commit**

```bash
git add tools/tool_exposure.py tests/test_tool_exposure.py docs/superpowers/plans/2026-07-16-dynamic-tool-filtering.md
git commit -m "fix: keep geographic capabilities visible"
```
