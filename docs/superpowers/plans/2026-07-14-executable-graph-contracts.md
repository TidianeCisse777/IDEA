# Executable Graph Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bloquer avant affichage les figures dont les axes, inversions, zéros ou mappings visuels ne respectent pas la demande scientifique.

**Architecture:** Un module pur valide le dictionnaire `graph_contract`, puis inspecte les axes et artistes de la figure matplotlib. `run_graph` appelle ce validateur après l’exécution du code et avant la capture PNG ; le prompt et `graph_writer` imposent la déclaration du contrat et les `gid` vérifiables.

**Tech Stack:** Python 3, matplotlib, Cartopy, pytest, LangChain tools, FastAPI OpenAI-compatible.

## Global Constraints

- TDD strict : chaque comportement est observé rouge avant implémentation.
- Seul l’axe de profondeur d’un profil vertical peut être inversé.
- Les abondances utilisent uniquement `abundance_ind_L` ou `abundance_ind_m3`.
- Les zéros échantillonnés restent présents par défaut ; le diagramme T–S les affiche en cercles vides.
- Les cartes utilisent Cartopy et matérialisent taille d’abondance, couleur environnementale et légendes distinctes.
- Un refus graphique interdit le repli vers un tableau.
- Aucun nom interne de tool n’est exposé dans la réponse finale utilisateur.

---

### Task 1: Validateur pur des contrats et axes

**Files:**
- Create: `core/graph_contracts.py`
- Create: `tests/test_graph_contracts.py`

**Interfaces:**
- Produces: `validate_graph_contract(contract: dict | None, figure) -> str | None`.
- Contract shape: `kind`, `axes`, `inverted_axes`, `mappings`, `zero_policy`, `source_variables`.

- [ ] **Step 1: Write failing schema and vertical-profile tests**

```python
def test_missing_contract_is_blocked():
    fig, _ = plt.subplots()
    assert "missing" in validate_graph_contract(None, fig)

def test_vertical_profile_requires_only_depth_y_inverted():
    fig, ax = plt.subplots()
    ax.invert_xaxis(); ax.invert_yaxis()
    issue = validate_graph_contract(vertical_contract(), fig)
    assert "abundance x-axis must remain normal" in issue
```

- [ ] **Step 2: Run RED**

Run: `pytest -q tests/test_graph_contracts.py`
Expected: FAIL because `core.graph_contracts` does not exist.

- [ ] **Step 3: Implement schema and inversion validation**

Implement allowed kinds, required fields, axis-index bounds, exact comparison of `xaxis_inverted()` / `yaxis_inverted()`, vertical x role and depth y role.

- [ ] **Step 4: Run GREEN**

Run: `pytest -q tests/test_graph_contracts.py`
Expected: all current tests PASS.

- [ ] **Step 5: Commit**

```bash
git add core/graph_contracts.py tests/test_graph_contracts.py
git commit -m "feat(graphs): validate graph axes contracts"
```

### Task 2: Relations, T–S et carte

**Files:**
- Modify: `core/graph_contracts.py`
- Modify: `tests/test_graph_contracts.py`

**Interfaces:**
- Mapping entries use `{"variable": str, "artist_gid": str}`.
- Zero policy uses `{"mode": "include"|"hollow", "artist_gid": str|None}`.

- [ ] **Step 1: Write failing tests for independent environmental axes**

Create three axes, share two deliberately, and assert refusal. Assert every environmental panel has a normal abundance axis.

- [ ] **Step 2: Run RED**

Run: `pytest -q tests/test_graph_contracts.py -k environment`
Expected: FAIL because panel independence is not validated.

- [ ] **Step 3: Implement independence checks**

Use matplotlib shared-axis sibling groups and reject any pair of environmental panels sharing x or y.

- [ ] **Step 4: Write failing T–S artist tests**

Create size/depth/station collections with `gid`; create a filled zero collection and assert `zero abundance must use hollow markers`.

- [ ] **Step 5: Implement T–S validation**

Require salinity x, temperature y, normal axes, size=`abundance_ind_L`, colour=depth, station shape/facet, and a hollow zero collection whose facecolour is `none`/empty.

- [ ] **Step 6: Write failing Cartopy map tests**

Assert refusal for a plain matplotlib axis, missing environmental-colour artist, or absent distinct size/colour legend gids.

- [ ] **Step 7: Implement map validation**

Require a Cartopy `GeoAxes`, position transform declaration, size=`abundance_ind_L`, environmental colour mapping, and artists with gids `abundance_size_legend` and `environment_color_legend`.

- [ ] **Step 8: Run GREEN and commit**

Run: `pytest -q tests/test_graph_contracts.py`
Expected: PASS.

```bash
git add core/graph_contracts.py tests/test_graph_contracts.py
git commit -m "feat(graphs): enforce scientific visual mappings"
```

### Task 3: Intégration dans run_graph

**Files:**
- Modify: `tools/data_tools.py`
- Modify: `tests/test_data_tools.py`

**Interfaces:**
- Consumes: `validate_graph_contract(local_vars.get("graph_contract"), fig)`.
- Produces: existing image markdown on success; corrective blocking message on failure.

- [ ] **Step 1: Write failing integration tests**

Add one test proving missing contract is blocked and one compliant vertical-profile figure returning `/graphs/`. Assert graph-block session metadata is set on refusal.

- [ ] **Step 2: Run RED**

Run: `pytest -q tests/test_data_tools.py -k graph_contract`
Expected: missing contract currently renders instead of blocking.

- [ ] **Step 3: Implement minimal integration**

After `exec`, validate every produced figure before `_graph_quality_issue`; close figures and call `_mark_graph_quality_blocked` on failure.

- [ ] **Step 4: Update legacy success fixtures**

Add a minimal valid `kind="generic"` contract to existing `run_graph` success tests; keep quality-failure tests focused on their original invariant.

- [ ] **Step 5: Run GREEN and commit**

Run: `pytest -q tests/test_data_tools.py tests/test_graph_contracts.py`
Expected: PASS.

```bash
git add tools/data_tools.py tests/test_data_tools.py tests/test_graph_contracts.py
git commit -m "feat(graphs): enforce contracts before rendering"
```

### Task 4: Production rules for the agent

**Files:**
- Modify: `agents/skills/graph_writer.md`
- Modify: `agents/copepod_system_prompt.py`
- Modify: `tests/test_agent_factory.py`

**Interfaces:**
- Every visual code block defines `graph_contract` before completing.
- Artists referenced by mappings receive stable `gid` values.

- [ ] **Step 1: Write failing prompt/skill tests**

Assert the prompt and skill contain the mandatory contract fields, the depth-only inversion rule, hollow-zero rule, independent environmental panels, and Cartopy mapping gids.

- [ ] **Step 2: Run RED**

Run: `pytest -q tests/test_agent_factory.py -k graph_contract`
Expected: FAIL because rules are absent.

- [ ] **Step 3: Add concise routing and writer rules**

Document exact dictionaries for `generic`, `vertical_profile`, `environment_relationships`, `temperature_salinity`, and `abundance_environment_map` without adding biological interpretation.

- [ ] **Step 4: Run GREEN and commit**

Run: `pytest -q tests/test_agent_factory.py tests/test_data_tools.py tests/test_graph_contracts.py`
Expected: PASS.

```bash
git add agents/skills/graph_writer.md agents/copepod_system_prompt.py tests/test_agent_factory.py
git commit -m "feat(graphs): require executable graph declarations"
```

### Task 5: Régression et curl agent

**Files:**
- Add fixtures only if the live curl scenario needs deterministic local data.

**Interfaces:**
- `/v1/chat/completions` remains unchanged.

- [ ] **Step 1: Run complete regression**

Run: `pytest -q tests/`
Expected: all non-optional tests PASS; only documented live/PostgreSQL tests skip.

- [ ] **Step 2: Curl vertical/environment figure**

Load deterministic canonical data, request a vertical profile plus three environmental relations, and verify only the depth axis is inverted and each relation is independent.

- [ ] **Step 3: Curl T–S figure**

Request size=ind./L, colour=depth, station distinction and hollow zeros; verify returned image and contract audit.

- [ ] **Step 4: Curl abundance/environment map**

Request Cartopy map with abundance size and environmental colour; verify image, projection and both legends.

- [ ] **Step 5: Final commit if curl fixtures changed**

```bash
git add tests/fixtures
git commit -m "test(graphs): add executable contract curl fixtures"
```
