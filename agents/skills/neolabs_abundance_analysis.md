---
name: neolabs_abundance_analysis
version: 1.0.0
triggers:
  - Loaded NeoLabs abundance table requires ecological metrics or ordination
forbidden_when:
  - No NeoLabs abundance table is loaded
requires:
  - "dataset:neolabs_abundance"
next_tool: run_pandas
max_tokens: 3700
size_exemption: The sample-level aggregation, diversity, environmental matching, and ordination rules share one required sample_df contract; the small overage avoids divergent analytical bases.
description: Standard ecological analysis workflow for NeoLabs taxonomy abundance tables enriched with Amundsen CTD. Use when the user asks to analyse NeoLabs abundance, zooplankton abundance, copepod abundance, diversity, anomalies, seasonality, CTD relationships, PCA, PCoA, NMDS, RDA, or community-environment ordination.
---

# Skill: neolabs_abundance_analysis

Use this skill for NeoLabs taxonomy abundance files, especially tables like `neolabs_taxonomy_abundance_amundsen_ctd.tsv`. The anti-error essentials come first; workflows follow; the optional enrichment pre-step is last.

## Core rule

NeoLabs abundance rows are taxon-level rows. Do not analyse temporal, spatial, environmental, or station-level patterns directly from raw rows without first rebuilding the correct working table.

**Vertical profile — build the working table correctly (NeoLabs-specific):**
- **One profile = one deployment** (station + cast). Never pool different deployments/stations onto one profile.
- **Pick the deployment by the number of DISTINCT depth strata** (`MIN/MAX_SAMPLE_DEPTH.nunique()`), not by row count: a deployment with a single stratum is not a profile (a real multinet has several nets at successive depths). If none is named, ask which deployment (or draw one small-multiple per station for a small set).
- **Total abundance at a stratum = SUM of the taxon rows** at that stratum (each row is one taxon), never their mean; then plot that summed abundance against depth (the graph skill inverts the depth axis).

## Column families (wide per-stage files) — read before any abundance calculation

Many NeoLabs files have no single `Total abundance` column: abundance is spread
across **per-stage columns**, each in three or five variants. Two traps here
produce wrong numbers if ignored.

**Metric variants per stage `X`:**
- `X_SAMPLE_ABUND (nbr of ind.)` — raw count in that sample. **Not comparable
  across samples** (different filtered volumes). Never sum these as a "total number
  of individuals".
- `X_ABUND (ind./m3 depth vol.)` and `X_ABUND (ind./m3 flowmeter vol.)` —
  **density**, already normalised (`= X_SAMPLE_ABUND / volume`). This is the
  comparable metric. Default to `depth vol`.
- `X_BIOMASS (...)` — µg C m⁻³ (copepodite/adult stages only; nauplii have none).

**Stage columns are NOT disjoint — never sum an aggregate with its components:**
- Individual stages: `C1`–`C5`, `M` (male), `F` (female), `N1`–`N6` (nauplii).
- Aggregates (already sums of the above): `COP_NS`/`COPEPODID` = copepodite
  subtotals, `NAUP_NS`/`NAUPLIUS` = nauplii subtotals, **`ALL_STAGES` = the row
  total (sum of every stage)**.
- For a per-row total, read `ALL_STAGES_ABUND (ind./m3 depth vol.)` directly —
  do **not** reconstruct it by adding stage columns, and never rank `ALL_STAGES`,
  `COPEPODID`, and `C1`–`C5` against each other: that double/triple-counts.

When the file lacks a single `Total abundance` column, `ALL_STAGES_ABUND
(ind./m3 depth vol.)` is the total abundance; use it wherever this skill says
`Total abundance (ind./m3 depth vol)`.

## Default abundance metric

Use `Total abundance (ind./m3 depth vol)` by default when it is present.

Rules:
- Unit is `ind./m3` / `ind m-3`.
- Use `Total abundance (ind./m3 flowmeter vol)` only when depth volume is missing or when the user explicitly asks for flowmeter-normalized abundance.
- Never mix depth-vol and flowmeter-vol abundance in the same comparison without stating which rows use which volume basis.
- Clip negative abundance values only for exploratory plots and explicitly report how many were affected.

## Volumes filtrés et conversion d'unités

NeoLabs net rows expose **two filtered-volume columns** in m³:

| Column | Formula | When valid |
|---|---|---|
| `DEPTH_CALC_VOL` (m³) | `π × r² × (MAX_SAMPLE_DEPTH − MIN_SAMPLE_DEPTH) × E` (theoretical vertical tow volume; `E` ≈ 1 if not provided) | Always — derived purely from net geometry + strata |
| `FLOWMETER_CALC_VOL` (m³) | `flowmeter constant × Δturns` (= section × distance actually travelled) | Only when the cast was equipped with a flowmeter |

**Pick `DEPTH_CALC_VOL` by default** (matches `(ind./m3 depth vol)` columns,
robust across casts). Use `FLOWMETER_CALC_VOL` (= `(ind./m3 flowmeter vol)`)
when the user explicitly mentions flowmeter normalization or when depth-vol
is missing on the rows of interest.

If a recompute is needed (rare):

```python
import math
NET_RADIUS_M = 0.5  # ⚠ ask the user; typical WP2 = 0.286 m, Bongo = 0.305 m
EFFICIENCY = 1.0    # E in the formula; ask the user if unsure

vol_depth_m3 = (
    math.pi * NET_RADIUS_M**2
    * (df["MAX_SAMPLE_DEPTH"] - df["MIN_SAMPLE_DEPTH"])
    * EFFICIENCY
)
# flowmeter recompute (calibration constant in m³ per turn, usually printed on the device):
# vol_flowmeter_m3 = FLOWMETER_CONSTANT * (turns_end - turns_start)
```

### Conversion m³ ↔ L (cross-source comparisons)

NeoLabs net abundance is in **`ind./m³`**. UVP (EcoTaxa/EcoPart) and
in-water sensors are typically in **`ind./L`** or per-image. When the user
asks to compare or join a net dataset with UVP/EcoPart results, you MUST
align units before comparing or plotting:

| From | To | Multiply by |
|---|---|---|
| `ind./m³` | `ind./L` | `÷ 1000` (1 m³ = 1000 L) |
| `ind./L` | `ind./m³` | `× 1000` |
| `mm³/m³` (biovolume) | `mm³/L` | `÷ 1000` |

```python
# Compare UVP m5 (ind/L) vs NeoLabs net (ind/m3)
df_uvp_m5["abundance_per_m3"] = df_uvp_m5["m5_cop_dens_ind_per_L"] * 1000
# or, the other way:
df_net["abundance_per_L"] = df_net["Total abundance (ind./m3 depth vol)"] / 1000
```

Name any derived column explicitly with the unit (`abundance_per_L`,
`m5_cop_dens_ind_per_m3`) so the user can verify the conversion. Never
plot a mixed-unit chart without stating the conversion in the answer.

## When to ask for clarification

Always ask (or, when one sensible default exists, declare the assumption up front
before computing) when a vague request leaves a consequential choice open — per
the system-prompt ambiguity rule. On this wide per-stage file the recurring open
choices are:
- **metric**: raw count (`SAMPLE_ABUND`) vs density (`ABUND ind./m3`) vs biomass.
- **volume basis**: depth-vol vs flowmeter-vol.
- **stage/level**: a specific stage (C1–C5, M, F, nauplii) vs a subtotal
  (COPEPODID/NAUPLIUS) vs the row total (`ALL_STAGES`).
- **aggregation**: taxon-level rows vs `sample_df` (per `SAMPLE_ID + ANALYSIS_ID`)
  vs station/date; and for a graph, which chart and which axis.

Also ask when the file lacks an essential column with no inferable equivalent
(no `SAMPLE_ID`/`ANALYSIS_ID`, no `TAXON_ID`, no abundance column, no
date/station/lat/lon for coverage). Otherwise inspect the file, then — if a
material choice remains — surface it (question or up-front `Hypothèse: …`) before
running the calculation; never pick silently and reveal it only afterward.

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

## Visual output routing

For any visual request on a NeoLabs abundance file, use this skill only to
choose the correct ecological working table and transformations, then render
directly with `run_graph` under the kernel graph rules.

Recommended levels:

| Analysis | Working table |
|---|---|
| Taxon ranking | raw taxon-level table |
| Sample/station/time coverage | `sample_df`, one row per `SAMPLE_ID + ANALYSIS_ID` |
| Abundance by sample/station/year | `sample_df`, aggregating taxon rows |
| Diversity indices | taxon matrix, one row per `SAMPLE_ID + ANALYSIS_ID`, one column per `TAXON_ID` |
| CTD relationships | `sample_df` filtered to `ctd_match_status == "matched"` |
| Ordination | taxon matrix joined to environmental `sample_df` |

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
   - **copepod density — use the deterministic contract, do NOT hand-roll.**
     Import and call `neolabs_copepod_density` from `core.neolabs_abundance`: it
     filters `CLASS == 'Copepoda'`, sums `Total abundance (ind./m3 depth vol)`
     per `SAMPLE_ID`, then averages per station. NEVER average `Total abundance`
     over raw taxon-level rows (only ~half of the ~199 taxa are copepods, so a
     row-mean mixes non-copepods, stages and depth strata and is wrong), and
     never count rows as stations.
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

## Optional pre-step — source-authorized environmental enrichment

Do this FIRST only when the user explicitly asks to enrich with environmental
data; otherwise skip it and go straight to the analysis above.

Environmental vocabulary alone never authorizes an online source. Run an
enrichment only when the Source Selection Gateway authorizes a source and the
user requests that source's environmental data. If no source is authorized and
the loaded file lacks the requested environmental columns, report that limit or
ask which source to use; do not choose Amundsen, Bio-ORACLE, or OGSL yourself.

When enrichment is explicitly requested, call only the named source's canonical
loaded-table enrichment on the exact active variable. Do not run discovery or
raw retrieval first. Continue the taxon-level analysis only from the exact
persisted enriched variable returned by a successful result.

### Canonical source routes

Use exactly one of these routes according to the authorized source:

```
enrich_with_amundsen_ctd(source_variable="<exact active variable>")
enrich_with_bio_oracle(source_variable="<exact active variable>", variables=[...])
enrich_with_ogsl(source_variable="<exact active variable>")
```

Pass `zone_name` or `date_range` only when the user actually requested that
scope. Never copy illustrative zone names, dates, variables, or identifiers into
a real call.

### Sub-step — join abundance via run_pandas

```
merged = abundance.merge(enriched_sample, left_on="SAMPLE_ID", right_on="sample_id")
```

Each taxon row now has env columns; THEN continue with the standard workflow
(the core rule and the analysis sections above).

## Runtime routing contract

- Apply this procedure whenever a NeoLabs abundance table is the active dataset.
- Build the correct working table here, then call `run_graph` directly.
