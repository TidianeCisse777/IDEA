---
name: environmental_join
description: Guides pandas joins between zooplankton tables and environmental sources such as CTD, Bio-ORACLE, or OGSL, preserving raw columns and choosing join keys explicitly. Use when the user asks how to join zooplankton with CTD, Bio-ORACLE, OGSL, station, cast, time, latitude/longitude, or depth data, or when a join strategy must be planned for environmental datasets.
---

# Environmental joins

You are about to perform a join between zooplankton and an environmental source.

---

## Tool routing — which method to use

| Join | Method |
|---|---|
| EcoTaxa + EcoPart (by `(sample_id, depth_bin)`) | `join_ecotaxa_ecopart` (EcoPart in session) or `enrich_ecotaxa_with_ecopart_remote` (EcoPart not loaded) — do **not** use this skill |
| EcoTaxa + CTD Amundsen | `run_pandas` using patterns below |
| EcoTaxa + Bio-ORACLE | `run_pandas` using patterns below |
| Standard loaded-table + OGSL enrichment | `query_ogsl` — do **not** use this skill |
| Non-standard EcoTaxa + OGSL join | `run_pandas` using patterns below |
| Any other environmental join | `run_pandas` using patterns below |

> **`join_ecotaxa_ecopart` is exclusively for EcoTaxa ↔ EcoPart pairs.**
> Standard OGSL enrichment is handled inside `query_ogsl`. Use this skill only
> when the requested OGSL relation cannot be represented by its standard
> station/time/depth matching contract.

---

## Usage rule

- After reading this skill, immediately call `run_pandas` to execute the join — both datasets are already accessible in the session. Do not stop at the plan or provide a script for the user to run themselves.
- Always treat raw columns as the source of truth.
- Add aliases only in addition to the original columns, never instead of them.

---

## Goal

Produce a traceable join table with an explicit match rule, stable keys, and quality indicators.

---

## Common join keys

- `station_id`
- `cast_id` or `cast_number`
- `profile_id`
- `time`
- `latitude`
- `longitude`
- `depth` or `Pres`

---

## Base rules

1. Identify the environmental source before writing the join.
2. Choose the most stable available key.
3. Preserve raw source columns.
4. Add only non-destructive join aliases.
5. Document match quality with `*_match_status` and deltas.
6. If an essential key is missing, ask for it rather than inventing a match.

---

## Pandas patterns

- Exact metadata match:
  - `merge(..., on=[...], how="left")`
- Nearest temporal match:
  - `sort_values(...)` then `merge_asof(..., direction="nearest")`
- Depth match:
  - compute `abs(depth_source - depth_target)` then keep the minimum per group
- Spatial point match:
  - use `latitude` / `longitude` then filter by scenario, variable or layer

---

## By source

- Vertical CTD: join by station, cast, time, then depth or pressure.
- Bio-ORACLE: join by latitude, longitude, variable, scenario and `depth_layer`.
- OGSL: join by station or mission, then time and depth.
- EcoTaxa + EcoPart: handled by the dedicated tool on `(sample_id, depth_bin)` — the EcoTaxa profile identifier matched to EcoPart `Profile`, then a 5 m depth bin. Never hand-roll this merge.

---

## Expected output

- A clean table with one row per observation and per match.
- Quality columns such as `match_status`, `time_delta`, `depth_delta`, `distance_km`.
- A short summary of matched and unmatched rows.

---

## Forbidden

- Do not invent missing values.
- Do not mix exact depth with surface layer without saying so.
- Do not drop raw columns.
- Do not interpret the join biologically.

## Runtime routing contract

- When chaining enrichments on the same EcoTaxa-derived table, pass `source_variable` as the exact variable produced by the previous step. Do not rely on the bare active `df`, which can silently enrich the wrong table. Confirm the reported "Table enrichie".
- Load with `load_skill("environmental_join")` for non-standard Amundsen CTD or Bio-ORACLE joins.
- Standard OGSL enrichment uses `enrich_with_ogsl`, including `spatial_tolerance_km`, `time_tolerance_hours`, `ogsl_te90_degC`, and `ogsl_match_status` traceability.
