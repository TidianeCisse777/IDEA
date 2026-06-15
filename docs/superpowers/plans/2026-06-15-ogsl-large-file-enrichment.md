# OGSL Large-File Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrich large station-time biological tables with OGSL data using one remote request per unique station and deterministic local time/depth matching.

**Architecture:** Add pure planning and matching functions to `core/ogsl_enrichment.py`. Extend the OGSL client to accept station-specific windows, then let `query_ogsl` persist both the raw download and a same-cardinality enriched table. The agent supplies only column names and tolerances.

**Tech Stack:** Python 3.13, pandas, requests, LangChain tools, pytest, LangSmith code evaluators.

---

### Task 1: Station Window Planning

**Files:**
- Create: `core/ogsl_enrichment.py`
- Create: `tests/test_ogsl_enrichment.py`

- [ ] **Step 1: Write the failing station-window test**

```python
def test_build_station_windows_scales_with_unique_stations():
    import pandas as pd
    from core.ogsl_enrichment import build_station_windows

    source = pd.DataFrame({
        "station": ["02M"] * 5000 + ["05M"] * 5000,
        "sample_time": (
            ["2022-10-09T22:03:37Z"] * 2500
            + ["2022-10-10T02:03:37Z"] * 2500
            + ["2023-01-05T12:00:00Z"] * 5000
        ),
    })

    windows, parsed_time = build_station_windows(
        source,
        station_column="station",
        time_column="sample_time",
        tolerance_hours=24,
    )

    assert len(windows) == 2
    assert windows[0] == {
        "station": "02M",
        "start": "2022-10-08T22:03:37Z",
        "end": "2022-10-11T02:03:37Z",
    }
    assert parsed_time.notna().all()
```

- [ ] **Step 2: Run the test and verify RED**

Run: `pytest -q tests/test_ogsl_enrichment.py::test_build_station_windows_scales_with_unique_stations`

Expected: FAIL because `core.ogsl_enrichment` does not exist.

- [ ] **Step 3: Implement station-window planning**

Create `build_station_windows(source, station_column, time_column, tolerance_hours)`:

```python
from __future__ import annotations

import pandas as pd


def _iso_utc(value: pd.Timestamp) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_station_windows(
    source: pd.DataFrame,
    *,
    station_column: str,
    time_column: str,
    tolerance_hours: float,
) -> tuple[list[dict[str, str]], pd.Series]:
    parsed_time = pd.to_datetime(source[time_column], errors="coerce", utc=True)
    planning = pd.DataFrame({
        "station": source[station_column].astype("string").str.strip(),
        "time": parsed_time,
    })
    planning = planning[
        planning["station"].notna()
        & planning["station"].ne("")
        & planning["time"].notna()
    ]
    padding = pd.Timedelta(hours=tolerance_hours)
    windows = []
    for station, rows in planning.groupby("station", sort=False):
        windows.append({
            "station": str(station),
            "start": _iso_utc(rows["time"].min() - padding),
            "end": _iso_utc(rows["time"].max() + padding),
        })
    return windows, parsed_time
```

- [ ] **Step 4: Run the test and verify GREEN**

Run: `pytest -q tests/test_ogsl_enrichment.py::test_build_station_windows_scales_with_unique_stations`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/ogsl_enrichment.py tests/test_ogsl_enrichment.py
git commit -m "feat(ogsl): plan station-specific query windows"
```

### Task 2: Deterministic Time And Depth Matching

**Files:**
- Modify: `core/ogsl_enrichment.py`
- Modify: `tests/test_ogsl_enrichment.py`

- [ ] **Step 1: Write failing matching tests**

Add tests covering:

```python
def test_enrich_ogsl_uses_nearest_time_and_pressure():
    source = pd.DataFrame([{
        "station": "02M",
        "sample_time": "2022-10-09T22:04:00Z",
        "depth": 8.0,
        "abundance": 120,
    }])
    ogsl = pd.DataFrame([
        {
            "stationID": "02M",
            "time": "2022-10-09T22:03:37Z",
            "PRES": 1.0,
            "TE90": 4.75,
            "cruiseID": "cruise-a",
            "cast_number": 4,
        },
        {
            "stationID": "02M",
            "time": "2022-10-09T22:03:37Z",
            "PRES": 8.0,
            "TE90": 4.20,
            "cruiseID": "cruise-a",
            "cast_number": 4,
        },
    ])

    result = enrich_with_ogsl(
        source,
        ogsl,
        station_column="station",
        time_column="sample_time",
        depth_column="depth",
        variables=["PRES", "TE90"],
        time_tolerance_hours=24,
        depth_tolerance_m=10,
    )

    assert result["ogsl_te90"].tolist() == [4.20]
    assert result["ogsl_time_delta_min"].iloc[0] == pytest.approx(23 / 60)
    assert result["ogsl_depth_delta_m"].tolist() == [0.0]
    assert result["ogsl_match_status"].tolist() == ["matched"]
```

```python
def test_enrich_ogsl_uses_surface_when_depth_is_absent():
    result = enrich_with_ogsl(
        source_without_depth,
        ogsl_with_multiple_pressures,
        station_column="station",
        time_column="sample_time",
        depth_column=None,
        variables=["PRES", "TE90"],
        time_tolerance_hours=24,
        depth_tolerance_m=10,
    )
    assert result["ogsl_pres"].tolist() == [1.0]
```

```python
def test_enrich_ogsl_preserves_invalid_and_unmatched_rows():
    assert result["ogsl_match_status"].tolist() == [
        "missing_station",
        "invalid_time",
        "no_match",
        "missing_depth",
    ]
    assert len(result) == len(source)
    assert list(result.index) == list(source.index)
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `pytest -q tests/test_ogsl_enrichment.py -k 'nearest or surface or unmatched'`

Expected: FAIL because `enrich_with_ogsl` is absent.

- [ ] **Step 3: Implement pure matching**

Implement `enrich_with_ogsl(...)` with these rules:

1. Copy the source deeply and add a stable `_ogsl_source_order`.
2. Parse source and OGSL timestamps as UTC.
3. Normalize station IDs to stripped strings.
4. For each valid source row, restrict candidates to the same station.
5. Find the minimum absolute cast-time delta.
6. Reject when the delta exceeds `time_tolerance_hours`.
7. Restrict to the nearest cast timestamp.
8. With depth, select minimum absolute `PRES - depth`; reject above
   `depth_tolerance_m`.
9. Without depth, select minimum `PRES`.
10. Prefix selected OGSL variable columns with `ogsl_`.
11. Restore source order and original index.

Use explicit status assignment before candidate selection:

```python
status = "matched"
if station_missing:
    status = "missing_station"
elif raw_time_missing:
    status = "missing_time"
elif parsed_time_missing:
    status = "invalid_time"
elif depth_column and raw_depth_missing:
    status = "missing_depth"
elif depth_column and parsed_depth_missing:
    status = "invalid_depth"
elif no_candidate_within_tolerances:
    status = "no_match"
```

- [ ] **Step 4: Run all matching tests**

Run: `pytest -q tests/test_ogsl_enrichment.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/ogsl_enrichment.py tests/test_ogsl_enrichment.py
git commit -m "feat(ogsl): match large files by time and depth"
```

### Task 3: Station-Specific OGSL Client Requests

**Files:**
- Modify: `core/ogsl_client.py`
- Modify: `tests/test_ogsl_client.py`

- [ ] **Step 1: Write a failing client test**

```python
def test_query_ogsl_uses_station_specific_windows(tmp_path):
    windows = [
        {
            "station": "02M",
            "start": "2022-10-08T22:00:00Z",
            "end": "2022-10-10T22:00:00Z",
        },
        {
            "station": "05M",
            "start": "2023-01-04T12:00:00Z",
            "end": "2023-01-06T12:00:00Z",
        },
    ]
    query_ogsl(
        {"station_windows": windows, "variables": ["PRES", "TE90"]},
        output_path=tmp_path / "ogsl.csv",
    )
    assert "time>=2022-10-08T22%3A00%3A00Z" in first_url
    assert "time>=2023-01-04T12%3A00%3A00Z" in second_url
```

- [ ] **Step 2: Run the test and verify RED**

Run: `pytest -q tests/test_ogsl_client.py::test_query_ogsl_uses_station_specific_windows`

Expected: FAIL because the client ignores `station_windows`.

- [ ] **Step 3: Extend the client**

Replace the flat station loop with:

```python
station_windows = list(parameters.get("station_windows") or [])
if not station_windows:
    station_windows = [
        {
            "station": station,
            "start": parameters.get("start"),
            "end": parameters.get("end"),
        }
        for station in dict.fromkeys(stations)
    ]

for window in station_windows:
    response = requests.get(
        _query_url(
            station=window["station"],
            variables=variables,
            start=window.get("start"),
            end=window.get("end"),
        ),
        timeout=30,
    )
```

Validate that every window has a non-empty `station`.

- [ ] **Step 4: Run client tests**

Run: `pytest -q tests/test_ogsl_client.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/ogsl_client.py tests/test_ogsl_client.py
git commit -m "feat(ogsl): query station-specific time windows"
```

### Task 4: Tool Orchestration And Persistence

**Files:**
- Modify: `tools/ogsl_sources.py`
- Modify: `tests/test_ogsl_sources.py`

- [ ] **Step 1: Write a failing large-file tool test**

Build a source table with 10,000 rows across two stations. Patch `_query_ogsl`
to assert:

```python
assert len(parameters["station_windows"]) == 2
assert parameters["station_windows"][0]["start"] == "2022-10-08T22:03:37Z"
```

Return a small raw OGSL fixture and assert:

```python
assert len(enriched) == 10_000
assert source.columns.tolist() == original_columns
assert set(enriched["ogsl_match_status"]) == {"matched"}
assert store.get(f"{thread_id}:ogsl") is not None
assert len(store.keys(f"{thread_id}:dataset:df_ogsl_enriched_")) == 1
```

- [ ] **Step 2: Run the tool test and verify RED**

Run: `pytest -q tests/test_ogsl_sources.py -k large_file`

Expected: FAIL because `query_ogsl` lacks `time_column`, `depth_column`, and
derived persistence.

- [ ] **Step 3: Extend the tool contract**

Change the signature to:

```python
def query_ogsl(
    station_column: str,
    time_column: str,
    depth_column: str | None = None,
    variables: list[str] | None = None,
    time_tolerance_hours: float = 24,
    depth_tolerance_m: float = 10,
) -> str:
```

Validate required columns, call `build_station_windows`, invoke `_query_ogsl`
with `station_windows`, then call `enrich_with_ogsl`.

Persist:

```python
store_dataset(..., raw_dataframe, latest_alias="ogsl", meta={"source": "ogsl", ...})
store_dataset(
    ...,
    enriched_dataframe,
    variable_name=dataset_variable_name("ogsl_enriched", query_id),
    meta={"source": "ogsl_enrichment", ...},
)
```

Return both table names, match-status counts, request count, and download links.

- [ ] **Step 4: Run tool and agent-factory tests**

Run: `pytest -q tests/test_ogsl_sources.py tests/test_agent_factory.py -k 'ogsl or required_tools'`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/ogsl_sources.py tests/test_ogsl_sources.py
git commit -m "feat(ogsl): enrich large station-time tables"
```

### Task 5: Agent Routing And Heavy-Operation Confirmation

**Files:**
- Modify: `agents/copepod_system_prompt.py`
- Modify: `tests/test_agent_factory.py`
- Modify: `agents/skills/environmental_join.md`

- [ ] **Step 1: Write failing prompt assertions**

Assert that the prompt:

- requires `station_column` and `time_column`;
- passes `depth_column` when available;
- says `query_ogsl` performs the standard join itself;
- forbids a redundant `run_pandas` join;
- requires confirmation above ten unique stations.

- [ ] **Step 2: Run and verify RED**

Run: `pytest -q tests/test_agent_factory.py -k ogsl`

Expected: FAIL on the new routing assertions.

- [ ] **Step 3: Update routing text**

Replace the current OGSL paragraph with explicit standard-enrichment routing.
Add `query_ogsl` above ten unique stations to the heavy-operation confirmation
list. Keep `environmental_join` for non-standard joins only.

- [ ] **Step 4: Run prompt tests**

Run: `pytest -q tests/test_agent_factory.py -k ogsl`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/copepod_system_prompt.py agents/skills/environmental_join.md tests/test_agent_factory.py
git commit -m "fix(agent): route standard OGSL enrichment through tool"
```

### Task 6: Harness, LangSmith, And Documentation

**Files:**
- Modify: `scripts/evals/run_agent_source_enrichment_eval.py`
- Modify: `scripts/evals/run_ogsl_langsmith_eval.py`
- Modify: `tests/test_agent_source_enrichment_eval.py`
- Modify: `tests/test_ogsl_langsmith_eval.py`
- Modify: `docs/TOOLS.md`
- Modify: `docs/AGENT_SOURCE_ENRICHMENT_EVAL.md`
- Modify: `docs/ARCHITECTURE.md`

- [ ] **Step 1: Write failing evaluator tests**

Update expected trajectory to:

```python
["load_file", "query_ogsl"]
```

Require:

- `station_column == "station"`
- `time_column == "sample_date"`
- no transcribed `stations`;
- one raw dataset with `source == "ogsl"`;
- one derived dataset with `source == "ogsl_enrichment"`;
- derived row count equals input row count;
- `ogsl_match_status` and `ogsl_time_delta_min` columns exist.

- [ ] **Step 2: Run and verify RED**

Run:

```bash
pytest -q tests/test_agent_source_enrichment_eval.py tests/test_ogsl_langsmith_eval.py
```

Expected: FAIL because evaluators still expect manual `load_skill` and
`run_pandas`.

- [ ] **Step 3: Update harness and docs**

Use a real bounded OGSL fixture with `station`, `sample_date`, and optional
`depth`. Update all new documentation passages in English.

- [ ] **Step 4: Run deterministic verification**

Run:

```bash
pytest -q \
  tests/test_ogsl_enrichment.py \
  tests/test_ogsl_client.py \
  tests/test_ogsl_sources.py \
  tests/test_agent_factory.py \
  tests/test_agent_source_enrichment_eval.py \
  tests/test_ogsl_langsmith_eval.py
git diff --check
```

Expected: all tests pass and no whitespace errors.

- [ ] **Step 5: Run one bounded LangSmith experiment**

Run:

```bash
set -a
source /Users/tidianecisse/PROJET_INFO/IDEA/.env
set +a
python scripts/evals/run_ogsl_langsmith_eval.py
```

Expected: all code evaluator scores equal `1`.

- [ ] **Step 6: Commit**

```bash
git add \
  scripts/evals/run_agent_source_enrichment_eval.py \
  scripts/evals/run_ogsl_langsmith_eval.py \
  tests/test_agent_source_enrichment_eval.py \
  tests/test_ogsl_langsmith_eval.py \
  docs/TOOLS.md \
  docs/AGENT_SOURCE_ENRICHMENT_EVAL.md \
  docs/ARCHITECTURE.md
git commit -m "test(ogsl): validate large-file agent enrichment"
```

### Task 7: Final Verification And Integration

**Files:**
- No production changes expected.

- [ ] **Step 1: Run the focused suite**

```bash
pytest -q \
  tests/test_ogsl_enrichment.py \
  tests/test_ogsl_client.py \
  tests/test_ogsl_sources.py \
  tests/test_agent_factory.py \
  tests/test_agent_source_enrichment_eval.py \
  tests/test_ogsl_langsmith_eval.py \
  tests/test_bio_oracle_sources.py
```

Expected: PASS.

- [ ] **Step 2: Run the full suite**

Run: `pytest -q`

Expected: all available tests pass. If only the known Chroma collection tests
fail, rebuild the local index with:

```bash
python core/copepod_rag/chunk_docs.py
python core/copepod_rag/build_index.py
pytest -q
```

- [ ] **Step 3: Review the final diff**

Run:

```bash
git diff --check
git status --short
git diff --stat main...HEAD
```

- [ ] **Step 4: Finish the branch**

Use `superpowers:finishing-a-development-branch`, then follow the user's chosen
push and merge-to-main workflow.
