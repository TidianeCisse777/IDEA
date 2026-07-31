# Bio-ORACLE Guided DataFrame Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Enrich every row of a loaded DataFrame with explicitly selected, validated Bio-ORACLE values and per-selection provenance.

**Architecture:** Add a pure catalogue that resolves French choices against the ERDDAP index. Make the Bio-ORACLE matcher consume resolved descriptors rather than building dataset IDs and value-column names. Keep the shared point-enrichment shell unchanged because it owns row preservation, deduplication and remapping.

**Tech Stack:** Python 3, pandas, requests, ERDDAP JSON/CSV, LangChain tools, pytest.

## Global Constraints

- The canonical route is enrich_with_bio_oracle; it preserves every input row, order and source column and never aggregates or filters it by zone.
- variables, scenarios, depth_layer and statistic are mandatory; every SSP also requires an available target_year. A missing choice makes no remote request.
- The agent proposes the copépodes selection but never applies it implicitly.
- Never interpret the enriched values biologically. Preserve selected dataset, time, actual grid coordinates and match status.
- Keep confirmation for expensive requests and do not expose credentials.
- Follow TDD and make one coherent commit per completed task.

---

## File structure

| File | Responsibility |
|---|---|
| core/bio_oracle_catalog.py | French labels/aliases, index parsing and selection resolver. |
| core/bio_oracle_client.py | Cached ERDDAP index access and descriptor-based CSV requests. |
| tools/bio_oracle_sources.py | Canonical argument guards, matcher and persisted result method block. |
| tests/test_bio_oracle_catalog.py | Catalogue parsing, alias and availability tests. |
| tests/test_bio_oracle_client.py | Descriptor-based ERDDAP request tests. |
| tests/test_bio_oracle_sources.py | Canonical row-preservation, guard and provenance tests. |
| agents/skills/bio_oracle_query.md | Guided user-selection workflow. |
| agents/copepod_system_prompt.py | Compact permanent explicit-selection rule. |
| CONTEXT.md, TOOLS.md | Public tool contract. |

## Task 1: Create the pure Bio-ORACLE catalogue

**Files:**
- Create: core/bio_oracle_catalog.py
- Create: tests/test_bio_oracle_catalog.py

**Interfaces:**
- Consumes: ERDDAP index rows with Dataset ID, Title and Summary.
- Produces: BioOracleSelection, BioOracleDataset, COPEPODES_PROPOSAL, parse_erddap_index(payload) and resolve_selection(selection, datasets).

- [ ] **Step 1: Write the failing tests**

~~~python
from core.bio_oracle_catalog import (
    COPEPODES_PROPOSAL, BioOracleSelection, parse_erddap_index, resolve_selection,
)

def test_resolve_selection_returns_exact_dataset_and_value_column():
    datasets = parse_erddap_index(_index_payload(
        "thetao_ssp245_2020_2100_depthsurf", "thetao_mean"
    ))
    result = resolve_selection(
        BioOracleSelection("température", "SSP2-4.5", 2050, "surface", "mean"),
        datasets,
    )
    assert result.dataset_id == "thetao_ssp245_2020_2100_depthsurf"
    assert result.value_column == "thetao_mean"

def test_resolve_selection_rejects_unavailable_statistic():
    datasets = parse_erddap_index(_index_payload(
        "par_mean_baseline_2000_2020_depthsurf", "par_mean"
    ))
    with pytest.raises(ValueError, match="statistique"):
        resolve_selection(
            BioOracleSelection("rayonnement", "baseline", None, "surface", "max"),
            datasets,
        )

def test_copepodes_proposal_is_a_non_empty_catalogue_subset():
    assert {"temperature", "phosphate", "phytoplankton"} <= set(COPEPODES_PROPOSAL)
~~~

- [ ] **Step 2: Run the test file and confirm it fails**

Run: pytest tests/test_bio_oracle_catalog.py -v

Expected: FAIL because the catalogue module does not exist.

- [ ] **Step 3: Implement the catalogue**

~~~python
@dataclass(frozen=True)
class BioOracleSelection:
    variable: str
    scenario: str
    target_year: int | None
    depth_layer: str
    statistic: str

@dataclass(frozen=True)
class BioOracleDataset:
    dataset_id: str
    variable_id: str
    scenario_id: str
    depth_id: str
    value_column: str
    available_years: tuple[int, ...]

def resolve_selection(
    selection: BioOracleSelection, datasets: Sequence[BioOracleDataset]
) -> BioOracleDataset:
    """Resolve an explicit valid user choice or raise a French ValueError."""
~~~

Define labels and aliases for all 19 current environmental identifiers: thetao, so, sws, swd, no3, po4, si, o2, dfe, ph, chl, phyc, mlotst, par, kdpar, sithick, siconc, clt and tas. Parse normal datasets such as thetao_..._depthsurf and single-statistic datasets such as par_mean_...; never manufacture a value-column name.

- [ ] **Step 4: Run the unit tests**

Run: pytest tests/test_bio_oracle_catalog.py -v

Expected: PASS.

- [ ] **Step 5: Commit**

~~~bash
git add core/bio_oracle_catalog.py tests/test_bio_oracle_catalog.py
git commit -m "feat: add Bio-ORACLE selection catalogue"
~~~

## Task 2: Resolve descriptors from ERDDAP and fetch an explicit statistic

**Files:**
- Modify: core/bio_oracle_client.py:14-177
- Modify: tests/test_bio_oracle_client.py:1-217

**Interfaces:**
- Consumes: BioOracleSelection and the ERDDAP griddap index.
- Produces: get_bio_oracle_catalog() and preview_bio_oracle_point(parameters) with dataset_id, value_column, time, latitude, longitude and value.

- [ ] **Step 1: Write failing descriptor/request tests**

~~~python
def test_preview_requests_the_resolved_statistic_column():
    with patch("core.bio_oracle_client.get_bio_oracle_catalog", return_value=_catalog_for("thetao_max")), \
         patch("core.bio_oracle_client.requests.get", return_value=_csv("thetao_max", 12.3)) as get:
        result = preview_bio_oracle_point({
            "latitude": 50.2, "longitude": -65.8, "variable": "temperature",
            "scenario": "SSP2-4.5", "target_year": 2050,
            "depth_layer": "surface", "statistic": "max",
        })
    assert ".csv?thetao_max[(2050-01-01T00:00:00Z)]" in get.call_args.args[0]
    assert result["value_column"] == "thetao_max"

def test_preview_does_not_call_csv_when_catalogue_rejects_selection():
    with patch("core.bio_oracle_client.get_bio_oracle_catalog", return_value=()), \
         patch("core.bio_oracle_client.requests.get") as get:
        with pytest.raises(ValueError, match="indisponible"):
            preview_bio_oracle_point(_valid_parameters())
    get.assert_not_called()
~~~

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: pytest tests/test_bio_oracle_client.py -v

Expected: FAIL because the client assumes a derived variable_mean name and has no catalogue resolver.

- [ ] **Step 3: Implement descriptor-based I/O**

Fetch the griddap index with a 30-second timeout and cache parsed descriptors through core.erddap_cache under a versioned bio_oracle_catalog key. Reuse the cache before contacting ERDDAP. Change _find_dataset_id into a compatibility wrapper for legacy callers. Make point and bbox fetches receive a resolved descriptor and request descriptor.value_column exactly.

- [ ] **Step 4: Run client and compatibility tests**

Run: pytest tests/test_bio_oracle_client.py tests/test_bio_oracle_sources.py -v

Expected: PASS after updating existing tests to include statistic="mean" where they directly use the new canonical client path.

- [ ] **Step 5: Commit**

~~~bash
git add core/bio_oracle_client.py tests/test_bio_oracle_client.py tests/test_bio_oracle_sources.py
git commit -m "feat: resolve Bio-ORACLE values from catalogued datasets"
~~~

## Task 3: Enforce the canonical tool contract and record grid provenance

**Files:**
- Modify: tools/bio_oracle_sources.py:83-468,1166-1275
- Modify: tests/test_bio_oracle_sources.py:935-1527

**Interfaces:**
- Consumes: variables, scenarios, target_year, depth_layer, statistic and a source DataFrame.
- Produces: a persisted df_bio_oracle_enriched_* with a value column and dataset, time, grid latitude and grid longitude columns per selection.

- [ ] **Step 1: Add failing canonical-path tests**

~~~python
@pytest.mark.parametrize("arguments, label", [
    ({"scenarios": ["baseline"], "depth_layer": "surface", "statistic": "mean"}, "variables"),
    ({"variables": ["temperature"], "depth_layer": "surface", "statistic": "mean"}, "scénarios"),
    ({"variables": ["temperature"], "scenarios": ["baseline"], "statistic": "mean"}, "couche"),
    ({"variables": ["temperature"], "scenarios": ["baseline"], "depth_layer": "surface"}, "statistique"),
])
def test_canonical_enrichment_requires_explicit_selections_without_http(arguments, label):
    with patch("tools.bio_oracle_sources._fetch_bio_oracle_bbox") as fetch:
        result = _enrich_tool("thread-contract").invoke(arguments)
    assert label in result.lower()
    fetch.assert_not_called()

def test_canonical_enrichment_keeps_rows_and_records_grid_provenance():
    _enrich_tool("thread-provenance").invoke(_explicit_baseline_mean())
    enriched = _latest_enriched("thread-provenance")
    assert len(enriched) == 3
    assert list(enriched["sample_id"]) == ["a", "b", "c"]
    assert "bio_oracle_temperature_baseline_surface_mean_grid_latitude" in enriched
~~~

- [ ] **Step 2: Run the test selection and confirm failure**

Run: pytest tests/test_bio_oracle_sources.py -k 'explicit_selections or grid_provenance' -v

Expected: FAIL because the tool currently supplies variables, baseline and surface defaults and records no actual grid coordinates.

- [ ] **Step 3: Implement canonical validation and matching**

Require all four selection fields with no defaults. Validate them before constructing BioOracleMatcher or resolving source coordinates. For every SSP, require target_year and let the catalogue reject unavailable years. Keep source_variable, explicit coordinate columns, confirmation, coordinate binning and worker limit.

Replace matcher cache keys with resolved descriptor keys. Return the selected grid cell latitude and longitude from _lookup_in_tile and persist them. Use column stubs such as bio_oracle_temperature_ssp2_4_5_2050_surface_max. Baseline has no fictional target year.

Do not pass zone_name or date_range to run_point_enrichment from this canonical tool: they would remove input rows and violate the approved contract.

- [ ] **Step 4: Run focused and adjacent tests**

Run: pytest tests/test_bio_oracle_sources.py tests/test_point_enrichment.py -v

Expected: PASS. Confirm every canonical success preserves row count, order and source columns, including invalid or terrestrial coordinates.

- [ ] **Step 5: Commit**

~~~bash
git add tools/bio_oracle_sources.py tests/test_bio_oracle_sources.py
git commit -m "feat: require explicit Bio-ORACLE enrichment selections"
~~~

## Task 4: Make the agent propose choices before it calls the tool

**Files:**
- Modify: agents/skills/bio_oracle_query.md:20-49
- Modify: agents/copepod_system_prompt.py:48-50
- Modify: CONTEXT.md:50,99-101
- Modify: TOOLS.md:204-217
- Modify: tests/test_bio_oracle_sources.py:1377-1384
- Modify: tests/test_agent_source_enrichment_eval.py

**Interfaces:**
- Consumes: an explicit request to enrich a loaded table with Bio-ORACLE.
- Produces: an assistant proposal of copépodes and catalogue values, then a canonical call only after the user supplies every required choice.

- [ ] **Step 1: Write failing behavioural tests**

~~~python
def test_bio_oracle_skill_requires_user_selection_before_tool_call():
    skill = Path("agents/skills/bio_oracle_query.md").read_text(encoding="utf-8")
    assert "propose" in skill.lower()
    assert "attend la sélection" in skill.lower()
    assert "ne l'applique jamais" in skill.lower()

def test_agent_enrichment_eval_defers_tool_call_when_selection_is_absent():
    assert expected_tool_calls("Enrichis mon fichier avec Bio-ORACLE") == []
~~~

- [ ] **Step 2: Run the behavioural tests and confirm failure**

Run: pytest tests/test_bio_oracle_sources.py -k skill tests/test_agent_source_enrichment_eval.py -v

Expected: FAIL because the skill currently instructs an immediate canonical call using defaults.

- [ ] **Step 3: Update the tool description and guidance**

State in the enrich_with_bio_oracle docstring, skill and compact system prompt: propose choices first; wait for variables, scenarios, SSP year, vertical layer and statistic; never invoke the tool with inferred defaults. Include the copépodes proposal and a full-catalogue option. Update CONTEXT.md and TOOLS.md to describe the strict row-preserving contract, not zone filtering.

- [ ] **Step 4: Run agent and routing regressions**

Run: pytest tests/test_bio_oracle_sources.py tests/test_agent_source_enrichment_eval.py tests/test_tool_exposure.py tests/test_source_scope.py -v

Expected: PASS; the canonical tool is still visible only for explicit Bio-ORACLE enrichment of a loaded file.

- [ ] **Step 5: Commit**

~~~bash
git add agents/skills/bio_oracle_query.md agents/copepod_system_prompt.py CONTEXT.md TOOLS.md \
  tests/test_bio_oracle_sources.py tests/test_agent_source_enrichment_eval.py
git commit -m "docs: guide explicit Bio-ORACLE enrichment choices"
~~~

## Task 5: Verify partial failures and align the RAG reference

**Files:**
- Modify if required: core/copepod_rag/docs/jointures_environnementales.md
- Regenerate if modified: core/copepod_rag/chunks.json
- Modify: tests/test_bio_oracle_sources.py

**Interfaces:**
- Consumes: completed catalogue, client, canonical tool and guidance.
- Produces: a green focused suite and RAG documentation aligned with the public contract.

- [ ] **Step 1: Write the partial-failure regression**

~~~python
def test_canonical_enrichment_persists_partial_results_with_statuses():
    with patch(
        "tools.bio_oracle_sources._fetch_bio_oracle_bbox",
        side_effect=[_tile(3.2), requests.Timeout()],
    ):
        result = _enrich_tool("thread-partial").invoke(_two_explicit_selections())
    enriched = _latest_enriched("thread-partial")
    assert "matched" in set(enriched["bio_oracle_match_status"])
    assert "no_value" in set(enriched["bio_oracle_match_status"])
    assert "no_value" in result.lower()
~~~

- [ ] **Step 2: Run it and confirm the desired diagnostic**

Run: pytest tests/test_bio_oracle_sources.py -k partial -v

Expected: PASS after Task 3; otherwise repair only the matcher error-to-status propagation before continuing.

- [ ] **Step 3: Align RAG only if its public contract differs**

Document explicit selections, row preservation, surface/benthic layers and statistic provenance in core/copepod_rag/docs/jointures_environnementales.md. If that source was modified, run:

~~~bash
python core/copepod_rag/build_index.py
~~~

- [ ] **Step 4: Run complete relevant verification**

Run: pytest tests/test_bio_oracle_catalog.py tests/test_bio_oracle_client.py tests/test_bio_oracle_sources.py tests/test_point_enrichment.py tests/test_tool_exposure.py tests/test_source_scope.py tests/test_agent_source_enrichment_eval.py -v

Expected: PASS.

- [ ] **Step 5: Commit the final documentation/index change if one was needed**

~~~bash
git add core/copepod_rag/docs/jointures_environnementales.md core/copepod_rag/chunks.json
git commit -m "docs: align RAG with Bio-ORACLE enrichment contract"
~~~
