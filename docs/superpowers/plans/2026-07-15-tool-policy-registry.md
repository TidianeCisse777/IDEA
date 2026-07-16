# ToolPolicy Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter une politique immuable et obligatoire aux 59/62 tools, valider la parité au démarrage et générer l'inventaire de `TOOLS.md` depuis le catalogue.

**Architecture:** `tools/tool_catalog.py` reste le seam unique. Des profils de politique réutilisables portent les invariants, tandis qu'un mapping explicite nom→profil classe chaque tool et empêche tout défaut permissif. `tools/tool_docs.py` rend un bloc Markdown déterministe consommé par `scripts/dev/generate_tools_doc.py`.

**Tech Stack:** Python 3.13, dataclasses immuables, `MappingProxyType`, LangChain `BaseTool`, pytest.

## Global Constraints

- Aucun changement de routage ou de liste de tools exposée pendant 2A.1.
- Les trois tools SQL restent optionnels au runtime mais obligatoires dans les métadonnées.
- `result_schema="legacy_text"` jusqu'à 2B.
- Toute politique manquante, orpheline ou incohérente bloque la construction.
- Aucun appel OpenRouter ni benchmark live dans ce lot.

---

### Task 1: Contrat `ToolPolicy` et parité

**Files:**
- Modify: `tools/tool_catalog.py`
- Create: `tests/test_tool_policy_registry.py`

**Interfaces:**
- Produces: `ToolPolicy`, `TOOL_POLICIES`, `ToolCatalog.policies`, `ToolCatalog.policy(name)`.

- [x] Écrire les tests qui exigent une politique pour chaque entrée de `TOOL_PRESENTATION`, l'immutabilité, l'égalité des familles et les invariants fail-closed.
- [x] Exécuter `pytest -q tests/test_tool_policy_registry.py` et constater l'absence de `ToolPolicy`.
- [x] Ajouter les types `ToolRisk`, `ToolSource`, `ToolPolicy`, les profils et le mapping explicite des 62 noms.
- [x] Étendre `validate_catalog()` pour vérifier présentation, politique, famille, confirmation/risque, lecture/mutation, limite d'appels et skill local.
- [x] Étendre `ToolCatalog` et `build_tool_catalog()` sans modifier `catalog.tools` ni `catalog.names`.

### Task 2: Métadonnées de risque sensibles

**Files:**
- Modify: `tools/tool_catalog.py`
- Test: `tests/test_tool_policy_registry.py`

**Interfaces:**
- Consumes: `ToolCatalog.policy(name)`.
- Produces: politiques explicites des exports, enrichissements, code libre, skills et SQL.

- [x] Tester les cinq opérations lourdes, `run_pandas`, `run_graph`, `load_skill`, les enrichissements conditionnels et les trois tools SQL.
- [x] Classer chaque tool par profil explicite; aucun nom n'est complété par un fallback.
- [x] Garder `requires_confirmation` déclaratif même lorsque l'implémentation de l'étape 7 n'existe pas encore.

### Task 3: Inventaire Markdown généré

**Files:**
- Create: `tools/tool_docs.py`
- Create: `scripts/dev/generate_tools_doc.py`
- Modify: `TOOLS.md`
- Test: `tests/test_tool_policy_registry.py`
- Modify: `tests/harness_redteam/test_budget_and_inventory_contracts.py`

**Interfaces:**
- Produces: `render_tool_inventory()`, `replace_generated_inventory()`, CLI `--check`.

- [x] Tester un bloc déterministe contenant 59 obligatoires, 3 SQL optionnels et les champs nom/famille/source/risque/confirmation.
- [x] Implémenter le rendu et le remplacement entre `<!-- TOOL-INVENTORY:START -->` et `<!-- TOOL-INVENTORY:END -->`.
- [x] Générer `TOOLS.md` et retirer uniquement le `xfail` du contrat de parité devenu vert.
- [x] Exécuter une vérification ciblée unique : registre, catalogue, budget de schémas et contrat de parité.

### Task 4: Documentation et gate 2A.1

**Files:**
- Modify: `IMPLEMENTATION_PLAN.md`
- Modify: `HARNESS_REDTEAM_CONTRACTS_2026-07-15.md`

- [ ] Documenter que 2A.1 est terminé et que les confirmations restent non exécutées jusqu'à l'étape 7.
- [ ] Consigner les commandes et résultats ciblés sans relancer le benchmark live.
