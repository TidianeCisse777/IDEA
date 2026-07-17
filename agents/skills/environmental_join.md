---
name: environmental_join
version: 1.0.0
triggers:
  - Explicit request for a non-standard environmental join not covered by canonical enrichment
forbidden_when:
  - A standard Amundsen, Bio-ORACLE, OGSL, or EcoPart loaded-table enrichment applies
requires:
  - "dataset:loaded"
next_tool: run_pandas
max_tokens: 1300
description: Guides only non-standard pandas joins between already-loaded zooplankton and environmental tables when no canonical source enrichment applies.
---

# Environmental joins

You are about to perform a join between zooplankton and an environmental source.

---

## Tool routing — which method to use

| Join | Method |
|---|---|
| EcoTaxa + EcoPart (by `(sample_id, depth_bin)`) | `join_ecotaxa_ecopart` (EcoPart in session) or `enrich_ecotaxa_with_ecopart_remote` (EcoPart not loaded) — do **not** use this skill |
| Loaded table + Amundsen CTD | `enrich_with_amundsen_ctd` — do **not** use this skill |
| Loaded table + Bio-ORACLE | `enrich_with_bio_oracle` — do **not** use this skill |
| Loaded table + OGSL | `enrich_with_ogsl` — do **not** use this skill |
| Non-standard join between two environmental tables already in session | `run_pandas` using patterns below |
| Any other environmental join | `run_pandas` using patterns below |

> **`join_ecotaxa_ecopart` is exclusively for EcoTaxa ↔ EcoPart pairs.**
> Standard source enrichment never uses hand-written pandas matching. The
> canonical capability owns schema detection, tolerances, match status,
> persistence, and provenance. Use this skill only when the user explicitly
> requests a relation that no canonical enrichment can represent and both input
> tables are already loaded.

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

- Non-standard vertical CTD table: join by station, cast, time, then depth or pressure.
- Non-standard gridded environment table: join by latitude, longitude, variable, scenario and `depth_layer`.
- Non-standard station table: join by station or mission, then time and depth.
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
- OGSL enrichment uses a dedicated tool selected by the loaded table's join key: `query_ogsl` for station/time/depth matching, `enrich_with_ogsl` for latitude/longitude spatial matching (`spatial_tolerance_km`, `time_tolerance_hours`, `ogsl_te90_degC`, `ogsl_match_status` traceability). Do not treat one as the sole standard.
