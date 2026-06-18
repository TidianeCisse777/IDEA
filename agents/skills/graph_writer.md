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
- For long labels (taxon names): `ax.tick_params(axis='x', rotation=45)`
- For horizontal bar charts when there are many categories (> 10): use `ax.barh()`
- Never call `plt.savefig()` — the system captures the figure automatically
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
