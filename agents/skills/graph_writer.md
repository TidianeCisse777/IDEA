# Skill: graph_writer

You must write correct and complete code to produce the planned output — either a matplotlib chart or a pandas table.

## If the plan says Output: table

Use this template with `run_pandas`:

```python
result = (
    df
    .groupby("<group_column>")["<value_column>"]
    .agg("<sum | mean | count>")
    .sort_values(ascending=False)
    .reset_index()
    .rename(columns={"<value_column>": "<label>"})
)
```

Rules:
- Always assign to `result`
- Always sort for readability
- Use `.reset_index()` so the table has clean columns
- Never call `plt.show()` or produce a figure — `run_pandas` returns a markdown table automatically

---

## If the plan says Output: visual

You must write correct and complete matplotlib code.

## Base template

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig, ax = plt.subplots(figsize=(10, 6))

# --- your code here ---

ax.set_title("<descriptive title>")
ax.set_xlabel("<X axis label>")
ax.set_ylabel("<Y axis label>")
plt.tight_layout()
```

## Mandatory rules

- Always use `matplotlib.use("Agg")` — no interactive display
- Always use `fig, ax = plt.subplots()` — never call `plt.show()`
- Always define `title`, `xlabel`, `ylabel`
- Keep figures readable: `figsize` must stay at or below `(16, 14)`. If a heatmap or ordination needs more space, aggregate or filter groups rather than increasing figure height.
- Legends must stay readable: if a grouping variable has more than 15 levels, do NOT call `ax.legend()` for every group. Use a single color, a continuous color scale, top 12 groups + "Other", or add a small note such as `Legend omitted: 83 stations`.
- Axis labels must stay readable: never show more than 50 visible tick labels on either axis. For heatmaps with many stations/samples, keep the top 40 groups by abundance or display sparse ticks.
- Taxon tick labels must be short: if labels contain taxonomy paths such as `Animalia | Arthropoda | ...`, display only the terminal taxon name; truncate labels longer than 35 characters with an ellipsis.
- For long labels (taxon names): `ax.tick_params(axis='x', rotation=45)`
- For horizontal bar charts when there are many categories (> 10): use `ax.barh()`
- Never call `plt.savefig()` — the system captures the figure automatically
- Never invent or rewrite the image URL in the final answer. Return the exact image markdown emitted by `run_graph`; do not replace it with `/graphs/graph.png`.
- After the figure code, set a string variable named `graph_explanation` to a neutral description limited to: axes, source, and confidence level. No reading of the chart, no observations, no priorities, no "Lecture rapide", no interpretation cues. The assistant ignores this field when replying to the user — it is kept only as metadata for the tool layer.
- For multi-source graphs, never plot directly from bare `df`. `df` is only the latest active table. First build `plot_df` explicitly from named source DataFrames such as `df_ecotaxa_ecopart`, `df_ecotaxa_ecopart_105`, `df_ctd`, `df_bio_oracle`, `df_ogsl`, or `df_sql`.
- Treat station, sample, cast, profile, analysis, taxon, and project identifiers as labels, not numbers. Never cast identifiers such as `STATION_NAME`, `SAMPLE_ID`, `ANALYSIS_ID`, `CAST_NUMBER`, or `profile_id` with `int()` / `float()` just to filter. Normalize both sides of identifier comparisons with `.astype(str).str.strip()`.
- After every filtering step that creates `plot_df`, validate that rows remain before plotting:
  `if plot_df.empty: raise ValueError("No rows remain after filtering; check identifier type normalization and filter criteria.")`
- Before plotting numeric axes, coerce only the plotted measurement columns with `pd.to_numeric(..., errors="coerce")`, then drop missing values from all plotted columns. Validate again that `plot_df` is not empty after this drop.

## Geographic maps

**Always use cartopy** for any map/geo scatter request — never use plain `plt.scatter` on lon/lat axes.
Cartopy produces real geographic projections with coastlines, ocean fill, and graticules.

### Standalone named-zone map

Use this when the user asks to show a named zone itself, e.g. "montre-moi sur
une carte la baie d'Hudson", and no loaded DataFrame is needed. Use the `bbox`
returned by `get_zone_info(zone_name=...)`; do not reference `df`.

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature

plt.style.use("dark_background")
plt.rcParams.update({"axes.facecolor": "#1a1a1a", "figure.facecolor": "#1a1a1a",
                     "grid.alpha": 0.25, "axes.edgecolor": "#444"})

bbox = {"south": <south>, "west": <west>, "north": <north>, "east": <east>}
central_lon = (bbox["west"] + bbox["east"]) / 2
central_lat = (bbox["south"] + bbox["north"]) / 2
proj = ccrs.LambertConformal(central_longitude=central_lon, central_latitude=central_lat)

fig, ax = plt.subplots(figsize=(10, 8), subplot_kw={"projection": proj})
ax.set_extent([bbox["west"], bbox["east"], bbox["south"], bbox["north"]], crs=ccrs.PlateCarree())

ax.add_feature(cfeature.LAND, facecolor="#2d2d2d", zorder=1)
ax.add_feature(cfeature.OCEAN, facecolor="#1a3a5c", zorder=0)
ax.add_feature(cfeature.COASTLINE, linewidth=0.8, edgecolor="#aaaaaa", zorder=2)
ax.add_feature(cfeature.BORDERS, linestyle=":", linewidth=0.5, edgecolor="#666666", zorder=2)

gl = ax.gridlines(draw_labels=True, linewidth=0.5, color="gray", alpha=0.4, linestyle="--")
gl.top_labels = False
gl.right_labels = False

ax.set_title("<zone name>", fontsize=13, color="white")
plt.tight_layout()

graph_explanation = "Carte de <zone name>. Axes : longitude x latitude. Source : get_zone_info."
```

### Dark background (mandatory for all maps)

Every map must start with:
```python
plt.style.use("dark_background")
plt.rcParams.update({{"axes.facecolor": "#1a1a1a", "figure.facecolor": "#1a1a1a", "grid.alpha": 0.25}})
```
Use `facecolor='#2d2d2d'` for LAND and `facecolor='#1a3a5c'` for OCEAN on dark maps.

---

### Template Hawke Channel / Nord québécois (lat 52–63°N)

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature

plt.style.use("dark_background")
plt.rcParams.update({{"axes.facecolor": "#1a1a1a", "figure.facecolor": "#1a1a1a"}})

map_df = df[['longitude', 'latitude']].dropna()
proj = ccrs.LambertConformal(central_longitude=-55, central_latitude=54)

fig, ax = plt.subplots(figsize=(10, 8), subplot_kw={{"projection": proj}})

margin = 2
ax.set_extent([
    map_df['longitude'].min() - margin,
    map_df['longitude'].max() + margin,
    map_df['latitude'].min()  - margin,
    map_df['latitude'].max()  + margin,
], crs=ccrs.PlateCarree())

ax.add_feature(cfeature.LAND,      facecolor='#2d2d2d', zorder=1)
ax.add_feature(cfeature.OCEAN,     facecolor='#1a3a5c', zorder=0)
ax.add_feature(cfeature.COASTLINE, linewidth=0.8, edgecolor='#aaaaaa', zorder=2)
ax.add_feature(cfeature.BORDERS,   linestyle=':', linewidth=0.5, edgecolor='#666666', zorder=2)

gl = ax.gridlines(draw_labels=True, linewidth=0.5, color='gray', alpha=0.4, linestyle='--')
gl.top_labels = False
gl.right_labels = False

sc = ax.scatter(
    map_df['longitude'], map_df['latitude'],
    color='white', s=40, alpha=0.9,
    transform=ccrs.PlateCarree(), zorder=3,
)

ax.set_title("<titre>", fontsize=13, color='white')
plt.tight_layout()
```

---

### Sampling gap map template

Use when the plan says Type: sampling gap map. One point per station, coloured by coverage status.

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import numpy as np

plt.style.use("dark_background")
plt.rcParams.update({{"axes.facecolor": "#1a1a1a", "figure.facecolor": "#1a1a1a"}})

# --- prepare data ---
# station_coverage must have columns: latitude, longitude, n_obs
# (compute with run_pandas before calling run_graph)
map_df = station_coverage.dropna(subset=['latitude', 'longitude'])
map_df = map_df.copy()
map_df['color'] = map_df['n_obs'].apply(
    lambda n: '#2ecc71' if n >= 10 else ('#f39c12' if n >= 1 else '#e74c3c')
)

central_lon = float(map_df['longitude'].mean())
proj = ccrs.LambertConformal(central_longitude=central_lon, central_latitude=float(map_df['latitude'].mean()))
fig, ax = plt.subplots(figsize=(12, 8), subplot_kw={{"projection": proj}})

margin = 3
ax.set_extent([
    map_df['longitude'].min() - margin, map_df['longitude'].max() + margin,
    map_df['latitude'].min() - margin,  map_df['latitude'].max() + margin,
], crs=ccrs.PlateCarree())

ax.add_feature(cfeature.LAND,      facecolor='#2d2d2d', zorder=1)
ax.add_feature(cfeature.OCEAN,     facecolor='#1a3a5c', zorder=0)
ax.add_feature(cfeature.COASTLINE, linewidth=0.8, edgecolor='#aaaaaa', zorder=2)
gl = ax.gridlines(draw_labels=True, linewidth=0.4, color='gray', alpha=0.4, linestyle='--')
gl.top_labels = False; gl.right_labels = False

for _, row in map_df.iterrows():
    ax.scatter(row['longitude'], row['latitude'],
               color=row['color'], s=60, alpha=0.9,
               transform=ccrs.PlateCarree(), zorder=3)

# Legend
from matplotlib.lines import Line2D
legend_elements = [
    Line2D([0],[0], marker='o', color='w', markerfacecolor='#2ecc71', markersize=8, label='≥ 10 obs'),
    Line2D([0],[0], marker='o', color='w', markerfacecolor='#f39c12', markersize=8, label='1–9 obs (sparse)'),
    Line2D([0],[0], marker='o', color='w', markerfacecolor='#e74c3c', markersize=8, label='0 obs (absent)'),
]
ax.legend(handles=legend_elements, loc='lower left', fontsize=8,
          facecolor='#2d2d2d', edgecolor='#666', labelcolor='white')

ax.set_title("<titre>", fontsize=13, color='white')
plt.tight_layout()

graph_explanation = "Carte des lacunes d'échantillonnage par station. Axes : longitude × latitude. Couleur : nombre d'observations par station (vert ≥10, orange 1–9, rouge 0). Source : run_pandas sur station_coverage."
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

plt.style.use("dark_background")
plt.rcParams.update({{"axes.facecolor": "#1a1a1a", "figure.facecolor": "#1a1a1a"}})

# --- prepare data ---
# delta_df must have: latitude, longitude, delta_rechauffement_degC
map_df = delta_df.dropna(subset=['latitude', 'longitude', 'delta_rechauffement_degC'])

central_lon = float(map_df['longitude'].mean())
proj = ccrs.LambertConformal(central_longitude=central_lon, central_latitude=float(map_df['latitude'].mean()))
fig, ax = plt.subplots(figsize=(12, 8), subplot_kw={{"projection": proj}})

margin = 3
ax.set_extent([
    map_df['longitude'].min() - margin, map_df['longitude'].max() + margin,
    map_df['latitude'].min() - margin,  map_df['latitude'].max() + margin,
], crs=ccrs.PlateCarree())

ax.add_feature(cfeature.LAND,      facecolor='#2d2d2d', zorder=1)
ax.add_feature(cfeature.OCEAN,     facecolor='#1a3a5c', zorder=0)
ax.add_feature(cfeature.COASTLINE, linewidth=0.8, edgecolor='#aaaaaa', zorder=2)
gl = ax.gridlines(draw_labels=True, linewidth=0.4, color='gray', alpha=0.4, linestyle='--')
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
cbar.ax.yaxis.label.set_color('white')
cbar.ax.tick_params(colors='white')

ax.set_title("<titre — ex: Delta réchauffement Bio-ORACLE SSP5-8.5 2100 vs CTD actuel>", fontsize=13, color='white')
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

# --- extent: auto-fit with margin ---
margin = 3  # degrees
ax.set_extent([
    map_df['longitude'].min() - margin,
    map_df['longitude'].max() + margin,
    map_df['latitude'].min()  - margin,
    map_df['latitude'].max()  + margin,
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

- **Always** `transform=ccrs.PlateCarree()` on scatter/annotate calls — required by cartopy
- **Always** `subplot_kw={"projection": proj}` — never `plt.subplots()` without projection for maps
- Use `NorthPolarStereo` for Arctic/Amundsen data (lat > 55°N)
- Use `ccrs.PlateCarree()` as projection for tropical/global data
- Extent auto-computed from data + margin — never hardcode coordinates
- Color variable: use `c=df['<col>']` + `cmap='viridis'` for continuous (abundance, biomass, temperature, salinity)
- No color variable: use `color='steelblue'`
- Station labels: iterate unique stations and call `ax.annotate(name, (lon, lat), transform=ccrs.PlateCarree(), fontsize=7)`
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

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

plt.style.use("dark_background")
plt.rcParams.update({"axes.facecolor": "#1a1a1a", "figure.facecolor": "#1a1a1a",
                     "grid.alpha": 0.25, "axes.edgecolor": "#444"})

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
ax.plot(profile_df[value_col], profile_df[depth_col], marker="o", color="#eeeeee", linewidth=1.8)
ax.invert_yaxis()
ax.grid(True, alpha=0.25)
ax.set_title("<descriptive title>")
ax.set_xlabel("<measurement label>")
ax.set_ylabel("Depth (m)")
plt.tight_layout()

graph_explanation = "Profil vertical. Axes : mesure x profondeur (m). Source : fichier charge. Confidence: <confidence>."
```

### Taxonomic composition stacked bar template

Use for composition taxonomique across stations, months, depth bins, samples,
or zones. Keep only the top taxa and group the rest as `Other`.

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

plt.style.use("dark_background")
plt.rcParams.update({"axes.facecolor": "#1a1a1a", "figure.facecolor": "#1a1a1a",
                     "grid.alpha": 0.25, "axes.edgecolor": "#444"})

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
ax.tick_params(axis="x", rotation=45, colors="#cccccc")
ax.tick_params(axis="y", colors="#cccccc")
ax.legend(title="Taxon", bbox_to_anchor=(1.02, 1), loc="upper left", frameon=False)
plt.tight_layout()

graph_explanation = "Composition taxonomique empilee. Axes : groupe x abondance relative. Source : fichier charge. Confidence: <confidence>."
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

plt.style.use("dark_background")
plt.rcParams.update({"axes.facecolor": "#1a1a1a", "figure.facecolor": "#1a1a1a",
                     "grid.alpha": 0.25, "axes.edgecolor": "#444"})

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
ax.set_yticklabels(short_taxa, fontsize=8, color="#cccccc")
if len(matrix.columns) <= 25:
    ax.set_xticks(range(len(matrix.columns)))
    ax.set_xticklabels(matrix.columns, rotation=45, ha="right", fontsize=8, color="#cccccc")
else:
    step = max(1, len(matrix.columns) // 20)
    ticks = list(range(0, len(matrix.columns), step))
    ax.set_xticks(ticks)
    ax.set_xticklabels([matrix.columns[i] for i in ticks], rotation=45, ha="right", fontsize=7, color="#cccccc")
cbar = plt.colorbar(im, ax=ax, label="log1p abundance")
cbar.ax.yaxis.label.set_color("white")
cbar.ax.tick_params(colors="white")
ax.set_title("<descriptive title>")
ax.set_xlabel("<group label>")
ax.set_ylabel("Taxon")
plt.tight_layout()

graph_explanation = "Heatmap de composition taxonomique. Axes : groupe x taxon. Couleur : log1p abondance. Source : fichier charge. Confidence: <confidence>."
```

### Rarefaction curve template

Use for rarefaction requests. This template estimates expected richness by
subsampling individuals from a non-negative taxon count/abundance vector per
group. If the source is normalized abundance rather than integer counts, state
that the curve is exploratory.

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

plt.style.use("dark_background")
plt.rcParams.update({"axes.facecolor": "#1a1a1a", "figure.facecolor": "#1a1a1a",
                     "grid.alpha": 0.25, "axes.edgecolor": "#444"})

group_col = "<station/zone/month column>"
taxon_col = "<taxon column>"
value_col = "<count or abundance column>"
plot_df = df[[group_col, taxon_col, value_col]].copy()
plot_df[value_col] = pd.to_numeric(plot_df[value_col], errors="coerce")
plot_df = plot_df.dropna(subset=[group_col, taxon_col, value_col])
plot_df = plot_df[plot_df[value_col] > 0]
if plot_df.empty:
    raise ValueError("No positive count-like values remain for rarefaction.")

def rarefy_counts(counts, sample_sizes):
    counts = np.asarray(counts, dtype=float)
    counts = counts[counts > 0]
    total = counts.sum()
    richness = []
    for n in sample_sizes:
        if n <= 0 or total <= 0:
            richness.append(0.0)
            continue
        # Hurlbert-style expectation: sum probability each taxon appears.
        p_absent = np.exp(np.log1p(-counts / total) * n)
        richness.append(float(np.sum(1 - p_absent)))
    return np.asarray(richness)

group_totals = plot_df.groupby(group_col)[value_col].sum().sort_values(ascending=False)
groups_to_plot = group_totals.head(8).index
fig, ax = plt.subplots(figsize=(10, 6))
for label, sub in plot_df[plot_df[group_col].isin(groups_to_plot)].groupby(group_col):
    counts = sub.groupby(taxon_col)[value_col].sum().values
    total = int(max(1, np.floor(counts.sum())))
    sample_sizes = np.linspace(1, total, num=min(40, total), dtype=int)
    sample_sizes = np.unique(sample_sizes)
    richness = rarefy_counts(counts, sample_sizes)
    ax.plot(sample_sizes, richness, marker="o", linewidth=1.5, label=str(label))
    if len(richness) > 2:
        ax.fill_between(sample_sizes, richness * 0.95, richness * 1.05, alpha=0.12)

ax.set_title("<descriptive title>")
ax.set_xlabel("Sample size / effort")
ax.set_ylabel("Expected taxon richness")
ax.grid(True, alpha=0.25)
if len(groups_to_plot) <= 8:
    ax.legend(frameon=False, fontsize=8)
plt.tight_layout()

graph_explanation = "Courbe de rarefaction. Axes : effort x richesse attendue. Source : fichier charge. Confidence: <confidence>."
```

### Species accumulation curve template

Use for species accumulation across samples/sites. This permutation-based
template is deterministic through `np.random.default_rng(0)`.

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

plt.style.use("dark_background")
plt.rcParams.update({"axes.facecolor": "#1a1a1a", "figure.facecolor": "#1a1a1a",
                     "grid.alpha": 0.25, "axes.edgecolor": "#444"})

sample_col = "<sample/station column>"
taxon_col = "<taxon column>"
value_col = "<abundance column>"
plot_df = df[[sample_col, taxon_col, value_col]].copy()
plot_df[value_col] = pd.to_numeric(plot_df[value_col], errors="coerce")
plot_df = plot_df.dropna(subset=[sample_col, taxon_col, value_col])
plot_df = plot_df[plot_df[value_col] > 0]
if plot_df.empty:
    raise ValueError("No positive taxon records remain for species accumulation.")

presence = (
    plot_df.assign(present=plot_df[value_col] > 0)
    .pivot_table(index=sample_col, columns=taxon_col, values="present", aggfunc="max", fill_value=False)
    .astype(bool)
)
samples = presence.index.to_numpy()
rng = np.random.default_rng(0)
curves = []
for _ in range(100):
    order = rng.permutation(samples)
    seen = set()
    cumulative = []
    for sample in order:
        seen.update(presence.columns[presence.loc[sample].to_numpy()])
        cumulative.append(len(seen))
    curves.append(cumulative)
curves = np.asarray(curves, dtype=float)
x = np.arange(1, curves.shape[1] + 1)
mean_curve = curves.mean(axis=0)
lower = np.percentile(curves, 5, axis=0)
upper = np.percentile(curves, 95, axis=0)

fig, ax = plt.subplots(figsize=(10, 6))
ax.plot(x, mean_curve, color="#eeeeee", linewidth=2)
ax.fill_between(x, lower, upper, color="#7f9ec0", alpha=0.25)
ax.set_title("<descriptive title>")
ax.set_xlabel("Number of samples")
ax.set_ylabel("Cumulative observed taxa")
ax.grid(True, alpha=0.25)
plt.tight_layout()

graph_explanation = "Courbe d'accumulation d'especes. Axes : nombre d'echantillons x taxons cumules. Source : fichier charge. Confidence: <confidence>."
```

### NMDS / PCoA ordination template

Use for exploratory NMDS or PCoA of taxonomic composition. Bray-Curtis is the
default dissimilarity for community composition. Do not describe causality.

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
from scipy.spatial.distance import pdist, squareform, braycurtis
from sklearn.manifold import MDS

plt.style.use("dark_background")
plt.rcParams.update({"axes.facecolor": "#1a1a1a", "figure.facecolor": "#1a1a1a",
                     "grid.alpha": 0.25, "axes.edgecolor": "#444"})

sample_col = "<sample column>"
taxon_col = "<taxon column>"
value_col = "<abundance column>"
color_col = "<optional metadata column>"  # or None
plot_df = df[[sample_col, taxon_col, value_col] + ([] if color_col is None else [color_col])].copy()
plot_df[value_col] = pd.to_numeric(plot_df[value_col], errors="coerce")
plot_df = plot_df.dropna(subset=[sample_col, taxon_col, value_col])
plot_df = plot_df[plot_df[value_col] > 0]
if plot_df.empty:
    raise ValueError("No positive abundance records remain for ordination.")

taxon_matrix = plot_df.pivot_table(index=sample_col, columns=taxon_col, values=value_col, aggfunc="sum", fill_value=0)
taxon_matrix = taxon_matrix.loc[taxon_matrix.sum(axis=1) > 0]
taxon_matrix = np.sqrt(taxon_matrix.div(taxon_matrix.sum(axis=1), axis=0).fillna(0))
dist = squareform(pdist(taxon_matrix.values, metric="braycurtis"))

# NMDS coordinates. For PCoA, replace this block with eigendecomposition of a centered distance matrix.
ordination = MDS(n_components=2, metric=False, dissimilarity="precomputed", random_state=0, normalized_stress="auto")
coords = ordination.fit_transform(dist)
scores = pd.DataFrame(coords, index=taxon_matrix.index, columns=["NMDS1", "NMDS2"])
if color_col is not None:
    meta = plot_df.drop_duplicates(sample_col).set_index(sample_col)[color_col]
    scores[color_col] = meta.reindex(scores.index)

fig, ax = plt.subplots(figsize=(9, 7))
if color_col is None:
    ax.scatter(scores["NMDS1"], scores["NMDS2"], color="#eeeeee", s=50, alpha=0.9)
else:
    n_groups = scores[color_col].nunique(dropna=False)
    if n_groups <= 15:
        for label, sub in scores.groupby(color_col, dropna=False):
            ax.scatter(sub["NMDS1"], sub["NMDS2"], s=50, alpha=0.9, label=str(label))
        ax.legend(frameon=False, fontsize=8)
    else:
        ax.scatter(scores["NMDS1"], scores["NMDS2"], color="#eeeeee", s=42, alpha=0.75)
        ax.text(
            0.01, 0.99, f"Legend omitted: {n_groups} {color_col} levels",
            transform=ax.transAxes, ha="left", va="top",
            fontsize=8, color="#cccccc",
        )
ax.axhline(0, color="#666666", linewidth=0.8)
ax.axvline(0, color="#666666", linewidth=0.8)
ax.set_title("<descriptive title>")
ax.set_xlabel("NMDS1")
ax.set_ylabel("NMDS2")
ax.grid(True, alpha=0.2)
plt.tight_layout()

graph_explanation = "Ordination NMDS exploratoire sur dissimilarite Bray-Curtis. Axes : NMDS1 x NMDS2. Source : fichier charge. Confidence: <confidence>."
```

### Rank-abundance template

Use for dominance, rank-abundance, or taxa ordered by abundance.

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

plt.style.use("dark_background")
plt.rcParams.update({"axes.facecolor": "#1a1a1a", "figure.facecolor": "#1a1a1a",
                     "grid.alpha": 0.25, "axes.edgecolor": "#444"})

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
ax.plot(rank_df["rank"], rank_df["relative_abundance"], marker="o", color="#eeeeee", linewidth=1.8)
ax.set_yscale("log")
ax.set_title("<descriptive title>")
ax.set_xlabel("Taxon rank")
ax.set_ylabel("Relative abundance")
ax.grid(True, alpha=0.25)
plt.tight_layout()

graph_explanation = "Courbe rank-abundance. Axes : rang taxonomique x abondance relative. Source : fichier charge. Confidence: <confidence>."
```

---

## Uncertainty rendering (CT-AG-27)

Every graph must reflect the confidence level from the plan. Confirmed and exploratory data must never look identical.

### Confidence palette

| Status | Color | Marker / fill |
|---|---|---|
| confirmed | full saturation (`#1f77b4`, `#2ca02c`, `viridis` cmap) | solid fill, `alpha=0.9` |
| exploratory | desaturated (`#7f9ec0`, `#92c190`, `cividis` cmap) | hatched fill (`hatch='//'`), `alpha=0.6` |
| uncertain identification | gray (`#9e9e9e`) | open marker (`facecolor='none'`, `edgecolor='gray'`), `alpha=0.6` |

### Mandatory annotations

After defining title/xlabel/ylabel, **always** add a confidence stamp in the bottom-right corner of the axes:

```python
confidence_label = f"Confidence: {confidence} ({n_confirmed} confirmed, {n_exploratory} exploratory, {n_uncertain} uncertain)"
ax.text(
    0.99, 0.01, confidence_label,
    transform=ax.transAxes,
    ha='right', va='bottom',
    fontsize=8, color='#444444',
    bbox=dict(boxstyle='round,pad=0.3', facecolor='white', edgecolor='#cccccc', alpha=0.8),
)
```

When confidence is `low`, add a second annotation in the top-left:

```python
ax.text(
    0.01, 0.99, "⚠ Low confidence — exploratory result",
    transform=ax.transAxes,
    ha='left', va='top',
    fontsize=9, color='#b30000', weight='bold',
)
```

### Visual encoding rules

- For bar charts mixing confirmed and exploratory categories: split into two series (full vs hatched) on the same axes.
- For scatter/map: pass `c=color_array` where each row's color comes from the palette above based on its status.
- For line charts of derived variables: solid line for confirmed segments, dashed line (`linestyle='--'`) for exploratory segments.
- For histograms: stack confirmed (solid) on top of exploratory (hatched) using `ax.hist([data_confirmed, data_exploratory], stacked=True, ...)`.

### graph_explanation

The `graph_explanation` string must include the axes, source, and confidence level with the dominant uncertainty source. No reading of the chart, no peak/trend description, no priorities. Example:

```python
graph_explanation = (
    "Distribution verticale de Calanus hyperboreus, EcoTaxa 1165. "
    "Axes : abondance × profondeur (m). Source : run_pandas sur df_ecotaxa_1165. "
    "Confidence: medium — 12 rows out of 84 lack sampled volume (exploratory)."
)
```

Never produce a graph where exploratory and confirmed values are visually indistinguishable.
