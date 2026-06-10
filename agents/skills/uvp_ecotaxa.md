# Skill: uvp_ecotaxa

You just loaded a **UVP EcoTaxa file** (columns `fre_*` or `object_*` + `sample_id`).
This skill provides the keys for interpreting it and computing metrics m5 and m6 (Vilgrain & Bourgouin 2026).

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

### Full m5 template (EcoTaxa + EcoPart already loaded in `df_ecopart`)

```python
import pandas as pd
import numpy as np

# ── 1. Identify columns based on file schema ───────────────────────────────
depth_col     = "obj_depth_min" if "obj_depth_min" in df.columns else "object_depth_min"
category_col  = "txo_display_name" if "txo_display_name" in df.columns else "object_annotation_category"

# ── 2. Compute depth bins (5m intervals) ──────────────────────────────────
df["depth_bin"] = (df[depth_col] // 5) * 5 + 2.5

# ── 3. Filter copepods (predicted or validated) ───────────────────────────
copepod_keywords = ["Copepoda", "Calanoida", "Calanus", "Metridia",
                    "Paraeuchaeta", "Heterorhabdidae"]
df_cop = df[df[category_col].str.contains("|".join(copepod_keywords), na=False, case=False)].copy()

# ── 4. Join with EcoPart to get sampled_volume ────────────────────────────
# df_ecopart must have columns: sample_id, depth_bin (rounded to 5m), Sampled volume [L]
df_ecopart["depth_bin"] = (df_ecopart["Depth [m]"] // 5) * 5 + 2.5
df_cop = df_cop.merge(
    df_ecopart[["sample_id", "depth_bin", "Sampled volume [L]"]].rename(columns={"Profile": "sample_id"})
    if "Profile" in df_ecopart.columns else
    df_ecopart[["sample_id", "depth_bin", "Sampled volume [L]"]],
    on=["sample_id", "depth_bin"], how="left"
)

# ── 5. Density per bin ─────────────────────────────────────────────────────
df_cop["count"] = 1
cop_bins = df_cop.groupby(["sample_id", "depth_bin", "Sampled volume [L]"])["count"].sum().reset_index()
cop_bins["cop_dens"] = cop_bins["count"] / cop_bins["Sampled volume [L]"]

# ── 6. m5: mean surface (0-50m) + bottom (last 50m) ──────────────────────
def m5_per_sample(grp):
    max_depth = grp["depth_bin"].max()
    surface   = grp[grp["depth_bin"] <= 50]["cop_dens"].mean()
    bottom    = grp[grp["depth_bin"] >= (max_depth - 50)]["cop_dens"].mean()
    return (surface + bottom) / 2

result = cop_bins.groupby("sample_id").apply(m5_per_sample).reset_index()
result.columns = ["sample_id", "m5_cop_dens_ind_per_L"]
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
