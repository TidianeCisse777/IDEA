---
name: net_uvp_abundance_comparison
version: 2.0.0
triggers:
  - User asks to compare net (NeoLabs) abundance against UVP (EcoTaxa/EcoPart) abundance
  - User asks to join net and UVP data, compute density, make comparisons by taxon or stage
forbidden_when:
  - No NeoLabs file is loaded
  - df_net_uvp_matches does not exist yet — call find_uvp_matches_for_net_table first
requires:
  - "file:loaded"
next_tool: run_pandas
max_tokens: 3500
description: >
  Open environment for net↔UVP comparisons. The session has all the data;
  run_pandas composes freely. No rigid pipeline — user drives taxon, stage, depth range.
---

# Skill: net_uvp_abundance_comparison

## What is in session

After the preparation steps, the session contains:

| Variable | Content |
|---|---|
| `df_net_uvp_matches` | Correspondence table: `net_sample_id`, `station`, `uvp_sample_id`, `uvp_profile_str`, `distance_km`, `time_gap_days`, `match_status` |
| `df_ecotaxa_ecopart` | UVP objects enriched with EcoPart volumes: `sample_id` (string profile, e.g. `am_leg4_RA27_2`), `sample_id_internal` (numeric), `object_annotation_hierarchy`, `object_depth_min`, `depth_bin`, `ecopart_Sampled volume [L]` |
| `df_ecotaxa` | UVP objects before EcoPart enrichment (no volume column) |
| `df_file_neolabs_abundance` | Net tow taxonomy: `SAMPLE_ID`, `STATION_NAME`, `CLASS`, `ORDER`, `FAMILY`, per-stage abundance columns (`C1_ABUND ...`, `ALL_STAGES_ABUND ...`) |
| `df_file_neolabs_sample` | Net tow metadata: `SAMPLE_ID`, `STATION_NAME`, `latitude`, `longitude`, `deployment_datetime_start` |

Variable names come from `load_file`:
- `load_file("neolabs_abundance.csv")` → `df_file_neolabs_abundance`
- `load_file("neolabs_sample.csv")` → `df_file_neolabs_sample`
- `query_ecotaxa(...)` / export → `df_ecotaxa`
- `enrich_ecotaxa_with_ecopart_remote(...)` → `df_ecotaxa_ecopart`
- `find_uvp_matches_for_net_table(...)` → `df_net_uvp_matches`

All of these are automatically injected into every `run_pandas` call — no reload needed.

## Bridge key between UVP and net

`df_net_uvp_matches` links:
- `uvp_sample_id` (integer) ↔ `sample_id_internal` in the EcoTaxa DataFrame
- `station` ↔ `STATION_NAME` in the NeoLabs abundance DataFrame

Always join through `df_net_uvp_matches` — never invent a spatial join directly.

## How to compute UVP density (run_pandas)

```python
from core.copepod_sample_depth import build_canonical_sample_depth

# taxon_filter examples:
#   None          → copepods only (copepod_hierarchy_mask)
#   "Calanus"     → any object whose hierarchy contains "Calanus"
#   "Copepoda"    → all copepods via substring match
#   "Appendicularia" → appendicularians
#   "*"           → all organisms

canonical = build_canonical_sample_depth(
    df_ecotaxa_ecopart,                  # enriched EcoTaxa+EcoPart DataFrame
    taxon_filter="Calanus",              # ← user's choice
    volume_column="ecopart_Sampled volume [L]",
)
# canonical columns: sample_id (string), depth_bin, target_count,
#                    sampled_volume_L, abundance_ind_L, abundance_ind_m3

# Aggregate per profile (mean over depth bins)
uvp_density = (
    canonical
    .groupby("sample_id", as_index=False)["abundance_ind_m3"].mean()
    .rename(columns={"sample_id": "uvp_profile_str"})
)
```

Restrict to a depth range before aggregating if the user asks:
```python
bins = canonical[(canonical["depth_bin"] >= 0) & (canonical["depth_bin"] <= 200)]
```

## How to compute net density (run_pandas)

```python
from core.neolabs_abundance import neolabs_copepod_density, STAGE_GROUPS

# stages presets:
#   "ALL_STAGES"   → all stages combined (default)
#   "late_stages"  → C4+C5+M+F  (comparable to UVP, >~600 µm)
#   "adults"       → M+F only
#   "copepodites"  → C1 to C5
#   "nauplii"      → N1 to N6
#   ["C5","M","F"] → explicit list

# taxon_filter matches the CLASS column (or pass taxon_column="FAMILY" for family-level)
net_density = neolabs_copepod_density(
    df_file_neolabs_abundance,
    stages="late_stages",            # ← user's choice
    taxon_filter="Copepoda",         # ← user's choice
    taxon_column="CLASS",
)
# net_density columns: STATION_NAME, copepod_density_ind_m3, n_samples,
#                      stages_used, taxon_filter
```

## Bridge and compare (run_pandas)

```python
from core.net_uvp_comparison import compare_paired_density

# Step 1: add the string profile to the match table
id_bridge = df_ecotaxa_ecopart[["sample_id_internal","sample_id"]].drop_duplicates()
id_bridge.columns = ["uvp_sample_id","uvp_profile_str"]
matched = df_net_uvp_matches[df_net_uvp_matches["match_status"]=="matched"].merge(
    id_bridge, on="uvp_sample_id", how="left"
)

# Step 2: join net density
paired = matched.merge(
    net_density.rename(columns={"copepod_density_ind_m3":"net_ind_m3"}),
    left_on="station", right_on="STATION_NAME", how="inner"
)

# Step 3: join UVP density
paired = paired.merge(uvp_density.rename(columns={"abundance_ind_m3":"uvp_ind_m3"}),
                      on="uvp_profile_str", how="inner")

# Step 4: compare
result = compare_paired_density(paired, net_col="net_ind_m3", uvp_col="uvp_ind_m3")
# adds: abundance_delta_ind_m3, abundance_abs_delta_ind_m3,
#       abundance_ratio (uvp/net), abundance_log2_ratio
```

## Interpretation rules

- `abundance_ratio` near 1 = concordant; >> 1 = UVP reads higher; << 1 = net reads higher.
- Net tows and UVP are not expected to give identical numbers: different sampling volumes,
  size selectivity, detection thresholds. Never present one as "more correct".
- UVP detects organisms reliably above ~600 µm → compare `late_stages` (C4+C5+M+F)
  on the net side when comparing totals, not `ALL_STAGES` which includes nauplii.
- Always keep `time_gap_days` and `match_status` visible in any result table.
- No causal or biological interpretation: describe the numbers, state the comparison basis.

## Graphs

After building `result`, call `load_skill("graph_writer")` then `run_graph` for:
- Scatter: `net_ind_m3` vs `uvp_ind_m3` per station (1:1 line reference)
- Bar: `abundance_log2_ratio` per station (0 = perfect agreement)
- Map: station bubbles coloured by ratio (needs lat/lon from `df_file_neolabs_sample`)
