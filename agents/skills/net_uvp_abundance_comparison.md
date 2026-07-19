---
name: net_uvp_abundance_comparison
version: 1.0.0
triggers:
  - User asks to compare net (NeoLabs) copepod abundance against UVP (EcoTaxa/EcoPart) abundance on matching stations
forbidden_when:
  - No NeoLabs net table is loaded
  - No net↔UVP correspondence table (df_net_uvp_matches) exists yet
requires:
  - "dataset:neolabs_abundance"
next_tool: run_pandas
max_tokens: 3400
size_exemption: The three sub-contracts (net density, UVP density, paired comparison) share one correspondence table and one unit basis; splitting them would let a free run_pandas re-derive an inconsistent join or mix ind./L with ind./m³.
description: Cross-instrument workflow to compare net (NeoLabs) copepod abundance with UVP (EcoTaxa/EcoPart) copepod abundance on the same monitoring stations. Use after find_uvp_matches_for_net_table has persisted df_net_uvp_matches, when the user wants to see whether net and UVP abundances coincide, their delta, or their ratio.
---

# Skill: net_uvp_abundance_comparison

Compare copepod abundance measured by **net tows (NeoLabs)** with copepod
abundance measured by **UVP (EcoTaxa/EcoPart)** on the same stations. This is a
cross-instrument comparison, never a single-source analysis.

## Hard prerequisite — the correspondence must already exist

This skill consumes `df_net_uvp_matches`, produced by
`find_uvp_matches_for_net_table`. If it does not exist, STOP and call
`find_uvp_matches_for_net_table` first (or tell the user no UVP samples cover the
net zone). Never invent a net↔UVP join yourself.

`df_net_uvp_matches` columns: `net_sample_id`, `station`, `latitude`,
`longitude`, `net_datetime`, `uvp_sample_id`, `uvp_project_id`,
`uvp_instrument`, `distance_km`, `time_gap_days`, `match_status`.

## Read the temporal reality first

- `match_status == "matched"` → spatial AND temporal proximity: a near-synchronous
  comparison is defensible.
- `match_status == "spatial_only"` → same station, different campaigns/years
  (typical: historical net program vs recent UVP). The comparison is then
  **station-level / climatological**, NOT cast-to-cast. Say so explicitly and
  keep `time_gap_days` visible in the answer. Never present a spatial_only
  comparison as if net and UVP sampled the same water.

## Step 1 — Net copepod density (ind./m³), deterministic contract

Do NOT hand-roll. Import the imposed contract:

```python
from core.neolabs_abundance import neolabs_copepod_density
net_density = neolabs_copepod_density(net_df)  # per STATION_NAME, ind./m³
```

It filters `CLASS == 'Copepoda'`, sums per `SAMPLE_ID`, averages per station.
Output key column: `copepod_density_ind_m3`.

## Step 2 — UVP copepod density (ind./m³)

UVP copepod density comes from EcoTaxa copepod objects normalised by the EcoPart
sampled volume. Use the existing UVP path, do not reinvent it:

1. Ensure the matched UVP project is loaded and enriched with EcoPart volume via
   `enrich_ecotaxa_with_ecopart_remote` (confirmation required — heavy op).
2. Build the canonical UVP copepod density with
   `core.copepod_sample_depth.build_canonical_sample_depth` (copepod filter +
   volume normalisation). UVP density is typically **ind./L**.

If the UVP copepod density cannot be computed remotely in this session, say so
and stop at Step 1 rather than fabricating a UVP number.

## Step 3 — Align units, then bridge through the matches

UVP is usually **ind./L**; net is **ind./m³**. Align BEFORE comparing:

```python
from core.net_uvp_comparison import to_ind_per_m3, compare_paired_density

uvp_density["uvp_ind_m3"] = to_ind_per_m3(
    uvp_density["copepod_density_ind_per_L"], from_unit="ind_per_L"
)

# bridge net station density and UVP sample density via the correspondence
paired = (
    df_net_uvp_matches
    .merge(net_density[["STATION_NAME", "copepod_density_ind_m3"]],
           left_on="station", right_on="STATION_NAME", how="inner")
    .merge(uvp_density[["uvp_sample_id", "uvp_ind_m3"]],
           on="uvp_sample_id", how="inner")
    .rename(columns={"copepod_density_ind_m3": "net_ind_m3"})
)
```

If the UVP density is already in ind./m³, pass `from_unit="ind_per_m3"`.

## Step 4 — Paired comparison, deterministic contract

```python
result = compare_paired_density(paired, net_col="net_ind_m3", uvp_col="uvp_ind_m3")
```

Adds `abundance_delta_ind_m3` (uvp − net), `abundance_abs_delta_ind_m3`,
`abundance_ratio` (uvp / net), `abundance_log2_ratio`. Keep `station`,
`distance_km`, `time_gap_days`, `match_status` in the result so the reader sees
the matching quality alongside every delta.

## Interpretation rules

- Report agreement descriptively: `abundance_ratio` near 1 = concordant,
  ≫1 = UVP reads higher, ≪1 = net reads higher. Do NOT claim one instrument is
  "correct".
- Net and UVP differ by design (mesh selectivity vs image detection, size ranges,
  depth strata). State that they are not expected to be identical.
- Never mix depth-vol and flowmeter-vol net abundance in the same comparison
  without stating the volume basis.
- No causal or biological interpretation (project rule): describe the numbers.

## Visual output routing

Not a graph_writer replacement. For a plot (e.g. net vs UVP scatter per station,
or log2-ratio map), use this skill only to build the paired table, then call
`load_skill("graph_planner")`, then `load_skill("graph_writer")`; the very next
execution call must be `run_graph`.

## Runtime routing contract

- Enter via `load_skill("net_uvp_abundance_comparison")` only after
  `find_uvp_matches_for_net_table` has persisted `df_net_uvp_matches`.
- This skill does not fetch sources on its own; Step 2's remote UVP path stays
  under the Source Selection Gateway and the heavy-operation confirmation rule.
