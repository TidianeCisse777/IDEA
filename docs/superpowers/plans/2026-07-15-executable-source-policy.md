# Executable Source Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer le filtre EcoTaxa ad hoc par une décision de source multi-source, persistante et fail-closed, dans laquelle une source externe doit être nommée une première fois puis reste active jusqu'à une bascule explicite ou au chargement d'un fichier.

**Architecture:** `tools/source_scope.py` porte les types, le parseur déterministe, la persistance `SourceAffinity` et le calcul pur de `SourceDecision`. Le catalogue existant classe les tools; le middleware consomme une seule décision pour filtrer la requête modèle et bloquer les appels. Le prompt importe un bloc rendu depuis cette politique afin que prose et code restent alignés.

**Tech Stack:** Python 3.13, dataclasses gelées, `Literal`, LangChain 1.x middleware, `SessionStore`, pytest, replay offline.

## Global Constraints

- TDD strict : chaque tranche commence par un test rouge observé avant le code de production.
- Aucun classifieur LLM, aucune source déduite d'un nombre ou d'un vocabulaire générique.
- Aucun registre parallèle des 62 tools : utiliser `ToolPolicy.source`.
- `run_pandas`, `run_graph`, `load_file`, géographie, RAG, taxonomie, livrables et chargement de skills génériques restent disponibles; seuls les tools/skills d'une source externe non autorisée sont filtrés.
- L'autorisation de source et le grounding d'identifiants restent deux contrôles indépendants.
- Aucun benchmark live répété. Un seul smoke test agent contrôlé est permis après tous les gates offline.

---

### Task 1: Parseur et décision pure

**Files:**
- Modify: `tools/source_scope.py`
- Modify: `tests/test_source_scope.py`
- Modify: `tests/harness_redteam/test_source_and_prompt_contracts.py`

**Interfaces:**
- Produces: `SourceName`, `SourceEvidence`, `SourceAffinity`, `SourceDecision`, `parse_explicit_sources(text)`, `decide_source(text, affinity, file_loaded)`.
- Consumes: uniquement du texte et des valeurs immuables; aucune lecture du store.

- [x] **RED 1:** remplacer l'ancien cas positif « résume le projet 17498 » par une assertion négative et ajouter une matrice couvrant noms explicites, IDs nus, exclusions, bascule et combinaison.

```python
def test_bare_project_id_never_selects_ecotaxa():
    decision = decide_source("résume le projet 17498", None, file_loaded=False)
    assert decision.authorized_sources == ()
    assert decision.needs_clarification is True

def test_explicit_ecotaxa_establishes_source():
    decision = decide_source("dans EcoTaxa, projet 17498", None, file_loaded=False)
    assert decision.primary_source == "ecotaxa"
    assert decision.explicit_sources == ("ecotaxa",)
```

- [x] **Verify RED 1:** `pytest -q tests/test_source_scope.py tests/harness_redteam/test_source_and_prompt_contracts.py`; attendu : échec sur l'ID nu et imports absents.
- [x] **GREEN 1:** implémenter les dataclasses gelées, les alias exacts des sept sources, la détection d'exclusion et les modes `replace`/`combine`/`file`/`inherit`. Garder `ecotaxa_signal()` comme façade qui ne retourne vrai que sur une mention EcoTaxa/EcoPart explicite.
- [x] **Verify GREEN 1:** même commande; attendu : contrats source verts, seul le contrat étape 4 reste `xfail`.
- [x] **Commit:** `feat: add deterministic source decision`.

### Task 2: Affinité persistante

**Files:**
- Modify: `tools/source_scope.py`
- Create: `tests/test_source_affinity.py`

**Interfaces:**
- Produces: `source_affinity_key(thread_id)`, `read_source_affinity(store, thread_id)`, `write_source_affinity(store, thread_id, affinity)`, `activate_file_source(store, thread_id)`, `source_decision_for_turn(store, thread_id, messages, persist=True)`.
- Persists: `store.set(f"{thread_id}:source_affinity", None, {"source_affinity": ...})`.

- [x] **RED 2:** tester deux tours successifs, la survie après recréation d'un `SessionStore`, la bascule `EcoTaxa → EcoPart`, la combinaison comparative, l'écrasement par fichier et l'affinité corrompue.

```python
first = source_decision_for_turn(store, "t", [HumanMessage(content="Explore EcoTaxa")])
second = source_decision_for_turn(store, "t", [HumanMessage(content="montre le projet 17498")])
assert first.authorized_sources == second.authorized_sources == ("ecotaxa",)
```

- [x] **Verify RED 2:** `pytest -q tests/test_source_affinity.py`; attendu : helpers absents.
- [x] **GREEN 2:** implémenter la sérialisation validée, une écriture idempotente et la lecture fail-closed. `origin_user_text` est nettoyé et borné à 240 caractères; `updated_at` est ISO UTC.
- [x] **Verify GREEN 2:** même commande; attendu : tous verts.
- [x] **Commit:** `feat: persist source affinity across turns`.

### Task 3: Classification et allowlist depuis `ToolPolicy`

**Files:**
- Modify: `tools/source_scope.py`
- Create: `tests/test_source_policy_tools.py`

**Interfaces:**
- Produces: `source_for_tool_call(name, args, policies)`, `filter_tools_for_decision(tools, decision, policies)`, `source_rejection_for_call(decision, name, args, policies)`.
- Consumes: `TOOL_POLICIES` ou un mapping injecté dans les tests.

- [x] **RED 3:** construire des faux tools de chaque source et vérifier qu'une décision EcoTaxa conserve les tools communs et EcoTaxa, mais retire EcoPart, Amundsen, Bio-ORACLE, OGSL et SQL. Tester aussi les skills source (`ecotaxa_navigation`, `ecopart_query`, `amundsen_ctd_query`, `bio_oracle_query`).
- [x] **Verify RED 3:** `pytest -q tests/test_source_policy_tools.py`; attendu : fonctions absentes.
- [x] **GREEN 3:** classifier depuis `ToolPolicy.source`; traiter `load_skill` via une table source→skills limitée aux skills source. Les sources de politique `file`, `geography`, `knowledge`, `taxonomy`, `skill` générique et `deliverable` restent communes.
- [x] **Verify GREEN 3:** même commande puis `pytest -q tests/test_tool_policy_registry.py tests/test_tool_catalog.py`; attendu : verts.
- [x] **Commit:** `feat: enforce source policy on tool catalog`.

### Task 4: Middleware unique et chargement de fichier

**Files:**
- Modify: `agent.py`
- Modify: `tools/data_tools.py`
- Modify: `tests/test_agent_factory.py`
- Modify: `tests/test_data_tools.py`

**Interfaces:**
- `agent._ContextMiddleware` appelle `source_decision_for_turn()` avant le modèle et avant le tool.
- `load_file()` appelle `activate_file_source()` uniquement après `store_dataset()` réussi.
- Un refus middleware utilise `ToolResult(status="blocked")` dans `ToolMessage.artifact` et `ToolMessage.status="error"` pour LangChain.

- [ ] **RED 4:** tester que le middleware masque toutes les sources externes non autorisées, conserve l'affinité EcoTaxa au second tour, bloque un appel Bio-ORACLE fabriqué et autorise le même appel après mention explicite. Tester qu'un `load_file` réussi remplace l'affinité EcoTaxa, mais qu'un échec ne la modifie pas.
- [ ] **Verify RED 4:** `pytest -q tests/test_agent_factory.py tests/test_data_tools.py -k 'source or affinity'`; attendu : nouveaux tests rouges.
- [ ] **GREEN 4:** remplacer `_source_scope_rejection()` et le filtre ad hoc par la décision commune. Conserver les façades historiques pour les tests existants, sans second parseur dans `agent.py`.
- [ ] **Verify GREEN 4:** même commande, puis `pytest -q tests/test_agent_factory.py tests/test_data_tools.py tests/test_session_context.py`; attendu : verts.
- [ ] **Commit:** `feat: apply source decision in agent middleware`.

### Task 5: Prompt généré et contrat red-team fermé

**Files:**
- Modify: `tools/source_scope.py`
- Modify: `agents/copepod_system_prompt.py`
- Modify: `tests/harness_redteam/test_source_and_prompt_contracts.py`
- Create: `tests/test_source_prompt_contract.py`

**Interfaces:**
- Produces: `render_source_selection_gateway() -> str`, `SOURCE_SELECTION_GATEWAY`.
- Consumes: constantes de noms et règles publiques de `tools/source_scope.py`.

- [ ] **RED 5:** retirer `xfail` du contrat « projet 17498 » et tester que le prompt contient l'héritage d'une source déjà activée, la bascule par fichier et la clarification d'un ID nu.
- [ ] **Verify RED 5:** `pytest -q tests/harness_redteam/test_source_and_prompt_contracts.py tests/test_source_prompt_contract.py`; attendu : prompt non aligné.
- [ ] **GREEN 5:** remplacer uniquement le bloc `Source Selection Gateway` statique par `{SOURCE_SELECTION_GATEWAY}` dans un f-string. Ne pas dupliquer les règles dans deux fichiers.
- [ ] **Verify GREEN 5:** même commande; attendu : contrat étape 3 vert et contrat étape 4 toujours `xfail`.
- [ ] **Commit:** `feat: generate source gateway from policy`.

### Task 6: Replay, gates et smoke test agent

**Files:**
- Modify: `evals/scenarios/harness_reference.json`
- Modify: `tests/test_replay_harness.py`
- Modify: `IMPLEMENTATION_PLAN.md`
- Modify: `BASELINE_HARNESS_2026-07-15.md`
- Modify: `docs/superpowers/specs/2026-07-15-source-policy-design.md`

**Interfaces:**
- Adds: un troisième tour à `SC-ECOTAXA` sans répétition du nom EcoTaxa.
- Produces: baseline offline régénérée une fois et preuve du smoke agent.

- [ ] **RED 6:** ajouter le tour « résume maintenant le projet 17498 » et un test séquentiel qui exige l'affinité héritée.
- [ ] **Verify RED 6:** `pytest -q tests/test_replay_harness.py tests/test_source_affinity.py`; attendu : fixture/attente non satisfaite avant adaptation.
- [ ] **GREEN 6:** adapter la fixture offline avec un résultat structuré et intégrer la décision dans la vérification de continuité sans appel modèle.
- [ ] **Targeted gate once:** `pytest -q tests/test_source_scope.py tests/test_source_affinity.py tests/test_source_policy_tools.py tests/test_source_prompt_contract.py tests/test_agent_factory.py tests/test_data_tools.py tests/test_session_context.py tests/test_replay_harness.py tests/harness_redteam/`.
- [ ] **Full gate once:** `pytest -q tests/`.
- [ ] **Offline baseline once:** `python -m evals.replay_harness --lane offline --runs 1 --output evals/baseline_offline_2026-07-15.json`.
- [ ] **Controlled agent smoke once:** dans un store isolé et tracing désactivé, exécuter au maximum trois tours : activation explicite EcoTaxa, suivi sans répétition, puis chargement fichier/bascule. Interdire tout tool lourd et consigner tools visibles/appelés. Si aucun provider n'est configuré, utiliser le modèle fake LangChain et documenter cette limite au lieu d'inventer un résultat live.
- [ ] **Docs:** noter taux de trajectoire, tools visibles, tokens fixes, type de smoke (réel/fake), skips et limites. Marquer l'étape 3 terminée seulement si tous les gates déterministes sont verts.
- [ ] **Commit:** `docs: close executable source policy gate`.
