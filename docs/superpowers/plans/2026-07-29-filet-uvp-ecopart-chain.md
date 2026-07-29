# Chaîne filet–UVP–EcoPart certifiée Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produire un DataFrame persistant de données filet et UVP enrichies EcoPart, reliées uniquement par des correspondances CTD certifiées.

**Architecture:** L’audit publie une sélection EcoTaxa des seuls `uvp_sample_id` certifiés. L’export multi-projets existant la consomme. L’enrichissement EcoPart partitionne ensuite la campagne par `export_project_id`, et une jointure locale s’appuie seulement sur l’audit certifié.

**Tech Stack:** Python, pandas, LangChain `@tool`, session store, pytest.

## Global Constraints

- Français par défaut ; aucune interprétation biologique ni valeur inventée.
- `join_eligible=True` après validation du fichier CTD Amundsen est l’unique droit de jointure filet–UVP.
- L’audit accepte un DataFrame filet persistant par `net_variable_name`; les filtres zone et année restent des étapes séparées.
- Les téléchargements EcoTaxa et EcoPart conservent leurs confirmations distinctes.
- EcoPart se joint par profil/sample et bin de 5 m ; les bins zéro échantillonnés et les volumes réels sont préservés.
- Toute sortie multi-projets porte les IDs EcoTaxa et EcoPart, la couverture et la provenance.

---

## Audit de l’existant

| Élément | État | Lacune |
|---|---|---|
| Sous-sélection filet | `find_uvp_matches_for_net_table(net_variable_name=...)` accepte déjà une table dérivée et `date_from/date_to`. | La réponse ne crée pas de chemin explicite vers l’export. |
| Certificat | `df_net_uvp_matches` contient le match spatial/temporel et le contrôle CTD Amundsen ; `join_eligible` est strict. | Aucune sélection EcoTaxa exportable ne contient les seuls samples certifiés. |
| Export | `export_ecotaxa_samples` groupe déjà les sample IDs par projet et crée une campagne avec `export_project_id`. | Il n’est pas alimenté par l’audit et ne garde pas son pont détaillé. |
| EcoPart | Le résolveur priorise le lien serveur, puis joint les objets par bin de 5 m. | `enrich_ecotaxa_with_ecopart_remote` ne traite qu’un couple de projets. |
| Table finale | `core/net_uvp_comparison.py` offre le matching et la comparaison ; le skill emploie du pandas manuel. | Aucun tool ne crée la table filet–UVP enrichie depuis les IDs certifiés. |
| Routage | L’audit appartient déjà à `file_analysis`. | Le nouveau tool doit être visible dans ce groupe. |

Baseline du 2026-07-29 : la suite ciblée retourne **134 réussites et 5 échecs**. Les échecs sont des attentes obsolètes sur les textes de skills EcoTaxa et de contrat cache, hors périmètre du flux visé. Ne pas les masquer.

## Fichiers

- `tools/copepod_sources.py` : sélection certifiée et tool de jointure locale.
- `core/net_uvp_comparison.py` : fonction pure de pont certifié.
- `tools/ecopart_sources.py` : enrichissement distant de campagne multi-projets.
- `tools/tool_catalog.py`, `tools/tool_exposure.py`, `agents/copepod_system_prompt.py` : registre et routage.
- `agents/skills/net_uvp_abundance_comparison.md`, `docs/features/ENRICHMENT_ECOTAXA_ECOPART.md`, `TOOLS.md` : documentation.
- `tests/test_copepod_sources.py`, `tests/test_net_uvp_comparison.py`, `tests/test_ecopart_sources.py`, `tests/test_enrichment_workflows_integration.py` : couverture.

### Task 1: Publier une sélection issue de l’audit

**Files:**
- Modify: `tools/copepod_sources.py:480-825, 860-990`
- Test: `tests/test_copepod_sources.py:1889-1990`

**Interfaces:**
- Produces: `selection:<name>` avec `sample_ids`, `project_ids`, `source="net_uvp_certified_selection"`, `audit_variable`, `net_variable_name`, et les bornes temporelles.

- [ ] **Step 1: Write the failing tests**

```python
def test_audit_publishes_only_ctd_certified_selection(...):
    result = tool.invoke({"net_variable_name": "df_file_baffin_2024"})
    name = _selection_name_from(result)
    meta = store.get(f"{thread_id}:selection:{name}")["meta"]
    assert meta["sample_ids"] == [101, 203]
    assert meta["project_ids"] == [10, 20]
    assert meta["source"] == "net_uvp_certified_selection"

def test_audit_without_ctd_certificate_creates_no_selection(...):
    tool.invoke({"net_variable_name": "df_file_baffin_2024"})
    assert not any(":selection:net_uvp_certified_" in key for key in store.keys(thread_id))
```

- [ ] **Step 2: Run the tests (RED)**

Run: `pytest tests/test_copepod_sources.py -k 'audit_publishes or audit_without_ctd' -v`

Expected: FAIL because the audit stores only `df_net_uvp_matches`.

- [ ] **Step 3: Implement the minimal selection**

Filter `matches` with `join_eligible`, deduplicate `uvp_project_id, uvp_sample_id`, generate a deterministic `net_uvp_certified_<source>_<digest>` name, then extend `_store_sample_selection` to accept custom source and metadata. Persist no selection on empty certification or unavailable Amundsen.

- [ ] **Step 4: Run the tests (GREEN)**

Run: `pytest tests/test_copepod_sources.py -k 'net_uvp' -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/copepod_sources.py tests/test_copepod_sources.py
git commit -m "feat: publish certified UVP selections from net audits"
```

### Task 2: Créer le pont pur certifié

**Files:**
- Modify: `core/net_uvp_comparison.py`
- Test: `tests/test_net_uvp_comparison.py`

**Interfaces:**
- Produces: `join_certified_net_uvp_enriched(net_df, audit_df, uvp_enriched_df) -> pd.DataFrame`.

- [ ] **Step 1: Write the failing tests**

```python
def test_certified_join_uses_project_and_profile_keys():
    out = join_certified_net_uvp_enriched(net, audit, enriched)
    assert set(out["uvp_sample_id"]) == {10}
    assert out["ctd_filename_join_eligible"].all()

def test_certified_join_excludes_uncertified_audit_rows():
    assert join_certified_net_uvp_enriched(net, audit.assign(join_eligible=False), enriched).empty
```

- [ ] **Step 2: Run the tests (RED)**

Run: `pytest tests/test_net_uvp_comparison.py -k certified_join -v`

Expected: FAIL because the function does not exist.

- [ ] **Step 3: Implement the bridge**

Normalize net sample IDs, retain and deduplicate only certified audit rows, derive an exported UVP profile key in priority order `sample_profileid`, then `sample_id` / `obj_orig_id` stripped of their object suffix. Merge with the composite key `(uvp_project_id, uvp_profile_str)` ↔ `(export_project_id, uvp_profile_str)`. Raise `ValueError` for absent or ambiguous profile keys.

- [ ] **Step 4: Run the tests (GREEN)**

Run: `pytest tests/test_net_uvp_comparison.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/net_uvp_comparison.py tests/test_net_uvp_comparison.py
git commit -m "feat: add certified net UVP enriched join helper"
```

### Task 3: Exposer la jointure locale

**Files:**
- Modify: `tools/copepod_sources.py`, `tools/tool_catalog.py`, `tools/tool_exposure.py`, `agents/copepod_system_prompt.py`
- Test: `tests/test_copepod_sources.py`, `tests/test_tool_catalog.py`, `tests/test_tool_exposure.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_join_net_uvp_enriched_persists_certified_object_rows(...):
    tool.invoke({"net_variable_name": "df_file_baffin_2024",
                 "uvp_enriched_variable": "df_ecotaxa_ecopart_campaign"})
    out = store.get(f"{thread_id}:dataset:df_net_uvp_ecopart")["df"]
    assert out["join_eligible"].all()
    assert "ecopart_Sampled volume [L]" in out

def test_join_net_uvp_enriched_is_exposed_for_file_analysis(...):
    assert "join_net_uvp_enriched" in decision.tool_names
```

- [ ] **Step 2: Run the tests (RED)**

Run: `pytest tests/test_copepod_sources.py tests/test_tool_catalog.py tests/test_tool_exposure.py -k net_uvp_enriched -v`

Expected: FAIL because the tool is unregistered.

- [ ] **Step 3: Implement and register**

Add `join_net_uvp_enriched(net_variable_name, uvp_enriched_variable, audit_variable_name="df_net_uvp_matches")` around the pure helper. Persist `df_net_uvp_ecopart` with source `net_uvp_ecopart_certified`. Register it as low-risk, local-session, `file_analysis`; update the prompt to require the prior audit.

- [ ] **Step 4: Run the tests (GREEN)**

Run: `pytest tests/test_copepod_sources.py tests/test_tool_catalog.py tests/test_tool_exposure.py -k 'net_uvp_enriched or file_analysis' -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/copepod_sources.py tools/tool_catalog.py tools/tool_exposure.py agents/copepod_system_prompt.py tests/test_copepod_sources.py tests/test_tool_catalog.py tests/test_tool_exposure.py
git commit -m "feat: expose certified net UVP join tool"
```

### Task 4: Enrichir les campagnes EcoTaxa par projet

**Files:**
- Modify: `tools/ecopart_sources.py:47-390, 780-970`
- Test: `tests/test_ecopart_sources.py`, `tests/test_enrichment_workflows_integration.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_remote_enrichment_partitions_campaign_by_ecotaxa_project(...):
    enrich.invoke({"confirmed": True})
    out = store.get(f"{thread_id}:ecotaxa_ecopart")["df"]
    assert set(out["export_project_id"]) == {101, 202}
    assert set(out["ecopart_project_id"]) == {301, 302}

def test_remote_enrichment_reports_a_failed_campaign_partition(...):
    result = enrich.invoke({"confirmed": True})
    assert "partiel" in result.lower()
```

- [ ] **Step 2: Run the tests (RED)**

Run: `pytest tests/test_ecopart_sources.py tests/test_enrichment_workflows_integration.py -k 'campaign or partition' -v`

Expected: FAIL because the remote tool resolves one EcoPart project.

- [ ] **Step 3: Implement partitioned enrichment**

Detect a campaign via `export_project_id`; partition it by project; resolve, dry-run, download and join every partition independently; annotate each successful row with `ecopart_project_id`; concatenate successful partitions and return per-project failures as explicit partial coverage. Preserve the existing local and mono-project pathways.

- [ ] **Step 4: Run the tests (GREEN)**

Run: `pytest tests/test_ecopart_sources.py tests/test_enrichment_workflows_integration.py -v`

Expected: new tests PASS; report the recorded unrelated baseline failures if still present.

- [ ] **Step 5: Commit**

```bash
git add tools/ecopart_sources.py tests/test_ecopart_sources.py tests/test_enrichment_workflows_integration.py
git commit -m "feat: enrich EcoTaxa campaigns with EcoPart per project"
```

### Task 5: Finaliser la documentation et l’E2E

**Files:**
- Modify: `agents/skills/net_uvp_abundance_comparison.md`, `docs/features/ENRICHMENT_ECOTAXA_ECOPART.md`, `TOOLS.md`, `tests/test_net_uvp_pipeline_e2e.py`, `tests/test_agent_factory.py`

- [ ] **Step 1: Write the failing tests**

Add an E2E whose audit has `join_eligible=True`, `ctd_filename_match_status="matched"`, project IDs and profile keys; assert no `spatial_only` row reaches the final dataframe. Add a prompt assertion for the certified selection and final join tool.

- [ ] **Step 2: Run the tests (RED)**

Run: `pytest tests/test_net_uvp_pipeline_e2e.py tests/test_agent_factory.py -k 'certified or net_uvp' -v`

Expected: FAIL because the current E2E fabricates an uncertified manual bridge.

- [ ] **Step 3: Update docs and E2E**

Document: sous-sélection filet → audit CTD → sélection exportable → confirmation EcoTaxa → confirmation EcoPart multi-projets → jointure locale → table canonique. Add the local tool to `TOOLS.md`; replace the manual pandas bridge in the skill.

- [ ] **Step 4: Run verification**

Run: `pytest -q tests/test_net_uvp_comparison.py tests/test_ctd_filename_match.py tests/test_copepod_sources.py tests/test_ecopart_sources.py tests/test_enrichment_workflows_integration.py tests/test_net_uvp_pipeline_e2e.py tests/test_tool_catalog.py tests/test_tool_exposure.py tests/test_agent_factory.py`

Expected: all new tests PASS; classify remaining failures against the recorded five-test baseline.

- [ ] **Step 5: Commit**

```bash
git add agents/skills/net_uvp_abundance_comparison.md docs/features/ENRICHMENT_ECOTAXA_ECOPART.md TOOLS.md tests/test_net_uvp_pipeline_e2e.py tests/test_agent_factory.py
git commit -m "docs: document certified net UVP EcoPart workflow"
```

## Plan self-review

Every requirement from the approved design maps to a task: certified selection (1), strict bridge (2), runtime tool exposure (3), multi-project EcoPart (4), and user-facing workflow plus regression coverage (5). The sole final key is project plus UVP profile, so campaigns cannot collide. The final tool creates no scientific metric; later calculations continue through the canonical sample-depth contracts.
