# Skill: uvp_ecotaxa

Tu viens de charger un fichier **EcoTaxa UVP** (colonnes `fre_*` ou `object_*` + `sample_id`).
Ce skill te donne les clés pour l'interpréter et calculer les métriques m5 et m6 (Vilgrain & Bourgouin 2026).

---

## Colonnes clés à identifier en premier

| Colonne | Signification | Unité |
|---|---|---|
| `fre_major` ou `object_major` | Longueur du grand axe de l'objet en pixels | pixels |
| `fre_area` ou `object_area` | Aire de l'objet en pixels² | px² |
| `fre_esd` ou `object_esd` | Diamètre équivalent sphérique en pixels | pixels |
| `acq_pixel` | Taille d'un pixel dans le plan imagé | µm/pixel |
| `acq_volimage` | Volume d'eau par image | L |
| `sample_id` | Identifiant du profil (= clé de jointure avec EcoPart) | — |
| `obj_depth_min` ou `object_depth_min` | Profondeur de l'objet | m |
| `txo_display_name` ou `object_annotation_category` | Taxon prédit ou validé | — |

**Étape 0 — extraire les constantes d'acquisition :**
```python
result = df[["acq_pixel", "acq_volimage"]].dropna().iloc[0]
```
Si `acq_pixel` est absent, utilise `process_pixel` ou note que la conversion µm est impossible.

---

## Metric m5 — Densité de copépodes (ind/L)

**Définition :** densité moyenne de copépodes dans les 50 premiers mètres ET les 50 derniers mètres de la colonne d'eau, pondérée par le volume échantillonné.

**Nécessite EcoPart** pour `sampled_volume`. Si EcoPart n'est pas chargé, demande à l'utilisateur de le charger.

### Template complet m5 (EcoTaxa + EcoPart déjà chargé dans `df_ecopart`)

```python
import pandas as pd
import numpy as np

# ── 1. Identifier les colonnes selon le schéma du fichier ──────────────────
depth_col     = "obj_depth_min" if "obj_depth_min" in df.columns else "object_depth_min"
category_col  = "txo_display_name" if "txo_display_name" in df.columns else "object_annotation_category"

# ── 2. Calculer les depth bins (intervalles de 5m) ─────────────────────────
df["depth_bin"] = (df[depth_col] // 5) * 5 + 2.5

# ── 3. Filtrer les copépodes (prédits ou validés) ──────────────────────────
copepod_keywords = ["Copepoda", "Calanoida", "Calanus", "Metridia",
                    "Paraeuchaeta", "Heterorhabdidae"]
df_cop = df[df[category_col].str.contains("|".join(copepod_keywords), na=False, case=False)].copy()

# ── 4. Joindre avec EcoPart pour obtenir sampled_volume ───────────────────
# df_ecopart doit avoir les colonnes : sample_id, depth_bin (arrondi 5m), Sampled volume [L]
df_ecopart["depth_bin"] = (df_ecopart["Depth [m]"] // 5) * 5 + 2.5
df_cop = df_cop.merge(
    df_ecopart[["sample_id", "depth_bin", "Sampled volume [L]"]].rename(columns={"Profile": "sample_id"})
    if "Profile" in df_ecopart.columns else
    df_ecopart[["sample_id", "depth_bin", "Sampled volume [L]"]],
    on=["sample_id", "depth_bin"], how="left"
)

# ── 5. Densité par bin ─────────────────────────────────────────────────────
df_cop["count"] = 1
cop_bins = df_cop.groupby(["sample_id", "depth_bin", "Sampled volume [L]"])["count"].sum().reset_index()
cop_bins["cop_dens"] = cop_bins["count"] / cop_bins["Sampled volume [L]"]

# ── 6. m5 : moyenne surface (0-50m) + fond (last 50m) ─────────────────────
def m5_per_sample(grp):
    max_depth = grp["depth_bin"].max()
    surface   = grp[grp["depth_bin"] <= 50]["cop_dens"].mean()
    bottom    = grp[grp["depth_bin"] >= (max_depth - 50)]["cop_dens"].mean()
    return (surface + bottom) / 2

result = cop_bins.groupby("sample_id").apply(m5_per_sample).reset_index()
result.columns = ["sample_id", "m5_cop_dens_ind_per_L"]
```

---

## Metric m6 — Densité de grands copépodes >2mm (ind/L)

**Définition :** même calcul que m5 mais filtré sur les copépodes dont la longueur dépasse 2000 µm (adultes *Calanus* dans l'Arctique/sub-Arctique).

**Requiert `acq_pixel`** pour convertir les pixels en µm.

```python
# ── Après avoir calculé cop_bins (voir m5 ci-dessus) ──────────────────────
major_col = "fre_major" if "fre_major" in df.columns else "object_major"

# Récupérer acq_pixel (µm/pixel)
acq_pixel_um = df["acq_pixel"].dropna().iloc[0]  # ex : 73.0 µm/pixel

# Ajouter taille en µm
df_cop["size_um"] = df_cop[major_col] * acq_pixel_um

# Filtrer >2000 µm
df_large = df_cop[df_cop["size_um"] > 2000].copy()

# Densité par bin (même logique que m5)
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

## m4 — Indice morpho-Shannon (non calculable sans données de référence)

m4 quantifie la diversité morphologique des particules via 5 clusters (dark, elongated, fluffy, flakes, agglomerated) définis dans un espace PCA de référence (Trudnowska et al. 2021).

**Non calculable ici** : il faut les fichiers `morpho_diversity_ref.csv` et `centers_init_ref.csv` du projet Vilgrain/Bourgouin 2026. Si l'utilisateur les a, ils peuvent être chargés et le calcul est possible.

---

## Règles d'interprétation

- `fre_*` = export LOKI/UVP6 ; `object_*` = export UVP5/ZooScan → même logique, colonnes différentes
- `acq_pixel` est en **µm/pixel** dans les exports UVP récents — toujours vérifier l'unité
- Un profil = un `sample_id` = un cast UVP
- Les concentrations sont en **ind/L**, pas ind/m³ (contrairement à l'EcoTaxa seul)
- Sans `sampled_volume` d'EcoPart, on ne peut obtenir qu'un **comptage brut**, pas une densité
