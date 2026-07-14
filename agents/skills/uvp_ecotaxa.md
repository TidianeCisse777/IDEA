# Skill: uvp_ecotaxa

You just loaded a **UVP EcoTaxa file** (columns `fre_*` or `object_*` + `sample_id`),
or a **pre-joined intermediate table** from `scripts/uvp_metrics_pipeline.py`.
This skill provides the keys for interpreting it and computing metrics m5 and
m6 (Vilgrain & Bourgouin 2026).

---

## ⚠ Not for net samples (WP2, Multinet, Bongo…)

This skill applies to **UVP imagery** (vertical profiles, 5 m bins, surface
+ bottom 50 m averaging). If the loaded file is a **zooplankton net
sample** — telltale columns: `GEAR`, `TOW_TYPE`, `NET_MESH_SIZE`,
`MIN_SAMPLE_DEPTH`/`MAX_SAMPLE_DEPTH`, `Total abundance (ind./m3 depth vol)`,
`flowmeter` — m5/m6 do not apply (no fine depth bins, no surface/bottom
split). In that case load **`neolabs_abundance_analysis`** instead and
ignore the templates below.

---

## Units — UVP is per-litre, nets are per-m³

UVP outputs (`m5`, `m6`, particle densities) are in **`ind./L`** (the
volume basis is `sampled_volume` from EcoPart, in litres per 5-m bin).
Zooplankton net abundance (NeoLabs `(ind./m3 depth vol)` /
`(ind./m3 flowmeter vol)`) is in **`ind./m³`**.

To compare or join the two sources you MUST convert before plotting:

```python
# UVP → per m³ (multiply by 1000)
df_uvp["m5_cop_dens_ind_per_m3"] = df_uvp["m5_cop_dens_ind_per_L"] * 1000
# Net → per L (divide by 1000)
df_net["abundance_per_L"] = df_net["Total abundance (ind./m3 depth vol)"] / 1000
```

Name the derived column with the new unit (`*_ind_per_m3`,
`*_per_L`) and state the conversion in the answer. See
`neolabs_abundance_analysis` for the full conversion table and net-volume
formulas (`DEPTH_CALC_VOL` vs `FLOWMETER_CALC_VOL`).

## Mandatory taxonomic selection — hierarchy only

Every Copepoda selection MUST use `object_annotation_hierarchy` through
`copepod_hierarchy_mask`. Never construct a keyword regex or a manual list of
descendant names. If the hierarchy column is missing, let the helper refuse the
calculation and explain that a new EcoTaxa export containing
`object_annotation_hierarchy` is required.

Do not copy or rename an alternate column to bypass this requirement, even on a
temporary dataframe. In particular, `hierarchy` is not an accepted substitute
for `object_annotation_hierarchy`. Do not pass an alternate column name to the
helper. A legacy intermediate table lacking the exact required column must be
refused and re-exported with the EcoTaxa hierarchy field.

## Mandatory canonical sample–depth table

For an object-level UVP table already joined with EcoPart, build the bin table
exactly once with the shared constructor:

```python
from core.copepod_sample_depth import build_canonical_sample_depth

volume_col = (
    "ecopart_Sampled volume [L]"
    if "ecopart_Sampled volume [L]" in df.columns
    else "sampled_volume"
)
canonical_bins = build_canonical_sample_depth(
    df,
    volume_column=volume_col,
)
result = canonical_bins  # persists as df_canonical_sample_depth
```

The result has one row per (`sample_id`, `depth_bin`), includes sampled zero
bins, and exposes `copepod_count`, `sampled_volume_L`, `abundance_ind_L`, and
`abundance_ind_m3`. All downstream tables, correlations, and graph datasets
MUST reuse the same `canonical_bins`. Do not rebuild the copepod mask or bins
independently in a later code block, and never add sampled volume to the group
key. If metadata or environmental columns are needed downstream, pass their
names through `stable_columns=(...)` when building the table.

Because analysis calls are isolated, the first call MUST return
`result = canonical_bins`. The analysis tool then persists it as
`df_canonical_sample_depth`. Every later analysis or graph MUST read
`df_canonical_sample_depth` directly and MUST NOT call the constructor again.

---

## 🛑 READ THIS FIRST — elementary abundance is the default

Generic abundance requests never produce m5 or m6. For **"densité
copépodes" / "abondance copépodes" / "profils verticaux" / environmental
relationships**, use `abundance_ind_L` or `abundance_ind_m3` from
`df_canonical_sample_depth`. These are the only elementary abundance columns.
Do not create ambiguous aliases such as `abundance`, `density`, or `cop_dens`.

For an environmental relationship or correlation, use the shared preparer:

```python
from core.copepod_abundance_analysis import prepare_environment_correlation

analysis_df = prepare_environment_correlation(
    df_canonical_sample_depth,
    ("amundsen_temperature",),
    abundance_column="abundance_ind_L",
    presence_only=False,
)
result = analysis_df
```

Default `presence_only=False` includes every sampled zero-abundance bin. Use
`presence_only=True` only when the user explicitly asks for presence-only,
positive bins, or non-zero values. You must report `n_retained` and `n_zero_abundance`
from `analysis_df.attrs` with the statistical result.

The preparer does not store coefficients in `attrs`. If the user requests a
Pearson, Spearman, or other named statistic, compute the requested coefficient from `analysis_df` after preparation,
in the same analysis call. Return the
coefficient together with `n_retained` and `n_zero_abundance`; do not look for a
coefficient or p-value in the attrs.

## m5/m6 are explicit-only

m5 or m6 may be computed only if the user writes `m5`/`m6`, or clearly asks
for the surface + bottom metric using the first and last 50 m. A generic
station ranking or abundance request is not sufficient.

### Answer template — always state the method explicitly

Whenever you compute a copepod density / abundance / ranking on a UVP file,
**start your answer with a one-line method note** before the table. Examples:

- Explicit m5:
  `Méthode : m5 (Vilgrain & Bourgouin 2026) = (densité moyenne surface 0-50 m + densité moyenne fond max-50 m) / 2, par sample, en ind./L.`
- User override (global sum/sum):
  `Méthode : densité moyenne globale sur tout le profil = somme(objets) / somme(volumes), par sample, en ind./L. (Override demandé par l'utilisateur — non m5.)`
- m6:
  `Méthode : m6 (Vilgrain & Bourgouin 2026) = identique à m5 mais filtré aux copépodes > 2 mm (taille = object_major × acq_pixel), en ind./L.`
- Conversion appliquée:
  Add `· Conversion : × 1000 pour passer de ind./L à ind./m³.` on a second line if you converted.

This note is **not optional** — the user needs to see which formula
produced the numbers in the same screen as the numbers themselves. Do not
put it only inside a code fence or as a column name suffix.

**FORBIDDEN — common LLM improvisation that produces wrong rankings:**

```python
# 🛑 DO NOT WRITE THIS. It is NOT m5. It collapses the whole profile.
station_stats = df.groupby('sample_id').agg(
    cop_objects=('category', 'size'),
    sampled_volume=('sampled_volume', 'sum'),
)
station_stats['density'] = station_stats['cop_objects'] / station_stats['sampled_volume']
```

This shape (`sum(objects) / sum(volume)` over the whole profile) gives a
different metric — global volume-weighted density — and produces a different
top-N. Do not substitute it for either elementary per-bin abundance or an
explicitly requested profile metric.

**REQUIRED — the m5 template for an intermediate `taxa_db` (sampled_volume
already joined):**

```python
from core.copepod_sample_depth import build_canonical_sample_depth

canonical_bins = build_canonical_sample_depth(
    df,
    volume_column="sampled_volume",
)

def m5(grp):
    max_d = grp["depth_bin"].max()
    surf = grp.loc[grp["depth_bin"] <= 50, "abundance_ind_L"].mean()
    bot  = grp.loc[grp["depth_bin"] >= (max_d - 50), "abundance_ind_L"].mean()
    return (surf + bot) / 2

result = (
    canonical_bins.groupby("sample_id").apply(m5).reset_index(name="m5_cop_dens_ind_per_L")
            .sort_values("m5_cop_dens_ind_per_L", ascending=False)
)
```

If the user **explicitly says** "je veux la moyenne sur tout le profil", that
is a separate requested metric. State its exact formula; never label it m5.

If the user joins station-level wording ("top 5 stations"), apply m5 at the
sample level then map back to station; do not collapse to station before
computing density.

---

## 🛑 READ THIS FIRST — m6 (copépodes >2 mm) : filtrer AVANT le groupby

**Pour m6**, le filtre `size_µm > 2000` doit être appliqué **AVANT** le
groupby sur `(sample_id, depth_bin)`. Sinon, des bins avec des copépodes
mais aucun >2 mm comptent comme `n_long = 0` et tirent les moyennes
surface/fond vers le bas → m6 sous-estimé.

**FORBIDDEN — agrégation post-groupby (bug subtil, valeurs trop basses) :**

```python
# 🛑 DO NOT WRITE THIS. n_long = 0 bins contaminent les moyennes.
cop['is_long'] = cop['object_major'] * 73.0 > 2000.0
bins = cop.groupby(['sample_id', 'depth_bin']).agg(
    n_long=('is_long', 'sum'),
    sampled_volume=('sampled_volume', 'first'),
)
bins['dens_long'] = bins['n_long'] / bins['sampled_volume']
# → bins où n_long=0 restent et tirent (surf + bot)/2 vers le bas
```

**REQUIRED — filtre AVANT groupby (template m6 intermédiaire) :**

Suppose `taxa_db.csv` et `taxa_morpho_db.csv` chargés en `df_file_taxa_db`
et `df_file_taxa_morpho_db`. `acq_pixel = 73 µm` pour UVP6 (à confirmer
projet par projet ; n'apparaît pas dans les tables intermédiaires).

```python
import pandas as pd
from core.copepod_taxonomy import copepod_hierarchy_mask

ACQ_PIXEL_UM = 73  # UVP6 Hawke Channel; ask user if different

# Join morpho avec taxa_db pour récupérer depth_bin + sampled_volume
m = df_file_taxa_morpho_db.merge(
    df_file_taxa_db[["sample_id", "object_id", "depth_bin", "sampled_volume",
                     "object_annotation_hierarchy"]],
    on=["sample_id", "object_id"], how="left",
)

cop = m.loc[copepod_hierarchy_mask(m)].copy()
cop["size_um"] = cop["object_major"] * ACQ_PIXEL_UM

# ⚠ Filtre > 2000 µm AVANT le groupby
large = cop[cop["size_um"] > 2000].copy()

large_bins = (
    large.groupby(["sample_id", "depth_bin", "sampled_volume"], as_index=False)
         .size().rename(columns={"size": "n_large"})
)
large_bins["dens_large"] = large_bins["n_large"] / large_bins["sampled_volume"]

def m6(grp):
    max_d = grp["depth_bin"].max()
    surf = grp.loc[grp["depth_bin"] <= 50, "dens_large"].mean()
    bot  = grp.loc[grp["depth_bin"] >= (max_d - 50), "dens_large"].mean()
    return (surf + bot) / 2

result = (
    large_bins.groupby("sample_id").apply(m6).reset_index(name="m6_largecop_dens_ind_per_L")
              .sort_values("m6_largecop_dens_ind_per_L", ascending=False)
)
```

---

## File shape: raw vs intermediate

Two shapes are supported. Detect first, then route.

| Shape | Signal columns | What to do |
|---|---|---|
| **Raw EcoTaxa export** | `fre_major` or `object_major` + `sample_id`, no `sampled_volume` | Call `join_ecotaxa_ecopart` to get `df_ecotaxa_ecopart` (5m-binned `sampled_volume` + all `ecopart_*` columns). Then build the canonical sample-depth table. **Never** hand-roll the merge in `run_pandas`. |
| **Intermediate `taxa_db`** (from `scripts/uvp_metrics_pipeline.py`) | `sample_id` + `depth_bin` + `sampled_volume` + `category` (and no `LPM (...)` column) | The file remains unusable for Copepoda unless it contains the exact `object_annotation_hierarchy` column. If present, build the canonical sample-depth table with `volume_column="sampled_volume"`. |
| **Intermediate `taxa_morpho_db`** | `sample_id` + `object_major` + morphological columns, no `sampled_volume` | Join with `taxa_db` on `(sample_id, object_id)` to recover `depth_bin` + `sampled_volume`, then apply m6 formula. |

---

## Default routing when the user wording is generic

For **"abondance copépodes" / "densité copépodes" / "profils verticaux"**,
use the elementary per-bin columns from `df_canonical_sample_depth`. For a
sample/station summary, ask which aggregation is wanted rather than inventing
one. Never infer m5, m6, or global sum/sum from generic wording.

If the user gives a metric name you do not recognise (anything other than
m1-m6 from the Vilgrain template), ask **one short clarifying question**
listing the 2-3 most likely interpretations before computing.

---

## Common trap — DO NOT do this

```python
# WRONG: collapses the whole profile, ignores the surface/bottom split.
station_stats = df.groupby('sample_id').agg(
    cop_objects=('category', 'size'),
    sampled_volume=('sampled_volume', 'sum'),
)
station_stats['m5'] = station_stats['cop_objects'] / station_stats['sampled_volume']
```

This is the most common improvisation when the LLM sees "densité moyenne par
sample". It is **not** m5. The correct shape always has a per-bin density
first, then two means (surface ≤ 50m and bottom ≥ max-50m), then their
average — see the template in the m5 section below.

---

## Key columns to identify first

| Column | Meaning | Unit |
|---|---|---|
| `fre_major` or `object_major` | Length of the object major axis in pixels | pixels |
| `fre_area` or `object_area` | Object area in pixels² | px² |
| `fre_esd` or `object_esd` | Equivalent spherical diameter in pixels | pixels |
| `acq_pixel` | Size of one pixel in the imaged plane | µm/pixel |
| `acq_volimage` | Water volume per image | L |
| `sample_id` | Profile identifier (= join key with EcoPart) | — |
| `obj_depth_min` or `object_depth_min` | Object depth | m |
| `txo_display_name` or `object_annotation_category` | Predicted or validated taxon | — |

**Step 0 — extract acquisition constants:**
```python
result = df[["acq_pixel", "acq_volimage"]].dropna().iloc[0]
```
If `acq_pixel` is absent, use `process_pixel` or note that µm conversion is not possible.

---

## Metric m5 — Copepod density (ind/L)

**Definition:** mean copepod density in the first 50m AND the last 50m of the water column, weighted by sampled volume.

**Requires EcoPart** for `sampled_volume`. If EcoPart is not loaded, ask the user to load it.

### Pre-step — Join EcoTaxa ↔ EcoPart before m5 (MANDATORY)

Before running the m5 template, call `join_ecotaxa_ecopart` to obtain the joined table (`df_ecotaxa_ecopart`) with `depth_bin`, `ecopart_Sampled volume [L]`, and all `ecopart_*` columns per object. The tool handles key detection (`sample_id` / `sample_profileid` / `obj_orig_id` / `sample_cruise`), 5m binning, `ecopart_` prefixing, session storage, and campaign-mismatch / partial-depth-coverage warnings. **Never** re-implement this merge in `run_pandas` — you lose those guarantees and the join becomes untraceable.

### Full m5 template (starting from `df_ecotaxa_ecopart`)

```python
from core.copepod_sample_depth import build_canonical_sample_depth

df = df_ecotaxa_ecopart  # joined table from join_ecotaxa_ecopart
canonical_bins = build_canonical_sample_depth(df)

# ── 6. m5: mean surface (0-50m) + bottom (last 50m) ──────────────────────
def m5_per_sample(grp):
    max_depth = grp["depth_bin"].max()
    surface   = grp[grp["depth_bin"] <= 50]["abundance_ind_L"].mean()
    bottom    = grp[grp["depth_bin"] >= (max_depth - 50)]["abundance_ind_L"].mean()
    return (surface + bottom) / 2

result = canonical_bins.groupby("sample_id").apply(m5_per_sample).reset_index()
result.columns = ["sample_id", "m5_cop_dens_ind_per_L"]
```

### m5 template for intermediate `taxa_db` (sampled_volume already joined)

```python
from core.copepod_sample_depth import build_canonical_sample_depth

canonical_bins = build_canonical_sample_depth(
    df,
    volume_column="sampled_volume",
)

def m5(grp):
    max_d = grp["depth_bin"].max()
    surf = grp.loc[grp["depth_bin"] <= 50, "abundance_ind_L"].mean()
    bot  = grp.loc[grp["depth_bin"] >= (max_d - 50), "abundance_ind_L"].mean()
    return (surf + bot) / 2

result = (
    canonical_bins.groupby("sample_id").apply(m5).reset_index()
            .rename(columns={0: "m5_cop_dens_ind_per_L"})
            .sort_values("m5_cop_dens_ind_per_L", ascending=False)
)
```

---

## Metric m6 — Large copepod density >2mm (ind/L)

**Definition:** same calculation as m5 but filtered to copepods whose length exceeds 2000 µm (adult *Calanus* in Arctic/sub-Arctic).

**Requires `acq_pixel`** to convert pixels to µm.

```python
# ── After computing cop_bins (see m5 above) ───────────────────────────────
major_col = "fre_major" if "fre_major" in df.columns else "object_major"

# Retrieve acq_pixel (µm/pixel)
acq_pixel_um = df["acq_pixel"].dropna().iloc[0]  # e.g. 73.0 µm/pixel

# Add size in µm
df_cop["size_um"] = df_cop[major_col] * acq_pixel_um

# Filter >2000 µm
df_large = df_cop[df_cop["size_um"] > 2000].copy()

# Density per bin (same logic as m5)
large_bins = df_large.groupby(["sample_id", "depth_bin", "Sampled volume [L]"])["count"].sum().reset_index()
large_bins["large_cop_dens"] = large_bins["count"] / large_bins["Sampled volume [L]"]

def m6_per_sample(grp):
    max_depth = grp["depth_bin"].max()
    surface   = grp[grp["depth_bin"] <= 50]["large_cop_dens"].mean()
    bottom    = grp[grp["depth_bin"] >= (max_depth - 50)]["large_cop_dens"].mean()
    return (surface + bottom) / 2

result_m6 = large_bins.groupby("sample_id").apply(m6_per_sample).reset_index()
result_m6.columns = ["sample_id", "m6_large_cop_dens_ind_per_L"]
```

---

## m4 — Morpho-Shannon index (not computable without reference data)

m4 quantifies the morphological diversity of particles via 5 clusters (dark, elongated, fluffy, flakes, agglomerated) defined in a reference PCA space (Trudnowska et al. 2021).

**Not computable here**: requires `morpho_diversity_ref.csv` and `centers_init_ref.csv` from the Vilgrain/Bourgouin 2026 project. If the user has them, they can be loaded and the calculation is possible.

---

## Interpretation rules

- `fre_*` = LOKI/UVP6 export; `object_*` = UVP5/ZooScan export → same logic, different column names
- `acq_pixel` is in **µm/pixel** in recent UVP exports — always verify the unit
- One profile = one `sample_id` = one UVP cast
- Concentrations are in **ind/L**, not ind/m³ (unlike raw EcoTaxa counts)
- Without `sampled_volume` from EcoPart, only a **raw count** is obtainable, not a density
