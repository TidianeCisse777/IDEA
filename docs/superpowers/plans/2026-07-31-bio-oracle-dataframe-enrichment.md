# Bio-ORACLE DataFrame Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the canonical Bio-ORACLE DataFrame enrichment guided, explicit, catalog-driven, statistically selectable, and row-preserving.

**Architecture:** Add a declarative catalog in `core` for friendly variables, ERDDAP identifiers, layers, scenarios, units, and statistics. Make the canonical matcher validate a complete selection before any network I/O, then include the selected statistic in tile requests, cache keys, output columns, and provenance. Keep legacy point/zone/coupling tools registered for compatibility but out of the canonical behavior.

**Tech Stack:** Python 3, pandas, requests, LangChain `@tool`, pytest, existing `run_point_enrichment`, ERDDAP tile cache.

## Global Constraints

- Preserve DataFrame grain: every input row remains one output row; no zone aggregation.
- No implicit variable, scenario, layer, year, or statistic may trigger remote I/O.
- All numeric values must come from Bio-ORACLE/ERDDAP or existing test fixtures; no scientific interpretation.
- Preserve source rows and add per-selection provenance and per-row match status.
- Use the source-selection gateway and canonical `enrich_with_bio_oracle` path only for this feature.
- Keep credentials out of code, logs, docstrings, tests, and commits.

---

### Task 1: Add the Bio-ORACLE catalog and validation API

**Files:**
- Create: `core/bio_oracle_catalog.py`
- Create: `tests/test_bio_oracle_catalog.py`

**Interfaces:**
- `CatalogVariable` frozen dataclass with `key`, `erddap_var`, `label`, `group`, `unit`, `layers`, `statistics`, and `aliases`.
- `CATALOG_VARIABLES: tuple[CatalogVariable, ...]` containing the copépode recommendation plus the remaining supported Bio-ORACLE v3 environmental variables.
- `CATALOG_SCENARIOS` mapping friendly scenario aliases to canonical ERDDAP scenario IDs.
- `CATALOG_LAYERS` mapping `surface`, `benthic_min`, `benthic_mean`, and `benthic_max` to existing ERDDAP depth suffixes.
- `list_catalog_variables() -> list[dict]` for tool-facing choices.
- `resolve_catalog_variable(value: str) -> CatalogVariable` and `resolve_catalog_statistic(variable: CatalogVariable, value: str) -> str`, raising `ValueError` with available choices on invalid input.
- `validate_enrichment_selection(variables, scenarios, depth_layer, statistic, target_year) -> dict` returning canonical selections or a deterministic validation error.

- [ ] **Step 1: Write failing catalog tests** for the copépode recommendation, alias normalization, every layer mapping, available statistics, unknown-variable rejection, and SSP-year requirement.
- [ ] **Step 2: Run the focused tests and verify they fail** because `core.bio_oracle_catalog` does not exist.
- [ ] **Step 3: Implement the catalog and validators** with no HTTP calls; use the official ERDDAP variable IDs only as data in the registry.
- [ ] **Step 4: Run `pytest tests/test_bio_oracle_catalog.py -v`** and verify all catalog tests pass.
- [ ] **Step 5: Commit** with `git add core/bio_oracle_catalog.py tests/test_bio_oracle_catalog.py && git commit -m "feat: add Bio-ORACLE enrichment catalog"`.

### Task 2: Make tile fetches statistic-aware

**Files:**
- Modify: `tools/bio_oracle_sources.py:_fetch_bio_oracle_bbox`, `BioOracleMatcher`
- Modify: `tests/test_bio_oracle_sources.py`

**Interfaces:**
- `_fetch_bio_oracle_bbox(..., statistic: str = "mean") -> pd.DataFrame` adds `statistic` to the cache key and requests `<erddap_var>_<statistic>`.
- `BioOracleMatcher(..., statistic: str)` carries the validated statistic through unique query keys, tile grouping, fetch payloads, and diagnostics.

- [ ] **Step 1: Add failing tests** proving `max` changes the requested ERDDAP column, separates cache entries from `mean`, and appears in the enrichment output column/provenance.
- [ ] **Step 2: Run the new focused tests and verify they fail** because the fetcher hard-codes `_mean` and the matcher has no statistic field.
- [ ] **Step 3: Implement the minimal statistic plumbing** while retaining `statistic="mean"` only as an internal backward-compatible fetcher default; the canonical tool will validate explicit user selection before calling it.
- [ ] **Step 4: Run the focused Bio-ORACLE source tests** and verify existing mean behavior plus new statistics pass.
- [ ] **Step 5: Commit** with `git add tools/bio_oracle_sources.py tests/test_bio_oracle_sources.py && git commit -m "feat: support Bio-ORACLE statistics in enrichment"`.

### Task 3: Enforce guided canonical tool selection

**Files:**
- Modify: `tools/bio_oracle_sources.py:enrich_with_bio_oracle`
- Modify: `tests/test_bio_oracle_sources.py`
- Modify: `agents/skills/bio_oracle_query.md`

**Interfaces:**
- `enrich_with_bio_oracle` accepts `variables`, `scenarios`, `depth_layer`, `statistic`, `target_year`, coordinate columns, source variable, scoping, confirmation, and worker settings.
- Omitted selection fields return `_bio_blocked(...)` with a structured choice list and perform no remote I/O.

- [ ] **Step 1: Write failing tests** for omitted variables/scenarios/layer/statistic, SSP without year, invalid catalog choices, and a valid explicit selection preserving row count/order.
- [ ] **Step 2: Run each new test and verify the expected failure**: current code silently chooses seven variables, baseline, and surface and does not accept statistic.
- [ ] **Step 3: Implement preflight validation** through `validate_enrichment_selection`; remove the canonical tool’s implicit selection behavior; pass canonical variables, scenarios, layer, statistic, and year into `BioOracleMatcher`.
- [ ] **Step 4: Update the tool docstring and `bio_oracle_query.md`** to say the agent must present the catalog/presélection copépodes and wait for explicit user choices before calling the tool; state that the tool enriches the full DataFrame row-by-row and never aggregates by zone.
- [ ] **Step 5: Run `pytest tests/test_bio_oracle_sources.py -v`** and verify the canonical tests pass, updating only tests whose old expectation depended on implicit defaults.
- [ ] **Step 6: Commit** with `git add tools/bio_oracle_sources.py tests/test_bio_oracle_sources.py agents/skills/bio_oracle_query.md && git commit -m "feat: require explicit Bio-ORACLE enrichment selections"`.

### Task 4: Expose the catalog and provenance in the agent-facing contract

**Files:**
- Modify: `tools/bio_oracle_sources.py:list_bio_oracle_datasets` or a focused catalog presentation helper
- Modify: `agents/copepod_system_prompt.py`
- Modify: `TOOLS.md`
- Modify: `CONTEXT.md`
- Create: `tests/test_bio_oracle_enrichment_contract.py`

**Interfaces:**
- The agent-facing text names the guided selection sequence and points to the catalog without exposing internal tool names in user-facing result prose.
- Result method blocks report variables, scenarios, target year, layer, statistic, deduplication, matched/no-value counts, and provenance references.

- [ ] **Step 1: Write failing contract tests** for the required guided-selection language, statistic/layer/year method metadata, and absence of any implicit default list in the canonical tool description.
- [ ] **Step 2: Run the contract tests and verify they fail** against the current prompt/docs and method block.
- [ ] **Step 3: Implement the prompt, skill, inventory, and method-block updates** using the same catalog terminology and CT-AG-06 confirmation rule.
- [ ] **Step 4: Run the focused contract tests and then the full Bio-ORACLE/source-scope suite**.
- [ ] **Step 5: Commit** with `git add agents/copepod_system_prompt.py TOOLS.md CONTEXT.md tests/test_bio_oracle_enrichment_contract.py tools/bio_oracle_sources.py && git commit -m "docs: expose guided Bio-ORACLE enrichment contract"`.

### Task 5: Full verification and integration review

**Files:**
- Modify only files identified by failing regressions; do not perform unrelated refactors.

- [ ] **Step 1: Run `pytest tests/test_bio_oracle_client.py tests/test_bio_oracle_catalog.py tests/test_bio_oracle_sources.py tests/test_bio_oracle_enrichment_contract.py tests/test_source_scope.py -v`.**
- [ ] **Step 2: Run the complete `pytest tests/` suite.**
- [ ] **Step 3: Run `git diff --check` and inspect `git status --short`.**
- [ ] **Step 4: Verify no test or log contains credentials, internal credentials, or invented scientific values.**
- [ ] **Step 5: Commit any regression-only fixes** with a message naming the corrected behavior, then report the final test commands and outcomes.
