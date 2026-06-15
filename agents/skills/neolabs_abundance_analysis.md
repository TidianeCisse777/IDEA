---
name: neolabs_abundance_analysis
description: Standard ecological analysis workflow for NeoLabs taxonomy abundance tables enriched with Amundsen CTD. Use when the user asks to analyse NeoLabs abundance, zooplankton abundance, copepod abundance, diversity, anomalies, seasonality, CTD relationships, PCA, PCoA, NMDS, RDA, or community-environment ordination.
---

# Skill: neolabs_abundance_analysis

Use this skill for NeoLabs taxonomy abundance files, especially tables like `neolabs_taxonomy_abundance_amundsen_ctd.tsv`.

## Core rule

NeoLabs abundance rows are taxon-level rows. Do not analyse temporal, spatial, environmental, or station-level patterns directly from raw rows without first rebuilding the correct working table.

Recommended levels:

| Analysis | Working table |
|---|---|
| Taxon ranking | raw taxon-level table |
| Sample/station/time coverage | `sample_df`, one row per `SAMPLE_ID + ANALYSIS_ID` |
| Abundance by sample/station/year | `sample_df`, aggregating taxon rows |
| Diversity indices | taxon matrix, one row per `SAMPLE_ID + ANALYSIS_ID`, one column per `TAXON_ID` |
| CTD relationships | `sample_df` filtered to `ctd_match_status == "matched"` |
| Ordination | taxon matrix joined to environmental `sample_df` |

## Default abundance metric

Use `Total abundance (ind./m3 depth vol)` by default when it is present.

Rules:
- Unit is `ind./m3` / `ind m-3`.
- Use `Total abundance (ind./m3 flowmeter vol)` only when depth volume is missing or when the user explicitly asks for flowmeter-normalized abundance.
- Never mix depth-vol and flowmeter-vol abundance in the same comparison without stating which rows use which volume basis.
- Clip negative abundance values only for exploratory plots and explicitly report how many were affected.

## Build `sample_df`

For sample-level analyses, group by:

```text
SAMPLE_ID + ANALYSIS_ID
```

Recommended fields:

```python
sample_df = (
    df.assign(
        abundance=pd.to_numeric(df["Total abundance (ind./m3 depth vol)"], errors="coerce").clip(lower=0),
        deployment_datetime_start=pd.to_datetime(df["deployment_datetime_start"], errors="coerce", utc=True),
    )
    .groupby(["SAMPLE_ID", "ANALYSIS_ID"], dropna=False)
    .agg(
        station=("STATION_NAME", "first"),
        year=("deployment_datetime_start", lambda s: s.dt.year.iloc[0] if s.notna().any() else None),
        month=("deployment_datetime_start", lambda s: s.dt.month.iloc[0] if s.notna().any() else None),
        latitude=("latitude", "first"),
        longitude=("longitude", "first"),
        min_depth=("MIN_SAMPLE_DEPTH", "first"),
        max_depth=("MAX_SAMPLE_DEPTH", "first"),
        ctd_match_status=("ctd_match_status", "first"),
        total_abundance_ind_m3=("abundance", "sum"),
        taxon_richness=("TAXON_ID", "nunique"),
        amundsen_temperature_degC=("amundsen_temperature_degC_mean_sample_interval", "first"),
        amundsen_salinity_psu=("amundsen_salinity_psu_mean_sample_interval", "first"),
        amundsen_oxygen_uM=("amundsen_oxygen_uM_mean_sample_interval", "first"),
        amundsen_fluorescence_ug_l=("amundsen_fluorescence_ug_l_mean_sample_interval", "first"),
        amundsen_nitrate_mmol_m3=("amundsen_nitrate_mmol_m3_mean_sample_interval", "first"),
    )
    .reset_index()
)
```

Adjust column names to the actual file after inspection.

## Standard analyses to propose

1. Coverage audit:
   - number of rows, samples, stations, taxa
   - year/month coverage
   - missing dates, latitude/longitude, CTD variables

2. QA/QC:
   - `ctd_match_status` counts
   - `ctd_distance_km`, `ctd_time_delta_min`, `ctd_depth_coverage_m`
   - negative or missing abundance values
   - generic taxonomic labels such as `Animalia`, `Copepoda`, `Calanus spp.`

3. Abundance:
   - total zooplankton abundance in `ind./m3`
   - copepod abundance filtered from `ZOOPLANKTON_CATEGORY`
   - top taxa by summed abundance
   - abundance by station, year, month, depth interval

4. Diversity:
   - taxon richness
   - Shannon diversity
   - Simpson diversity
   - Pielou evenness

5. Temporal anomalies:
   - monthly climatology when enough years exist
   - anomaly = observation minus monthly mean
   - standardized anomaly = anomaly / monthly standard deviation

6. Community-environment:
   - only use samples with `ctd_match_status == "matched"`
   - plot `log10(total_abundance_ind_m3 + 1)` versus temperature, salinity, oxygen, fluorescence, nitrate
   - present relationships as exploratory unless the user asks for a formal model

7. Ordination:
   - PCA on standardized environmental variables
   - PCoA or NMDS on Bray-Curtis taxonomic composition
   - RDA for exploratory community-environment coupling
   - CCA only when a validated method/library is available; otherwise state that CCA is not implemented in this workflow

## Diversity formulas

Build a sample-by-taxon matrix first:

```python
taxon_matrix = (
    df.assign(abundance=pd.to_numeric(df["Total abundance (ind./m3 depth vol)"], errors="coerce").clip(lower=0))
    .pivot_table(
        index=["SAMPLE_ID", "ANALYSIS_ID"],
        columns="TAXON_ID",
        values="abundance",
        aggfunc="sum",
        fill_value=0,
    )
)
```

Then:

```python
p = taxon_matrix.div(taxon_matrix.sum(axis=1).replace(0, pd.NA), axis=0)
shannon = -(p * np.log(p.where(p > 0))).sum(axis=1)
simpson = 1 - (p ** 2).sum(axis=1)
richness = (taxon_matrix > 0).sum(axis=1)
pielou = shannon / np.log(richness.where(richness > 1))
```

## Ordination workflow

Use `scikit-learn` for PCA and NMDS when available. Use `scipy` for Bray-Curtis distances.

Preparation:

```python
from scipy.spatial.distance import pdist, squareform
from sklearn.decomposition import PCA
from sklearn.manifold import MDS
from sklearn.preprocessing import StandardScaler
```

Taxon matrix:
- Keep samples with positive total abundance.
- Remove taxa occurring in fewer than 3 samples or contributing only tiny abundance, unless the user asks to keep rare taxa.
- Apply `log1p` or Hellinger transformation before ordination.

Environment matrix:
- Use matched CTD samples only.
- Standardize temperature, salinity, oxygen, fluorescence, nitrate.
- Keep `ctd_distance_km` and `ctd_time_delta_min` available for QA, not as ecological predictors by default.

Recommended outputs:
- PCA environmental biplot or scores colored by year/station.
- PCoA/NMDS taxonomic ordination colored by temperature, salinity, or year.
- RDA exploratory biplot with top environmental arrows and dominant taxa.

Interpretation rule:
- Do not claim causality.
- Say "ordination exploratoire" unless a formal model, permutation test, and assumptions are explicitly implemented.

## When to ask for clarification

Ask only if the file lacks an essential column and no equivalent can be inferred:
- no sample key (`SAMPLE_ID`, `ANALYSIS_ID`)
- no taxon column (`TAXON_ID`)
- no abundance column
- no date/station/lat/lon for coverage analysis

Otherwise inspect the file and proceed with the closest valid workflow.
