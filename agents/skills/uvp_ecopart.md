---
name: uvp_ecopart
version: 1.0.0
triggers:
  - Loaded file is detected as a UVP EcoPart export
forbidden_when:
  - Loaded data is not an EcoPart export
requires:
  - "dataset:uvp_ecopart"
next_tool: run_pandas
max_tokens: 1400
---

# Skill: uvp_ecopart

You just loaded a **UVP EcoPart file** (columns `LPM (...)` + `Sampled volume [L]`).
This skill provides the keys for interpreting it and computing metrics m1, m2, m3 (Vilgrain & Bourgouin 2026).

---

## EcoPart file structure

| Column | Meaning | Unit |
|---|---|---|
| `Profile` | Profile/cast identifier (= `sample_id` in EcoTaxa) | — |
| `Depth [m]` | Bin depth | m |
| `Sampled volume [L]` | Water volume sampled in this bin | L |
| `LPM (64-128 µm) [# l-1]` … `LPM (4.1-8.19 mm) [# l-1]` | Particle density by size class | #/L |
| `LPM biovolume (64-128 µm) [mm3 l-1]` … | Particle biovolume by size class | mm³/L |

**All particle metrics (m1-m3) are computed on the first 200 metres only.**

---

## Metric m1 — Mean particle density (#/L)

**Definition:** mean number of particles per litre, averaged over 0-200m per cast.

Size classes used: `64-128 µm` to `4.1-8.19 mm` (8 classes).

```python
import pandas as pd

# LPM density columns (exclude biovolume)
lpm_dens_cols = [c for c in df.columns if c.startswith("LPM (") and "# l-1" in c
                 and "biovolume" not in c.lower()]

# Filter 0-200m
df200 = df[df["Depth [m]"] < 200].copy()

# Total particles per bin = sum of densities × sampled volume
df200["nb_tot"] = df200[lpm_dens_cols].sum(axis=1) * df200["Sampled volume [L]"]

# m1 per profile = sum(nb_tot) / sum(volume)
result = df200.groupby("Profile").apply(
    lambda g: g["nb_tot"].sum() / g["Sampled volume [L]"].sum()
).reset_index()
result.columns = ["sample_id", "m1_part_dens_per_L"]
```

---

## Metric m2 — Mean particle biovolume (mm³/L)

**Definition:** total particle volume in mm³ per litre, averaged over 0-200m per cast.

```python
# LPM biovolume columns
lpm_biovol_cols = [c for c in df.columns if "LPM biovolume" in c and "mm3 l-1" in c]

df200 = df[df["Depth [m]"] < 200].copy()
df200["biovol_tot"] = df200[lpm_biovol_cols].sum(axis=1) * df200["Sampled volume [L]"]

result = df200.groupby("Profile").apply(
    lambda g: g["biovol_tot"].sum() / g["Sampled volume [L]"].sum()
).reset_index()
result.columns = ["sample_id", "m2_part_biovol_mm3_per_L"]
```

---

## Metric m3 — Size spectrum slope

**Definition:** slope of the log(density) ~ log(size) relationship — ecosystem functionality indicator. Typical range -5 to -2. Closer to 0 = more large particles = productive ecosystem.

Classes used: `128-256 µm` to `2.05-4.1 mm` (6 classes, excluding extremes).

```python
import numpy as np
from scipy import stats

# Median value of each size class (µm)
size_midpoints = {
    "LPM (128-256 µm) [# l-1]":       192,
    "LPM (256-512 µm) [# l-1]":       384,
    "LPM (0.512-1.02 mm) [# l-1]":    766,
    "LPM (1.02-2.05 mm) [# l-1]":    1535,
    "LPM (2.05-4.1 mm) [# l-1]":     3075,
}
size_widths = {
    "LPM (128-256 µm) [# l-1]":       128,
    "LPM (256-512 µm) [# l-1]":       256,
    "LPM (0.512-1.02 mm) [# l-1]":    512,
    "LPM (1.02-2.05 mm) [# l-1]":    1020,
    "LPM (2.05-4.1 mm) [# l-1]":     2050,
}

df200 = df[df["Depth [m]"] < 200].copy()
slopes = {}
for profile, grp in df200.groupby("Profile"):
    rows = []
    for col, mid in size_midpoints.items():
        if col not in grp.columns:
            continue
        dens = grp[col].mean()
        width = size_widths[col]
        dens_norm = dens / width  # normalise by bin width
        if dens_norm > 0:
            rows.append((np.log(mid), np.log(dens_norm)))
    if len(rows) >= 3:
        x, y = zip(*rows)
        slope, _, _, pval, _ = stats.linregress(x, y)
        slopes[profile] = slope if pval < 0.05 else None

result = pd.DataFrame(list(slopes.items()), columns=["sample_id", "m3_slope"])
```

---

## m4 — Morpho-Shannon index (not computable from EcoPart alone)

m4 is computed from **EcoTaxa images** (particle morphology), not from EcoPart.
See skill `uvp_ecotaxa` and the Vilgrain & Bourgouin 2026 report for the full procedure.

---

## Join with EcoTaxa for m5/m6

EcoPart provides `sampled_volume` needed to compute copepod densities.
Join key: `Profile` (EcoPart) = `sample_id` (EcoTaxa) + `depth_bin` (rounded to 5m).

```python
# Prepare EcoPart for the join
df["depth_bin"] = (df["Depth [m]"] // 5) * 5 + 2.5
df_ecopart_join = df[["Profile", "depth_bin", "Sampled volume [L]"]].rename(
    columns={"Profile": "sample_id"}
)
# → use df_ecopart_join in the m5/m6 template in skill uvp_ecotaxa
```

---

## Interpretation rules

- Always filter to `Depth [m] < 200` for m1-m3 (depth bias otherwise)
- `Sampled volume [L]` ≈ 100L per 5m bin for a UVP6 at normal descent speed
- If `Sampled volume [L]` is very low (<10L) in a bin, the density estimate is unreliable
- Columns `LPM (1-2 µm)` and `LPM (2-4 µm)` are often unreliable — do not use them for m1-m3
