---
name: graph_writer
version: 1.0.0
triggers:
  - A visual request or follow-up visual edit must be rendered when its selected table is non-empty
forbidden_when:
  - The selected table is empty or no visual output was requested
requires:
  - "intent:visual"
next_tool: run_graph
max_tokens: 11500
size_exemption: The writer owns one executable graph-contract vocabulary shared by runtime validation across all chart families; its full body is delivered with a manifest-governed cap instead of the generic tool truncation.
---

# Skill: graph_writer

You must write correct and complete code to produce the planned visual output.

## Execution truth

- If the selected table has zero rows, stop: report the empty result and do not
  write or execute graph code.
  - Never invent or reuse an artifact URL. Only relay the exact artifact returned
  by a successful `run_graph` call for the current request.
- On a correctable `run_graph` contract/quality block, no image exists: revise
  from its diagnostic and retry once with the same dataframe; otherwise surface
  the final diagnostic. For data, source, authorization, or column errors,
  surface the failure directly.
- Use only values present in the explicitly selected source variable. Never
  hardcode coordinates, identifiers, counts, or substitute columns from another
  source.
- A newly named zone supersedes the prior figure scope: resolve/filter it and
  render it; never reuse the former zone.
- The user's scientific question and requested framing are binding: make the requested state of the data visible. Preserve explicit population, measure,
  comparison/grouping, scope, encoding, and labels. Never silently substitute
  a generic/easier graph; if impossible, state the conflict and ask one focused
  question.

## Visual output

You must write correct and complete matplotlib code.

## Base template

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig, ax = plt.subplots(figsize=(10, 6))
fig.patch.set_facecolor("#ffffff")
ax.set_facecolor("#f8fafc")
ax.tick_params(colors="#334155")

# --- your code here ---

ax.set_title("<descriptive title>")
ax.set_xlabel("<X axis label>")
ax.set_ylabel("<Y axis label>")
plt.tight_layout()
```

## Mandatory rules

- Always use `matplotlib.use("Agg")` — no interactive display
- Use the single light theme below for every graph and map. Never select a dark
  matplotlib style or use white text/markers as a workaround for a dark background.
- Always use `fig, ax = plt.subplots()` — never call `plt.show()`
- Always define `title`, `xlabel`, `ylabel`
- Keep figures readable: `figsize` must stay at or below `(16, 14)`. If a heatmap or ordination needs more space, aggregate or filter groups rather than increasing figure height.
- Always include a legend or labels. Multi-series: `ax.legend()` with a variable title. For station maps, `station_id` is the default map label because it is concise; use `original_id` or `sample_id` only when the user explicitly requests it. Do not suppress station labels based only on their count: if crowded, user can request another extent/presentation. A single series needs a colorbar label or descriptive title. For >15 non-station levels, use top 12 + "Other", a continuous scale, or a note. A `vertical_profile` may show 16–30 profiles with `ax.legend(ncol=2)`; above 30, filter or aggregate.
- Axis labels must stay readable: never show more than 50 visible tick labels on either axis. For heatmaps with many stations/samples, keep the top 40 groups by abundance or display sparse ticks.
- Taxon tick labels must be short: if labels contain taxonomy paths such as `Animalia | Arthropoda | ...`, display only the terminal taxon name; truncate labels longer than 35 characters with an ellipsis.
- For long labels (taxon names): `ax.tick_params(axis='x', rotation=45)`
- For horizontal bar charts when there are many categories (> 10): use `ax.barh()`
- Never call `plt.savefig()` — the system captures the figure automatically
- Never invent or rewrite the image URL in the final answer. Return the exact image markdown emitted by `run_graph`; do not replace it with `/graphs/graph.png`.
- After the figure code, set a string variable named `graph_explanation` to a neutral description limited to axes and source. No reading of the chart, observations, priorities, or interpretation cues. The assistant ignores this field when replying to the user — it is kept only as metadata for the tool layer.
- For multi-source graphs, never plot directly from bare `df`. `df` is only the latest active table. First build `plot_df` explicitly from named source DataFrames such as `df_ecotaxa_ecopart`, `df_ecotaxa_ecopart_105`, `df_ctd`, `df_bio_oracle`, `df_ogsl`, or `df_sql`.
- Treat station, sample, cast, profile, analysis, taxon, and project identifiers as labels, not numbers. Never cast identifiers such as `STATION_NAME`, `SAMPLE_ID`, `ANALYSIS_ID`, `CAST_NUMBER`, or `profile_id` with `int()` / `float()` just to filter. Normalize both sides of identifier comparisons with `.astype(str).str.strip()`.
- After every filtering step that creates `plot_df`, validate that rows remain before plotting:
  `if plot_df.empty: raise ValueError("No rows remain after filtering; check identifier type normalization and filter criteria.")`
- Before plotting numeric axes, coerce only the plotted measurement columns with `pd.to_numeric(..., errors="coerce")`, then drop missing values from all plotted columns. Validate again that `plot_df` is not empty after this drop.

## Clarté et information visuelle (priorité)

Un graphe doit se lire d'un coup d'œil : le lecteur saisit l'information sans
effort. La clarté prime sur l'esthétique.

- **Titre porteur de sens** : décrit ce que montre la figure et sur quoi
  (variable, zone, période), pas juste « Graphique ».
- **Axes avec unités** : `xlabel`/`ylabel` nomment la variable ET son unité —
  `Profondeur (m)`, `Abondance (ind./m³)`, `Température (°C)`.
- **Couleur = information, pas décoration** : n'encode par la couleur qu'une
  variable réelle (zone, taxon, statut, valeur) ; sinon une seule couleur.
  Échelle continue perceptuellement uniforme (`viridis`) pour une valeur.
- **Labels lisibles** : jamais de chevauchement — rotation (`rotation=45`),
  troncature des noms longs (taxon terminal, ≤ 35 car.), et pas plus de ~50
  ticks visibles par axe (sinon agrège ou espace les ticks).
- **Légende toujours présente et détaillée** : multi-séries → `ax.legend()` ;
  cartes de stations → appliquer la règle de labels ci-dessous ; heatmap ou
  scatter unique → titre d'axe + colorbar. Au-delà de ~12 séries, top N +
  « Autres », échelle continue, ou note de légende.
- **Densité de points (overplotting)** : quand les points se superposent
  (scatter, carte à nombreuses stations), rends la distribution visible —
  transparence (`alpha=0.3–0.6`), marqueurs plus petits, ou agrégation
  (`hexbin`, densité 2D, comptes par cellule). Jamais un amas opaque où le signal
  disparaît.
- **Mettre en avant le signal** : trie les catégories par valeur, ordonne
  temps/profondeur logiquement, retire le superflu (grilles lourdes, bordures).
- **Comparabilité** : échelles cohérentes entre panneaux ; ne tronque pas un axe
  numérique sans le signaler.

## Grant-ready standard (all visuals)

Every visual is a concise evidence figure suitable for insertion into a research
proposal, report, or PDF at its final size. Apply this standard to every graph,
map, profile, and analytical visual without waiting for a keyword.

- Keep only the evidence needed to answer the request: one scientific message,
  one concise title, labelled axes with units, and a legend only when it decodes
  a real visual encoding. Use no decorative overlays, dashboard furniture, or
  technical status badges.
- Make every text element legible at 100% viewing size. If labels or legends do
  not fit, shorten, aggregate, use sparse ticks, or split the comparison; never
  solve crowding by making the figure harder to read.
- Do not use colour alone to convey a category, status, or comparison. Pair it
  with a label, marker shape, line style, hatch, or direct annotation when that
  distinction is needed to interpret the figure.
- For regional maps, use the exact requested geometry and a proportional data
  extent. Add a small locator inset only when the reader needs wider geographic
  context; do not use a world view as decoration.
- For a follow-up visual edit, reuse the active selection and preserve its
  scientific meaning. Modify only the requested extent, context, encoding, or
  layout; re-query only when the requested geographic/data scope truly changes.

## Executable graph contract (mandatory)

Every visual must define `graph_contract`. Rendering is blocked when it is
missing or disagrees with the actual matplotlib axes/artists. Use exactly these
fields: `"kind"`, `"axes"`, `"inverted_axes"`, `"mappings"`,
`"zero_policy"`, and `"source_variables"`.

For a visual outside the four specialised families (bar, line, scatter, histogram,
boxplot, heatmap, time series, area, bubble, pie — all treated as `"generic"`):

```python
graph_contract = {
    "kind": "generic",  # also accepts: "bar","line","scatter","heatmap","time_series","histogram","boxplot"
    "axes": [{"axis_index": 0, "x": "<x role>", "y": "<y role>"}],
    "inverted_axes": [],
    "mappings": {},
    "zero_policy": {"mode": "include", "artist_gid": None},
    "source_variables": ["<actual plotted columns>"],
}
```

### Vertical abundance profile

Invert only depth y. `vertical_profile` requires ind./L or ind./m³; raw counts
use `generic` with real fields and units. For a French abundance column, keep
the real name in `source_variables` but declare `abundance_ind_L` or
`abundance_ind_m3` in the contract.
When a prior calculation produced a persistent table, use that exact named table
instead of recalculating abundance inside the graph code. For 16–30 profiles,
use a compact multi-column legend; do not create a one-column legend.

```python
ax.plot(plot_df["abundance_ind_L"], plot_df["depth_m"])
ax.invert_yaxis()
graph_contract = {
    "kind": "vertical_profile",
    "axes": [{"axis_index": 0, "x": "abundance_ind_L", "y": "depth_m"}],
    "inverted_axes": [{"axis_index": 0, "axis": "y"}],
    "mappings": {},
    "zero_policy": {"mode": "include", "artist_gid": None},
    "source_variables": ["abundance_ind_L", "depth_m"],
}
```

### Independent environmental relationships

Create separate subplots without `sharex` or `sharey`. All abundance axes stay
normal.

```python
fig, axes = plt.subplots(1, 3, figsize=(15, 5))
graph_contract = {
    "kind": "environment_relationships",
    "axes": [
        {"axis_index": 0, "x": "temperature", "y": "abundance_ind_L"},
        {"axis_index": 1, "x": "salinity", "y": "abundance_ind_L"},
        {"axis_index": 2, "x": "oxygen", "y": "abundance_ind_L"},
    ],
    "inverted_axes": [],
    "mappings": {},
    "zero_policy": {"mode": "include", "artist_gid": None},
    "source_variables": ["temperature", "salinity", "oxygen", "abundance_ind_L"],
}
```

### Temperature–salinity sample–depth diagram

The non-zero collection carries size and depth colour. Distinguish stations by
shape or facet. Put sampled zeros in a separate hollow collection.

```python
ts_points = ax.scatter(x, y, s=sizes, c=depth, cmap="viridis")
ts_points.set_gid("ts_points")
station_shapes = ax.scatter([], [], marker="s")
station_shapes.set_gid("station_shapes")
zero_points = ax.scatter(zero_x, zero_y, facecolors="none", edgecolors="#475569")
zero_points.set_gid("zero_abundance")
graph_contract = {
    "kind": "temperature_salinity",
    "axes": [{"axis_index": 0, "x": "salinity", "y": "temperature"}],
    "inverted_axes": [],
    "mappings": {
        "size": {"variable": "abundance_ind_L", "artist_gid": "ts_points"},
        "color": {"variable": "depth_m", "artist_gid": "ts_points"},
        "station": {"variable": "station", "artist_gid": "station_shapes"},
    },
    "zero_policy": {"mode": "hollow", "artist_gid": "zero_abundance"},
    "source_variables": ["salinity", "temperature", "abundance_ind_L", "depth_m", "station"],
}
```

### Choosing the map kind

There are exactly two valid `graph_contract["kind"]` values for a **geographic map**
with data points. Never emit `kind: "map"` or `kind: "scatter"` for a geographic
map — use one of the two below. (`"scatter"` is valid for non-geographic scatter
plots and resolves to `"generic"`.)

- **`station_map`** — sample positions, and any encoding that is **not**
  measured abundance: number of samples per position, taxa richness
  (`n_taxa`), counts, presence. `size`/`color` are optional and map to the
  **real** variable name.
- **`abundance_environment_map`** — only when `size` genuinely encodes
  `abundance_ind_L` and `color` encodes an environmental variable.

**Never rename a count or a richness to `abundance_ind_L` to satisfy the
contract.** If the user asked for positions / number of samples / number of
taxa, use `station_map` with that variable — inventing an abundance column is a
data-integrity violation.

### EcoTaxa profile / cast map

For `df_ecotaxa_profile_map`, draw **one point per profile**. Its required
columns are `profile_id`, `n_samples`, `lat_avg`, and `lon_avg`; do not merge,
expand, or regroup it. The point-size encoding is `n_samples` and must have a
size legend. Never use `sample_id` as a grouping key for this map.

```python
plot_df = df_ecotaxa_profile_map.dropna(
    subset=["profile_id", "n_samples", "lat_avg", "lon_avg"]
).copy()
sizes = 36 + 220 * (
    plot_df["n_samples"] / plot_df["n_samples"].max()
).clip(lower=0.15)
map_points = ax.scatter(
    plot_df["lon_avg"], plot_df["lat_avg"], s=sizes,
    color="#2563eb", edgecolor="#0f172a", linewidth=0.45,
    transform=ccrs.PlateCarree(), zorder=3,
)
map_points.set_gid("map_points")
legend_counts = sorted(plot_df["n_samples"].astype(int).unique())
legend_handles = [
    ax.scatter([], [], s=36 + 220 * (count / plot_df["n_samples"].max()),
               color="#2563eb", edgecolor="#0f172a")
    for count in legend_counts
]
size_legend = ax.legend(legend_handles, [str(count) for count in legend_counts],
                        title="Samples par profil", loc="lower left")
size_legend.set_gid("station_size_legend")
```

Use `kind: "station_map"`, a coordinate `position` mapping, a `size` mapping
for `n_samples`, and `source_variables` naming those columns. Draw the exact
resolved zone polygon; do not request a second lookup merely to render it.

### Station / position map (`station_map`)

The data axis must be a Cartopy GeoAxes. Give the point collection a stable gid.
`size` and `color` are optional; when you show a colour or size legend, give it a
gid and point its mapping at the **same variable** as the encoding it explains.
A position mapping with `x` / `y` keys is invalid. It must use exactly
`{"variable": "longitude_latitude", "artist_gid": "<point gid>"}`.

For categorical year or marker legends, set the legend artist gid to exactly
`station_color_legend` and include a matching `color_legend` mapping, even when
the legend is made with `ax.legend(...)` rather than a colourbar. Do not use a
different gid such as `year_marker_legend`.

```python
map_points = ax.scatter(lon, lat, s=sizes, c=values,
                        transform=ccrs.PlateCarree())
map_points.set_gid("map_points")
# optional — only if you actually encode a variable by colour:
color_legend = fig.colorbar(map_points, ax=ax)
color_legend.ax.set_gid("station_color_legend")
graph_contract = {
    "kind": "station_map",
    "axes": [{"axis_index": 0, "x": "longitude", "y": "latitude"}],
    "inverted_axes": [],
    "mappings": {
        "position": {"variable": "longitude_latitude", "artist_gid": "map_points"},
        # include size/color ONLY if you encode them, with the real variable:
        "color": {"variable": "n_taxa", "artist_gid": "map_points"},
        "color_legend": {"variable": "n_taxa", "artist_gid": "station_color_legend"},
    },
    "zero_policy": {"mode": "include", "artist_gid": None},
    "source_variables": ["longitude", "latitude", "sample_id", "n_taxa"],
}
```

For a plain positions map, keep only the `position` mapping and drop
`size`/`color`/legends entirely.

**Règle légende / labels obligatoire — toute carte de stations** :

- Libeller chaque station unique par `station_id` par défaut. Remplacer par
  `original_id` ou `sample_id` seulement sur demande explicite. Ne pas retirer
  les labels parce qu'il y a 21, 30 ou davantage de stations : l'utilisateur
  décide ensuite si un autre cadrage ou une carte plus sobre est préférable.
- Quand la taille encode `n_samples`, la légende doit afficher les comptes réels
  correspondants. Size-legend labels must be exact `n_samples` counts, never
  marker areas or a transformed size scale. Never use `pts.legend_elements(prop="sizes")`.

Never use `ccrs.PlateCarree()._as_mpl_transform(ax)`: use `ax.text(...,
transform=ccrs.PlateCarree(), clip_on=True)` for geographic labels.

```python
label_column = "station_id"  # replace only on explicit request
label_df = plot_df.dropna(subset=[label_column]).drop_duplicates(label_column)
for _, row in label_df.iterrows():
    ax.text(row["lon_avg"], row["lat_avg"], str(row[label_column]),
            transform=ccrs.PlateCarree(), clip_on=True, fontsize=7,
            color="#0f172a", ha="left", va="bottom")
```

For a sample map, `run_graph` provides `zone_polygons`, a mapping of canonical
names to local Shapely geometries from the IHO/NeoLab/MEOW registry. Draw each
Use Cartopy `ShapelyFeature` with the DataFrame's `zone` values. Never use bare `df`.

### EcoTaxa export map: aggregate objects into samples first

An EcoTaxa export is normally one row per **object**, not one row per sample.
For a map whose points are samples and whose size encodes one taxon's abundance:

- inspect the active export columns; do not assume `lat_avg` / `lon_avg` exist;
- if the export has `object_lat` / `object_lon`, group by `sample_id`, retaining
  the first non-null coordinates and counting only rows matching the selected
  taxon; use those aggregate coordinates for the map;
- never draw one point per object when the request is about samples or casts;
- if coordinates are missing both from the export and from a named sample-level
  source, stop with that precise limitation rather than inventing columns.

Use `kind: "station_map"`, one Cartopy GeoAxes, longitude/latitude roles, a
point artist gid, a `position` mapping with `longitude_latitude`,
`zero_policy: include`, and actual `source_variables`. Retry once on a missing
contract.

### Zone breakdown map (samples + polygon boundaries)

Use this template when the user asks to show samples colored by zone **with** zone borders.
`zone_polygons` is already in scope — do NOT call `get_zone_info()` inside `run_graph` code.

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from matplotlib.lines import Line2D
import pandas as pd

plt.rcParams.update({"figure.facecolor": "#ffffff", "axes.facecolor": "#f8fafc",
                     "axes.edgecolor": "#94a3b8", "axes.labelcolor": "#0f172a",
                     "xtick.color": "#334155", "ytick.color": "#334155",
                     "text.color": "#0f172a", "grid.alpha": 0.35})

# Use the correct DataFrame variable (df_ecotaxa_cache_query, loaded_file, etc.)
plot_df = df_ecotaxa_cache_query.copy()
plot_df = plot_df.dropna(subset=["lat_avg", "lon_avg"])

# Sort zones so color assignment is stable regardless of DataFrame assembly order.
zones = sorted(plot_df["iho_zone"].fillna("Inconnu").unique().tolist())
cmap = plt.get_cmap("tab20", max(len(zones), 1))
color_map = {z: cmap(i % cmap.N) for i, z in enumerate(zones)}

fig = plt.figure(figsize=(16, 8))
ax = plt.axes(projection=ccrs.Robinson())
ax.set_global()
ax.add_feature(cfeature.LAND, facecolor="#efe7d2", zorder=1)
ax.add_feature(cfeature.OCEAN, facecolor="#dbeafe", zorder=0)
ax.add_feature(cfeature.COASTLINE, linewidth=0.4, edgecolor="#475569", zorder=2)
ax.gridlines(linewidth=0.4, color="#94a3b8", alpha=0.35, linestyle="--")

# Draw zone polygon boundaries — zone_polygons keys match iho_zone values exactly
for zone_name in zones:
    if zone_name in zone_polygons:
        feat = cfeature.ShapelyFeature(
            [zone_polygons[zone_name]], ccrs.PlateCarree(),
            facecolor=(*color_map[zone_name][:3], 0.12),
            edgecolor=color_map[zone_name], linewidth=1.2,
        )
        ax.add_feature(feat, zorder=3)

# Plot actual sample points on top
for zone_name, group in plot_df.groupby("iho_zone", sort=True):
    pts = ax.scatter(
        group["lon_avg"], group["lat_avg"],
        s=14, color=color_map.get(zone_name, "#2563eb"), alpha=0.85,
        transform=ccrs.PlateCarree(), zorder=4, label=zone_name,
    )
    pts.set_gid("map_points")

# Legend — cap at 15 entries to avoid overflow
legend_zones = zones[:15]
handles = [Line2D([0], [0], marker="o", color="none",
                  markerfacecolor=color_map[z], markersize=6, label=z)
           for z in legend_zones]
ax.legend(handles=handles, title="iho_zone", loc="lower left",
          fontsize=7, title_fontsize=8, frameon=True, framealpha=0.85)

ax.set_title("Samples EcoTaxa — découpage par zone IHO/MEOW", fontsize=14, color="#0f172a")
graph_contract = {
    "kind": "station_map",
    "axes": [{"axis_index": 0, "x": "longitude", "y": "latitude"}],
    "inverted_axes": [],
    "mappings": {"position": {"variable": "lon_avg_lat_avg", "artist_gid": "map_points"}},
    "zero_policy": {"mode": "include", "artist_gid": None},
    "source_variables": ["lat_avg", "lon_avg", "iho_zone"],
}
graph_explanation = "Carte monde des samples EcoTaxa colorés et découpés par zone iho_zone."
plt.tight_layout()
```

### Abundance–environment map

The data axis must be a Cartopy GeoAxes. Give the point collection and both
distinct legend artists stable gids.

```python
map_points = ax.scatter(lon, lat, s=sizes, c=environment,
                        transform=ccrs.PlateCarree())
map_points.set_gid("map_points")
size_legend = ax.legend(handles=size_handles, title="Abondance (ind./L)")
size_legend.set_gid("abundance_size_legend")
ax.add_artist(size_legend)
environment_legend = fig.colorbar(map_points, ax=ax)
environment_legend.ax.set_gid("environment_color_legend")
graph_contract = {
    "kind": "abundance_environment_map",
    "axes": [{"axis_index": 0, "x": "longitude", "y": "latitude"}],
    "inverted_axes": [],
    "mappings": {
        "position": {"variable": "longitude_latitude", "artist_gid": "map_points"},
        "size": {"variable": "abundance_ind_L", "artist_gid": "map_points"},
        "color": {"variable": "<environment column>", "artist_gid": "map_points"},
        "size_legend": {"variable": "abundance_ind_L", "artist_gid": "abundance_size_legend"},
        "color_legend": {"variable": "<environment column>", "artist_gid": "environment_color_legend"},
    },
    "zero_policy": {"mode": "include", "artist_gid": None},
    "source_variables": ["longitude", "latitude", "abundance_ind_L", "<environment column>"],
}
```

## Geographic maps

**Always use cartopy** for any map/geo scatter request — never use plain `plt.scatter` on lon/lat axes.
Cartopy produces real geographic projections with coastlines, ocean fill, and graticules.
For multi-zone sample maps, prefer `ccrs.PlateCarree()`; it is the stable
renderer for polygon contours and sample points in this environment.

### Standalone named-zone map

Use this only when the user asks to show the zone boundary itself and no sample
data is requested. For a map of samples in one or more named zones, the agent
must first query/persist the sample rows (including latitude/longitude), then
plot the exact named DataFrame; do not use this standalone template or bare `df`.
For a boundary-only map, use the `bbox` returned by `get_zone_info(zone_name=...)`.

For a standalone zone map, use `ccrs.PlateCarree()` and put lon/lat labels via
`set_xticks`/`set_yticks` + the cartopy formatters. Do **not** use
`ax.gridlines(draw_labels=True)` here: on this cartopy build the gridline
labeler raises `ValueError: cannot convert float NaN to integer` (especially on
`LambertConformal`), which has nothing to do with a missing file.

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from cartopy.mpl.ticker import LongitudeFormatter, LatitudeFormatter

plt.rcParams.update({"figure.facecolor": "#ffffff", "axes.facecolor": "#f8fafc",
                     "axes.edgecolor": "#94a3b8", "axes.labelcolor": "#0f172a",
                     "xtick.color": "#334155", "ytick.color": "#334155",
                     "text.color": "#0f172a", "grid.alpha": 0.35})

bbox = {"south": <south>, "west": <west>, "north": <north>, "east": <east>}
proj = ccrs.PlateCarree()

fig, ax = plt.subplots(figsize=(10, 8), subplot_kw={"projection": proj})
ax.set_extent([bbox["west"], bbox["east"], bbox["south"], bbox["north"]], crs=ccrs.PlateCarree())

ax.add_feature(cfeature.LAND, facecolor="#efe7d2", zorder=1)
ax.add_feature(cfeature.OCEAN, facecolor="#dbeafe", zorder=0)
ax.add_feature(cfeature.COASTLINE, linewidth=0.8, edgecolor="#475569", zorder=2)
ax.add_feature(cfeature.BORDERS, linestyle=":", linewidth=0.5, edgecolor="#64748b", zorder=2)

# lon/lat labels via the axis (avoids the broken gridline labeler)
import numpy as np
ax.set_xticks(np.linspace(bbox["west"], bbox["east"], 5), crs=ccrs.PlateCarree())
ax.set_yticks(np.linspace(bbox["south"], bbox["north"], 5), crs=ccrs.PlateCarree())
ax.xaxis.set_major_formatter(LongitudeFormatter())
ax.yaxis.set_major_formatter(LatitudeFormatter())
ax.tick_params(colors="#334155", labelsize=8)
ax.gridlines(linewidth=0.5, color="#94a3b8", alpha=0.35, linestyle="--")  # lines only, no draw_labels

ax.set_title("<zone name>", fontsize=13, color="#0f172a")
plt.tight_layout()

graph_explanation = "Carte de <zone name>. Axes : longitude x latitude. Source : get_zone_info."
```

## Light theme (mandatory for all graphs)

Every graph and map must use this clear template. It is the only approved
theme: white figure, softly tinted plotting area, dark text, and pale geographic
features. Never use a dark matplotlib style, a black/charcoal figure, or white text
to compensate for a dark surface.

```python
plt.rcParams.update({
    "figure.facecolor": "#ffffff",
    "axes.facecolor": "#f8fafc",
    "axes.edgecolor": "#94a3b8",
    "axes.labelcolor": "#0f172a",
    "xtick.color": "#334155",
    "ytick.color": "#334155",
    "text.color": "#0f172a",
    "grid.color": "#cbd5e1",
    "grid.alpha": 0.55,
})
# Cartopy maps: LAND="#efe7d2", OCEAN="#dbeafe", COASTLINE="#475569".
```

---

### Template Hawke Channel / Nord québécois (lat 52–63°N)

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature

plt.rcParams.update({{"figure.facecolor": "#ffffff", "axes.facecolor": "#f8fafc",
                     "axes.edgecolor": "#94a3b8", "axes.labelcolor": "#0f172a",
                     "xtick.color": "#334155", "ytick.color": "#334155", "text.color": "#0f172a"}})

map_df = df[['longitude', 'latitude']].dropna()
proj = ccrs.LambertConformal(central_longitude=-55, central_latitude=54)

fig, ax = plt.subplots(figsize=(10, 8), subplot_kw={{"projection": proj}})

lon_pad = max((map_df['longitude'].max() - map_df['longitude'].min()) * 0.12, 0.25)
lat_pad = max((map_df['latitude'].max() - map_df['latitude'].min()) * 0.12, 0.25)
ax.set_extent([
    map_df['longitude'].min() - lon_pad,
    map_df['longitude'].max() + lon_pad,
    map_df['latitude'].min()  - lat_pad,
    map_df['latitude'].max()  + lat_pad,
], crs=ccrs.PlateCarree())

ax.add_feature(cfeature.LAND,      facecolor='#efe7d2', zorder=1)
ax.add_feature(cfeature.OCEAN,     facecolor='#dbeafe', zorder=0)
ax.add_feature(cfeature.COASTLINE, linewidth=0.8, edgecolor='#475569', zorder=2)
ax.add_feature(cfeature.BORDERS,   linestyle=':', linewidth=0.5, edgecolor='#64748b', zorder=2)

gl = ax.gridlines(draw_labels=True, linewidth=0.5, color='#94a3b8', alpha=0.45, linestyle='--')
gl.top_labels = False
gl.right_labels = False

sc = ax.scatter(
    map_df['longitude'], map_df['latitude'],
    color='#2563eb', s=40, alpha=0.9,
    transform=ccrs.PlateCarree(), zorder=3,
)

ax.set_title("<titre>", fontsize=13, color='#0f172a')
plt.tight_layout()
```

---

### Climate delta map template

Use when the plan says Type: climate delta map. Stations coloured by warming delta (Bio-ORACLE SSP − CTD current).

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import numpy as np

plt.rcParams.update({{"figure.facecolor": "#ffffff", "axes.facecolor": "#f8fafc",
                     "axes.edgecolor": "#94a3b8", "axes.labelcolor": "#0f172a",
                     "xtick.color": "#334155", "ytick.color": "#334155", "text.color": "#0f172a"}})

# --- prepare data ---
# delta_df must have: latitude, longitude, delta_rechauffement_degC
map_df = delta_df.dropna(subset=['latitude', 'longitude', 'delta_rechauffement_degC'])

central_lon = float(map_df['longitude'].mean())
proj = ccrs.LambertConformal(central_longitude=central_lon, central_latitude=float(map_df['latitude'].mean()))
fig, ax = plt.subplots(figsize=(12, 8), subplot_kw={{"projection": proj}})

lon_pad = max((map_df['longitude'].max() - map_df['longitude'].min()) * 0.12, 0.25)
lat_pad = max((map_df['latitude'].max() - map_df['latitude'].min()) * 0.12, 0.25)
ax.set_extent([
    map_df['longitude'].min() - lon_pad, map_df['longitude'].max() + lon_pad,
    map_df['latitude'].min() - lat_pad,  map_df['latitude'].max() + lat_pad,
], crs=ccrs.PlateCarree())

ax.add_feature(cfeature.LAND,      facecolor='#efe7d2', zorder=1)
ax.add_feature(cfeature.OCEAN,     facecolor='#dbeafe', zorder=0)
ax.add_feature(cfeature.COASTLINE, linewidth=0.8, edgecolor='#475569', zorder=2)
gl = ax.gridlines(draw_labels=True, linewidth=0.4, color='#94a3b8', alpha=0.45, linestyle='--')
gl.top_labels = False; gl.right_labels = False

vmax = float(map_df['delta_rechauffement_degC'].abs().quantile(0.95)) or 5
sc = ax.scatter(
    map_df['longitude'], map_df['latitude'],
    c=map_df['delta_rechauffement_degC'],
    cmap='coolwarm', vmin=-vmax, vmax=vmax,
    s=60, alpha=0.9,
    transform=ccrs.PlateCarree(), zorder=3,
)
cbar = plt.colorbar(sc, ax=ax, label='Δ température (°C)', shrink=0.6, pad=0.02)
cbar.ax.yaxis.label.set_color('#0f172a')
cbar.ax.tick_params(colors='#334155')

ax.set_title("<titre — ex: Delta réchauffement Bio-ORACLE SSP5-8.5 2100 vs CTD actuel>", fontsize=13, color='#0f172a')
plt.tight_layout()

graph_explanation = "Carte du delta de température par station. Axes : longitude × latitude. Couleur : Δ°C (Bio-ORACLE SSP5-8.5 2100 − CTD actuel), coolwarm centrée sur 0. Source : run_pandas sur delta_df."
```

---

### Standard template (Amundsen / Arctic / Baffin Bay)

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import numpy as np

# --- prepare data ---
map_df = df[['longitude', 'latitude']].dropna()  # add color column if needed

# --- projection centred on data ---
central_lon = float(map_df['longitude'].mean())
proj = ccrs.NorthPolarStereo(central_longitude=central_lon)

fig, ax = plt.subplots(figsize=(10, 8), subplot_kw={"projection": proj})
fig.patch.set_facecolor('#ffffff')
ax.set_facecolor('#f8fafc')

# --- extent: zoom to the data with a proportional margin ---
lon_pad = max((map_df['longitude'].max() - map_df['longitude'].min()) * 0.12, 0.25)
lat_pad = max((map_df['latitude'].max() - map_df['latitude'].min()) * 0.12, 0.25)
ax.set_extent([
    map_df['longitude'].min() - lon_pad,
    map_df['longitude'].max() + lon_pad,
    map_df['latitude'].min()  - lat_pad,
    map_df['latitude'].max()  + lat_pad,
], crs=ccrs.PlateCarree())

# --- background ---
ax.add_feature(cfeature.LAND,      facecolor='#d2c5a0', zorder=1)
ax.add_feature(cfeature.OCEAN,     facecolor='#cfe2f3', zorder=0)
ax.add_feature(cfeature.COASTLINE, linewidth=0.8,       zorder=2)
ax.add_feature(cfeature.BORDERS,   linestyle=':',       linewidth=0.5, zorder=2)

# --- gridlines ---
gl = ax.gridlines(draw_labels=True, linewidth=0.5, color='gray', alpha=0.5, linestyle='--')
gl.top_labels   = False
gl.right_labels = False

# --- data points ---
sc = ax.scatter(
    map_df['longitude'], map_df['latitude'],
    c='<color_column>',   # or color='steelblue' if no variable
    cmap='viridis',
    s=60, alpha=0.9,
    transform=ccrs.PlateCarree(),
    zorder=3,
)
plt.colorbar(sc, ax=ax, label='<unit>', shrink=0.6)  # omit if no color variable

ax.set_title("<title>", fontsize=13)
plt.tight_layout()
```

### Rules

- **Always** `transform=ccrs.PlateCarree()` on geographic scatter/text calls — required by cartopy
- **Always** `subplot_kw={"projection": proj}` — never `plt.subplots()` without projection for maps
- Use `NorthPolarStereo` for Arctic/Amundsen data (lat > 55°N)
- Use `ccrs.PlateCarree()` as projection for tropical/global data
- Extent auto-computed from data + margin — never hardcode coordinates
- Color variable: use `c=df['<col>']` + `cmap='viridis'` for continuous (abundance, biomass, temperature, salinity)
- No color variable: use `color='steelblue'`
- Station labels: use `ax.text(lon, lat, name, transform=ccrs.PlateCarree(), clip_on=True, fontsize=7)` on unique stations; default to `station_id`, otherwise only an explicitly requested ID.
- Never use folium — cartopy only
- When writing the code, make the `graph_explanation` reflect the actual plotting choices (axes, source, encoding) — never describe what the chart shows or suggest priorities.

## Data handling

- Sort values before plotting (e.g. `.sort_values(ascending=False)`)
- Drop NaN before plotting: `.dropna()`
- If the user requests a top N, respect exactly N — do not truncate arbitrarily

---

## Biodiversity and copepod graph templates

Use these templates when the plan selects a biodiversity-specific graph type.
They are intentionally explicit so the agent does not collapse rarefaction,
ordination, composition, and depth profiles into generic scatter plots.

### Vertical profile template

Use for "profil vertical", "vertical distribution", abundance by depth,
biomass by depth, CTD variable by depth, or diel/depth positioning plots.

Render one coherent profile per subject: the profile's own working table must
already be built (source-specific grouping done upstream). Plot the measurement
against depth on an inverted y-axis; do not mix unrelated groups onto one profile.

#### EcoTaxa object-export profiles

An EcoTaxa export has one row per object, normally without concentration. For a
taxon profile, filter one real annotation label and group numeric
`object_depth_min` (or available object depth) by `sample_id`, using
`object_id.size()` as `object_count`. A count is not ind./L or ind./m³: use a
`generic` contract (`object_count` x, `depth_m` y), never an abundance role.
If CTD temperature is requested, carry the mean real field. Assign that table
to both `profile_df` and `result` in `run_pandas`; this persists the derived
table for the graph. Then plot one line per `sample_id`, invert only the depth
y-axis, and use the temperature field for a colorbar or an explicitly labelled
secondary encoding. Never reject this request merely because a raw export lacks
an abundance column, and never count rows without first filtering the selected
taxon.

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

plt.rcParams.update({"figure.facecolor": "#ffffff", "axes.facecolor": "#f8fafc",
                     "axes.edgecolor": "#94a3b8", "axes.labelcolor": "#0f172a",
                     "xtick.color": "#334155", "ytick.color": "#334155",
                     "text.color": "#0f172a", "grid.alpha": 0.35})

plot_df = df.copy()
depth_col = "<depth column>"          # e.g. MIN_SAMPLE_DEPTH or depth_min_m
value_col = "<value column>"          # e.g. Total abundance (ind./m3 depth vol)
plot_df[depth_col] = pd.to_numeric(plot_df[depth_col], errors="coerce")
plot_df[value_col] = pd.to_numeric(plot_df[value_col], errors="coerce")
plot_df = plot_df.dropna(subset=[depth_col, value_col])
if plot_df.empty:
    raise ValueError("No rows remain after filtering; check depth and value columns.")

profile_df = (
    plot_df
    .groupby(depth_col, as_index=False)[value_col]
    .mean()
    .sort_values(depth_col)
)

fig, ax = plt.subplots(figsize=(8, 7))
ax.plot(profile_df[value_col], profile_df[depth_col], marker="o", color="#2563eb", linewidth=1.8)
ax.invert_yaxis()
ax.grid(True, alpha=0.25)
ax.set_title("<descriptive title>")
ax.set_xlabel("<measurement label>")
ax.set_ylabel("Depth (m)")
plt.tight_layout()

graph_explanation = "Profil vertical. Axes : mesure x profondeur (m). Source : fichier charge."
```

### Vertical profile with multiple samples or profiles

When the request compares profiles, build `plot_df` from the exact persistent
table returned by the calculation. Do not recompute a derived abundance in the
graph code. Keep the real data-column name in `value_col`, but declare the
canonical abundance role in `graph_contract`.

```python
# Replace df_derived_abundance_df with the exact persistent variable returned by run_pandas.
plot_df = df_derived_abundance_df.copy()
profile_col = "Profile"
depth_col = "Depth [m]"
value_col = "abondance_totale_ind_m3"  # real source column; may be French
abundance_role = "abundance_ind_m3"    # required graph-contract role

plot_df[depth_col] = pd.to_numeric(plot_df[depth_col], errors="coerce")
plot_df[value_col] = pd.to_numeric(plot_df[value_col], errors="coerce")
plot_df = plot_df.dropna(subset=[profile_col, depth_col, value_col])
if plot_df.empty:
    raise ValueError("No rows remain after filtering; check profile, depth, and abundance columns.")

profiles = sorted(plot_df[profile_col].astype(str).unique())
if len(profiles) > 30:
    raise ValueError("More than 30 profiles: filter or aggregate before plotting.")

fig, ax = plt.subplots(figsize=(10, 8))
for profile, group in plot_df.groupby(profile_col, sort=True):
    group = group.sort_values(depth_col)
    ax.plot(group[value_col], group[depth_col], marker="o", markersize=3,
            linewidth=1, alpha=0.8, label=str(profile))
ax.invert_yaxis()
ax.grid(True, alpha=0.25)
ax.set_title("<descriptive title>")
ax.set_xlabel("Abondance (ind·m⁻³)")
ax.set_ylabel("Depth (m)")
if len(profiles) > 15:
    ax.legend(title=profile_col, ncol=3, fontsize=6, title_fontsize=7, frameon=False)
else:
    ax.legend(title=profile_col, fontsize=7, title_fontsize=8, frameon=False)

graph_contract = {
    "kind": "vertical_profile",
    "axes": [{"axis_index": 0, "x": abundance_role, "y": "depth_m"}],
    "inverted_axes": [{"axis_index": 0, "axis": "y"}],
    "mappings": {},
    "zero_policy": {"mode": "include", "artist_gid": None},
    "source_variables": [profile_col, depth_col, value_col],
}
```

### Taxonomic composition stacked bar template

Use for composition taxonomique across stations, months, depth bins, samples,
or zones. Keep only the top taxa and group the rest as `Other`.

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

plt.rcParams.update({"figure.facecolor": "#ffffff", "axes.facecolor": "#f8fafc",
                     "axes.edgecolor": "#94a3b8", "axes.labelcolor": "#0f172a",
                     "xtick.color": "#334155", "ytick.color": "#334155",
                     "text.color": "#0f172a", "grid.alpha": 0.35})

group_col = "<station/month/depth/sample column>"
taxon_col = "<taxon column>"
value_col = "<abundance column>"
plot_df = df[[group_col, taxon_col, value_col]].copy()
plot_df[value_col] = pd.to_numeric(plot_df[value_col], errors="coerce")
plot_df = plot_df.dropna(subset=[group_col, taxon_col, value_col])
if plot_df.empty:
    raise ValueError("No rows remain after filtering; check composition columns.")

top_taxa = (
    plot_df.groupby(taxon_col)[value_col].sum()
    .sort_values(ascending=False)
    .head(10)
    .index
)
plot_df[taxon_col] = plot_df[taxon_col].where(plot_df[taxon_col].isin(top_taxa), "Other")
matrix = (
    plot_df.pivot_table(index=group_col, columns=taxon_col, values=value_col, aggfunc="sum", fill_value=0)
    .sort_index()
)
matrix = matrix.div(matrix.sum(axis=1).replace(0, pd.NA), axis=0).fillna(0)

fig, ax = plt.subplots(figsize=(12, 7))
matrix.plot(kind="bar", stacked=True, ax=ax, colormap="tab10", width=0.85)
ax.set_title("<descriptive title>")
ax.set_xlabel("<group label>")
ax.set_ylabel("Relative abundance")
ax.tick_params(axis="x", rotation=45, colors="#334155")
ax.tick_params(axis="y", colors="#334155")
ax.legend(title="Taxon", bbox_to_anchor=(1.02, 1), loc="upper left", frameon=False)
plt.tight_layout()

graph_explanation = "Composition taxonomique empilee. Axes : groupe x abondance relative. Source : fichier charge."
```

### Taxonomic composition heatmap template

Use when the plan says composition heatmap or when many taxa/groups would make
a stacked bar unreadable.

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

plt.rcParams.update({"figure.facecolor": "#ffffff", "axes.facecolor": "#f8fafc",
                     "axes.edgecolor": "#94a3b8", "axes.labelcolor": "#0f172a",
                     "xtick.color": "#334155", "ytick.color": "#334155",
                     "text.color": "#0f172a", "grid.alpha": 0.35})

group_col = "<station/month/depth/sample column>"
taxon_col = "<taxon column>"
value_col = "<abundance column>"
plot_df = df[[group_col, taxon_col, value_col]].copy()
plot_df[value_col] = pd.to_numeric(plot_df[value_col], errors="coerce")
plot_df = plot_df.dropna(subset=[group_col, taxon_col, value_col])
if plot_df.empty:
    raise ValueError("No rows remain after filtering; check heatmap columns.")

top_taxa = plot_df.groupby(taxon_col)[value_col].sum().sort_values(ascending=False).head(20).index
plot_df = plot_df[plot_df[taxon_col].isin(top_taxa)]
matrix = plot_df.pivot_table(index=taxon_col, columns=group_col, values=value_col, aggfunc="sum", fill_value=0)
matrix = np.log1p(matrix)

matrix = matrix.loc[matrix.sum(axis=1).sort_values(ascending=False).head(20).index]
if matrix.shape[1] > 40:
    top_groups = matrix.sum(axis=0).sort_values(ascending=False).head(40).index
    matrix = matrix[top_groups]

fig, ax = plt.subplots(figsize=(12, 8))
im = ax.imshow(matrix.values, aspect="auto", cmap="viridis")
ax.set_yticks(range(len(matrix.index)))
short_taxa = [
    str(label).split("|")[-1].strip()[:35] + ("…" if len(str(label).split("|")[-1].strip()) > 35 else "")
    for label in matrix.index
]
ax.set_yticklabels(short_taxa, fontsize=8, color="#334155")
if len(matrix.columns) <= 25:
    ax.set_xticks(range(len(matrix.columns)))
    ax.set_xticklabels(matrix.columns, rotation=45, ha="right", fontsize=8, color="#334155")
else:
    step = max(1, len(matrix.columns) // 20)
    ticks = list(range(0, len(matrix.columns), step))
    ax.set_xticks(ticks)
    ax.set_xticklabels([matrix.columns[i] for i in ticks], rotation=45, ha="right", fontsize=7, color="#334155")
cbar = plt.colorbar(im, ax=ax, label="log1p abundance")
cbar.ax.yaxis.label.set_color("#0f172a")
cbar.ax.tick_params(colors="#334155")
ax.set_title("<descriptive title>")
ax.set_xlabel("<group label>")
ax.set_ylabel("Taxon")
plt.tight_layout()

graph_explanation = "Heatmap de composition taxonomique. Axes : groupe x taxon. Couleur : log1p abondance. Source : fichier charge."
```

### Rank-abundance template

Use for dominance, rank-abundance, or taxa ordered by abundance.

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

plt.rcParams.update({"figure.facecolor": "#ffffff", "axes.facecolor": "#f8fafc",
                     "axes.edgecolor": "#94a3b8", "axes.labelcolor": "#0f172a",
                     "xtick.color": "#334155", "ytick.color": "#334155",
                     "text.color": "#0f172a", "grid.alpha": 0.35})

taxon_col = "<taxon column>"
value_col = "<abundance column>"
plot_df = df[[taxon_col, value_col]].copy()
plot_df[value_col] = pd.to_numeric(plot_df[value_col], errors="coerce")
plot_df = plot_df.dropna(subset=[taxon_col, value_col])
plot_df = plot_df[plot_df[value_col] > 0]
if plot_df.empty:
    raise ValueError("No positive abundance values remain for rank-abundance.")

rank_df = (
    plot_df.groupby(taxon_col, as_index=False)[value_col].sum()
    .sort_values(value_col, ascending=False)
    .reset_index(drop=True)
)
rank_df["rank"] = np.arange(1, len(rank_df) + 1)
rank_df["relative_abundance"] = rank_df[value_col] / rank_df[value_col].sum()

fig, ax = plt.subplots(figsize=(10, 6))
ax.plot(rank_df["rank"], rank_df["relative_abundance"], marker="o", color="#2563eb", linewidth=1.8)
ax.set_yscale("log")
ax.set_title("<descriptive title>")
ax.set_xlabel("Taxon rank")
ax.set_ylabel("Relative abundance")
ax.grid(True, alpha=0.25)
plt.tight_layout()

graph_explanation = "Courbe rank-abundance. Axes : rang taxonomique x abondance relative. Source : fichier charge."
```

---

### Zoom to data

For a regional or station map, zoom to the populated extent instead of leaving a
world-scale or arbitrarily wide view. Use a proportional margin with a small
minimum so a single station remains visible. Do not use this helper for a map
that explicitly requests a global view or the full geometry of a named zone.

```python
def padded_extent(map_df, lon_col="longitude", lat_col="latitude", pad=0.12, minimum=0.25):
    west, east = map_df[lon_col].min(), map_df[lon_col].max()
    south, north = map_df[lat_col].min(), map_df[lat_col].max()
    lon_pad = max((east - west) * pad, minimum)
    lat_pad = max((north - south) * pad, minimum)
    return west - lon_pad, east + lon_pad, south - lat_pad, north + lat_pad

west, east, south, north = padded_extent(map_df)
ax.set_extent([west, east, south, north], crs=ccrs.PlateCarree())
```
