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

## Geographic maps

If the plan recommends a `map` or `geo scatter` graph type, use this template:

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig, ax = plt.subplots(figsize=(12, 8))

scatter = ax.scatter(
    df['longitude'].dropna(),
    df['latitude'].dropna(),
    c=df['<color_variable>'],  # e.g. abundance, biomass — optional
    cmap='viridis',
    alpha=0.7,
    s=50,
)

ax.set_xlabel("Longitude (°W)")
ax.set_ylabel("Latitude (°N)")
ax.set_title("<title: e.g. Station distribution — Baffin Bay>")

plt.colorbar(scatter, ax=ax, label='<unit>')
plt.tight_layout()
```

- Use `longitude` for X and `latitude` for Y
- If a continuous variable is available (abundance, biomass, temperature): encode it as color with `c=` and `cmap='viridis'`
- If no continuous variable: use a fixed color (`color='steelblue'`)
- To annotate stations: `ax.annotate(row['STATION_NAME'], (row['longitude'], row['latitude']))` iterating over unique stations
- Never use folium — matplotlib only

## Data handling

- Sort values before plotting (e.g. `.sort_values(ascending=False)`)
- Drop NaN before plotting: `.dropna()`
- If the user requests a top N, respect exactly N — do not truncate arbitrarily
