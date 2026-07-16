# Harness Step 2 Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Terminer l'étape 2 du renforcement du harness en imposant des entrées strictes aux 62 tools puis en faisant transiter chaque résultat par une enveloppe `ToolResult` structurée, sans parser les anciens messages textuels.

**Architecture:** `tools/tool_catalog.py` demeure la source de vérité des politiques et applique les schémas stricts au démarrage. `tools/tool_result.py` définit l'enveloppe et produit le contrat LangChain natif `content_and_artifact` : le contenu textuel reste visible par le modèle et les clients existants, tandis que l'artefact porte le statut structuré. Chaque fonction `@tool` choisit explicitement son statut; le catalogue refuse tout tool encore en `legacy_text` à la fin de 2B.

**Tech Stack:** Python 3.13, Pydantic 2, LangChain `BaseTool`/`ToolMessage`, pytest, replay offline déterministe.

**État final (15 juillet 2026) : terminé.** Tasks 1 à 7 implémentées et commitées par tranche. Task 8 validée par les scans de contrats, la suite complète et une seule régénération offline; aucun benchmark live n'a été lancé.

## Global Constraints

- Aucun changement de liste ou de routage des tools pendant l'étape 2.
- Aucun benchmark live ni appel OpenRouter automatique.
- TDD par tranche : un run rouge, une implémentation, un run vert ciblé.
- Les réponses textuelles visibles restent stables lorsque le statut change de représentation.
- Aucun statut n'est inféré en parsant des préfixes comme `Erreur` ou `Aucun`.
- À la fin, chaque politique vaut `result_schema="tool_result_v1"` et chaque tool utilise `response_format="content_and_artifact"`.
- `ToolResult.status` appartient exactement à `success | empty | blocked | error | cancelled`.

---

### Task 1: Schémas d'entrée stricts (2A.2) — terminé

**Files:**
- Create: `tools/tool_input.py`
- Modify: `tools/tool_catalog.py`
- Modify: `tools/ecopart_sources.py`
- Create: `tests/test_tool_input_contracts.py`

**Interfaces:**
- Produces: `strict_tool_args_schema(tool: BaseTool) -> type[BaseModel]`, `apply_strict_tool_schema(tool: BaseTool) -> BaseTool`.
- Consumes: chaque `BaseTool.args_schema` construit par LangChain.

- [ ] Écrire des tests exigeant `extra="forbid"`, le rejet de coercitions (`"105"` vers `int`) et `project_id` requis pour `list_ecopart_samples`/`query_ecopart`.
- [ ] Exécuter `pytest -q tests/test_tool_input_contracts.py` et constater le passage coercif et les défauts `105`.
- [ ] Créer un modèle Pydantic dérivé via `create_model`, conserver annotations/descriptions, appliquer `ConfigDict(strict=True, extra="forbid")` et mettre en cache par schéma source.
- [ ] Retirer `project_id=105` des deux signatures EcoPart; l'identifiant doit venir explicitement du modèle ou du contexte.
- [ ] Appliquer le schéma dans `build_tool_catalog()` avant validation et ajouter à `validate_catalog()` les invariants strict/extra/arguments dangereux.
- [ ] Exécuter une seule fois les tests ciblés `test_tool_input_contracts.py`, `test_tool_catalog.py` et `test_tool_schema_budget.py`.
- [ ] Commit : `feat: enforce strict tool input schemas`.

### Task 2: Contrat commun `ToolResult` — terminé

**Files:**
- Create: `tools/tool_result.py`
- Create: `tests/test_tool_result_contract.py`
- Modify: `tools/tool_catalog.py`

**Interfaces:**
- Produces: `ToolStatus`, `ToolResult`, `ToolOutput`, `success()`, `empty()`, `blocked()`, `error()`, `cancelled()`, `validate_tool_artifact()`.
- `ToolOutput = tuple[str, dict[str, Any]]`; le premier élément est `summary`, le second `ToolResult.model_dump(mode="json")`.

- [ ] Écrire les tests du schéma, des cinq statuts, des champs `summary`, `data_ref`, `artifact_refs`, `provenance`, `persisted`, `retryable`, `method`, `metrics` et de la sérialisation JSON.
- [ ] Vérifier le rouge : module absent.
- [ ] Implémenter un `BaseModel` gelé avec `extra="forbid"`, `summary` non vide et constructeurs explicites; `error()` exige un résumé sûr et ne sérialise pas d'exception brute ailleurs.
- [ ] Tester qu'un `@tool(response_format="content_and_artifact")` conserve son string sur `.invoke(args)` et produit un `ToolMessage.artifact` validable sur `.invoke(tool_call)`.
- [ ] Étendre `ToolPolicy.result_schema` à `Literal["legacy_text", "tool_result_v1"]` pendant la migration.
- [ ] Exécuter `pytest -q tests/test_tool_result_contract.py tests/test_tool_policy_registry.py`.
- [ ] Commit : `feat: add structured tool result contract`.

### Task 3: Familles locales et core — terminé

**Files:**
- Modify: `tools/data_tools.py`
- Modify: `tools/geo_tools.py`
- Modify: `tools/rag_tool.py`
- Modify: `tools/taxonomy_tool.py`
- Modify: `tools/skill_tool.py`
- Modify: `tools/deliverable_tool.py`
- Modify: `tools/tool_catalog.py`
- Create: `tests/test_tool_result_local_families.py`

**Interfaces:**
- Consumes: constructeurs `ToolOutput` de Task 2.
- Produces: dix tools `content_and_artifact` et politiques `tool_result_v1`.

- [ ] Tester au minimum un chemin `success`, `empty`, `blocked` et `error`, plus `data_ref`/`artifact_refs`/`persisted` pour fichier, dataframe, graphe et livrable.
- [ ] Vérifier le rouge : artefacts absents.
- [ ] Remplacer chaque `@tool` par `@tool(response_format="content_and_artifact")` (préserver `description=`) et chaque retour terminal par le constructeur correspondant.
- [ ] Garder le résumé textuel identique; renseigner les références de dataset et d'artefact déjà connues au point de retour.
- [ ] Marquer les dix politiques `tool_result_v1`.
- [ ] Exécuter les nouveaux contrats et les modules de tests métier touchés une seule fois.
- [ ] Commit : `feat: migrate local tools to ToolResult`.

### Task 4: Famille EcoTaxa — terminé

**Files:**
- Modify: `tools/copepod_sources.py`
- Modify: `tools/tool_catalog.py`
- Create: `tests/test_tool_result_ecotaxa.py`

**Interfaces:**
- Produces: 28 tools EcoTaxa avec statut explicite et provenance EcoTaxa.

- [ ] Écrire des contrats paramétrés sur les 28 noms et des tests fonctionnels pour succès, résultat vide, validation bloquée et erreur d'adaptateur.
- [ ] Vérifier le rouge : `response_format="content"` et aucun artefact.
- [ ] Migrer les retours externes des 28 fonctions sans modifier les helpers de formatage internes; chaque `except` devient `error`, absence de lignes devient `empty`, précondition utilisateur devient `blocked`, données valides deviennent `success`.
- [ ] Ajouter `provenance` (source EcoTaxa, IDs utilisés) et `data_ref` lorsqu'un dataset est persisté.
- [ ] Marquer les 28 politiques `tool_result_v1`.
- [ ] Exécuter les contrats EcoTaxa et les tests EcoTaxa existants une fois.
- [ ] Commit : `feat: migrate ecotaxa tools to ToolResult`.

### Task 5: Sources EcoPart, Amundsen, Bio-ORACLE et OGSL — terminé

**Files:**
- Modify: `tools/ecopart_sources.py`
- Modify: `tools/amundsen_sources.py`
- Modify: `tools/bio_oracle_sources.py`
- Modify: `tools/ogsl_sources.py`
- Modify: `tools/tool_catalog.py`
- Create: `tests/test_tool_result_remote_families.py`

**Interfaces:**
- Produces: 22 tools de sources distantes avec statut explicite, provenance et références persistées.

- [ ] Écrire des contrats paramétrés sur les 22 noms et des tests représentatifs des cinq statuts pertinents.
- [ ] Vérifier le rouge.
- [ ] Migrer EcoPart (7), Amundsen (6), Bio-ORACLE (7), OGSL (2), famille par famille, avec un run vert ciblé après chaque famille.
- [ ] Distinguer `empty` (requête valide sans données), `blocked` (précondition/confirmation manquante) et `error` (échec de source).
- [ ] Marquer les 22 politiques `tool_result_v1`.
- [ ] Exécuter les tests métier des quatre modules une fois après la migration complète.
- [ ] Commit : `feat: migrate remote source tools to ToolResult`.

### Task 6: SQL optionnel et fermeture fail-closed de 2B — terminé

**Files:**
- Modify: `tools/sql_workspace.py`
- Modify: `tools/tool_catalog.py`
- Modify: `tests/test_tool_result_contract.py`

**Interfaces:**
- Produces: trois tools SQL structurés et `validate_catalog()` sans autorisation legacy.

- [ ] Tester les trois tools SQL (success/empty/error) et la validation qui refuse une politique `legacy_text` ou un tool sans `content_and_artifact`.
- [ ] Vérifier le rouge.
- [ ] Migrer les trois wrappers SQL et marquer leurs politiques `tool_result_v1`.
- [ ] Remplacer la tolérance transitoire du catalogue par `result_schema == "tool_result_v1"` pour les 62 noms.
- [ ] Ajouter un test de parité global : 62 politiques structurées, 59 tools obligatoires structurés, 3 SQL structurés lorsqu'ils sont configurés.
- [ ] Exécuter les contrats du catalogue et SQL une fois.
- [ ] Commit : `feat: enforce ToolResult for every tool`.

### Task 7: Replay et observabilité structurés — terminé

**Files:**
- Modify: `evals/replay_harness.py`
- Modify: `tests/test_replay_harness.py`
- Modify: `evals/scenarios/harness_reference.json`

**Interfaces:**
- Consumes: `ToolMessage.artifact` validé par `validate_tool_artifact()`.
- Produces: `tool_calls[*].result` structuré et `status` issu exclusivement de l'artefact.

- [ ] Écrire un test où le contenu contient le mot « Erreur » mais l'artefact est `success`, et vérifier que le grader conserve `success`; écrire le cas artefact absent qui échoue explicitement.
- [ ] Vérifier le rouge : le replay lit `ToolMessage.status` et `result_preview` seulement.
- [ ] Capturer `message.artifact`, valider `ToolResult`, enregistrer le payload et dériver `status` de `artifact.status` uniquement.
- [ ] Ajouter aux fixtures offline des résultats structurés minimaux afin que les pistes partagent le même schéma.
- [ ] Supprimer toute logique de statut basée sur `startswith`, regex ou sous-chaîne de contenu dans le replay.
- [ ] Exécuter `pytest -q tests/test_replay_harness.py tests/test_tool_result_contract.py`.
- [ ] Commit : `feat: capture structured tool results in replay`.

### Task 8: Gates, documentation et baseline offline — terminé

**Files:**
- Modify: `IMPLEMENTATION_PLAN.md`
- Modify: `HARNESS_REDTEAM_CONTRACTS_2026-07-15.md`
- Modify: `TOOLS.md`
- Modify: `evals/baseline_offline_2026-07-15.json`

**Interfaces:**
- Produces: preuve de fermeture de 2A.2 et 2B.

- [ ] Rechercher `result_schema="legacy_text"`, policies legacy, tools sans `content_and_artifact`, `project_id=105` et parseurs de statut; toute occurrence runtime non justifiée échoue.
- [ ] Lancer la suite ciblée de l'étape 2 une fois, puis la suite `pytest tests/` une fois.
- [ ] Générer une seule baseline offline déterministe et comparer routage, tools exposés et trajectoires à la baseline précédente; ne pas lancer le benchmark live.
- [ ] Mettre à jour le plan principal, les contrats red-team et l'inventaire généré avec les commandes et résultats exacts.
- [ ] Faire `git diff --check`, revue du diff et commit : `docs: close harness step 2 gates`.

## Completion Audit

- 2A.2 : 62 schémas stricts, extra interdit, deux `project_id` EcoPart requis, construction du catalogue verte.
- 2B : 62 politiques `tool_result_v1`, 62 tools `content_and_artifact`, aucun adaptateur legacy, cinq statuts validés.
- Replay : statut lu depuis l'artefact et jamais depuis le texte.
- Comportement : réponses textuelles existantes préservées, trajectoire offline stable, suite complète verte.
