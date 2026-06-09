# Skill: uvp_ecopart

Tu viens de charger un fichier **EcoPart UVP** (colonnes `LPM (...)` + `Sampled volume [L]`).
Ce skill te donne les clés pour l'interpréter et calculer les métriques m1, m2, m3 (Vilgrain & Bourgouin 2026).

---

## Structure du fichier EcoPart

| Colonne | Signification | Unité |
|---|---|---|
| `Profile` | Identifiant du profil/cast (= `sample_id` dans EcoTaxa) | — |
| `Depth [m]` | Profondeur du bin | m |
| `Sampled volume [L]` | Volume d'eau échantillonné dans ce bin | L |
| `LPM (64-128 µm) [# l-1]` … `LPM (4.1-8.19 mm) [# l-1]` | Densité de particules par classe de taille | #/L |
| `LPM biovolume (64-128 µm) [mm3 l-1]` … | Biovolume de particules par classe de taille | mm³/L |

**Toutes les métriques particules (m1-m3) sont calculées sur les 200 premiers mètres uniquement.**

---

## Metric m1 — Densité moyenne de particules (#/L)

**Définition :** nombre moyen de particules par litre, moyenné sur 0-200m par cast.

Classes de taille utilisées : `64-128 µm` à `4.1-8.19 mm` (8 classes).

```python
import pandas as pd

# Colonnes LPM densité (hors biovolume)
lpm_dens_cols = [c for c in df.columns if c.startswith("LPM (") and "# l-1" in c
                 and "biovolume" not in c.lower()]

# Filtrer 0-200m
df200 = df[df["Depth [m]"] < 200].copy()

# Nombre total de particules par bin = somme des densités × volume échantillonné
df200["nb_tot"] = df200[lpm_dens_cols].sum(axis=1) * df200["Sampled volume [L]"]

# m1 par profil = somme nb_tot / somme volume
result = df200.groupby("Profile").apply(
    lambda g: g["nb_tot"].sum() / g["Sampled volume [L]"].sum()
).reset_index()
result.columns = ["sample_id", "m1_part_dens_per_L"]
```

---

## Metric m2 — Biovolume moyen de particules (mm³/L)

**Définition :** volume total de particules en mm³ par litre, moyenné sur 0-200m par cast.

```python
# Colonnes LPM biovolume
lpm_biovol_cols = [c for c in df.columns if "LPM biovolume" in c and "mm3 l-1" in c]

df200 = df[df["Depth [m]"] < 200].copy()
df200["biovol_tot"] = df200[lpm_biovol_cols].sum(axis=1) * df200["Sampled volume [L]"]

result = df200.groupby("Profile").apply(
    lambda g: g["biovol_tot"].sum() / g["Sampled volume [L]"].sum()
).reset_index()
result.columns = ["sample_id", "m2_part_biovol_mm3_per_L"]
```

---

## Metric m3 — Pente du spectre de taille

**Définition :** pente de la relation log(densité) ~ log(taille) — indicateur de fonctionnalité écosystémique. Valeur typique entre -5 et -2. Plus proche de 0 = plus de grosses particules = écosystème productif.

Classes utilisées : `128-256 µm` à `2.05-4.1 mm` (6 classes, sans les extrêmes).

```python
import numpy as np
from scipy import stats

# Valeur médiane de chaque classe de taille (µm)
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
        dens_norm = dens / width  # normaliser par la largeur du bin
        if dens_norm > 0:
            rows.append((np.log(mid), np.log(dens_norm)))
    if len(rows) >= 3:
        x, y = zip(*rows)
        slope, _, _, pval, _ = stats.linregress(x, y)
        slopes[profile] = slope if pval < 0.05 else None

result = pd.DataFrame(list(slopes.items()), columns=["sample_id", "m3_slope"])
```

---

## m4 — Indice morpho-Shannon (non calculable depuis EcoPart seul)

m4 se calcule depuis les **images EcoTaxa** (morphologie des particules), pas depuis EcoPart.
Voir le skill `uvp_ecotaxa` et le rapport Vilgrain & Bourgouin 2026 pour la procédure complète.

---

## Jointure avec EcoTaxa pour m5/m6

EcoPart est la source de `sampled_volume` pour calculer les densités de copépodes.
Clé de jointure : `Profile` (EcoPart) = `sample_id` (EcoTaxa) + `depth_bin` (arrondi 5m).

```python
# Préparer EcoPart pour la jointure
df["depth_bin"] = (df["Depth [m]"] // 5) * 5 + 2.5
df_ecopart_join = df[["Profile", "depth_bin", "Sampled volume [L]"]].rename(
    columns={"Profile": "sample_id"}
)
# → utiliser df_ecopart_join dans le template m5/m6 du skill uvp_ecotaxa
```

---

## Règles d'interprétation

- Toujours filtrer à `Depth [m] < 200` pour m1-m3 (biais de profondeur sinon)
- `Sampled volume [L]` ≈ 100L par bin de 5m pour un UVP6 à descente normale
- Si `Sampled volume [L]` est très bas (<10L) dans un bin, la densité est peu fiable
- Les colonnes `LPM (1-2 µm)` et `LPM (2-4 µm)` sont souvent peu fiables — ne pas les utiliser pour m1-m3
