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
- After the figure code, set a string variable named `graph_explanation` with a short "Lecture rapide" note: what the graph shows, why the chosen encoding fits the question, and the main reading cue. Keep it concise and factual.

## Geographic maps

**Always use cartopy** for any map/geo scatter request — never use plain `plt.scatter` on lon/lat axes.
Cartopy produces real geographic projections with coastlines, ocean fill, and graticules.

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
- When writing the code, make the `graph_explanation` reflect the actual plotting choices in the code, not generic commentary.

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

The `graph_explanation` string must include the confidence level and the dominant uncertainty source. Example:

```python
graph_explanation = (
    "Distribution verticale de Calanus hyperboreus, EcoTaxa 1165. "
    "Confidence: medium — 12 rows out of 84 lack sampled volume (exploratory). "
    "Lecture rapide: pic à 50 m, queue jusqu'à 200 m."
)
```

Never produce a graph where exploratory and confirmed values are visually indistinguishable.
