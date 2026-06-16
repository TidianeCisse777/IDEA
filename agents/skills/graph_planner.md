# Skill: graph_planner

You must plan a graph before writing any code.

## Step 0 — Geographic dimension (FIRST CHECK)

Before any other decision, check whether the question has a spatial component:
- Are there columns named `latitude`, `longitude`, `STATION_NAME`, `station`, `deployment_id`?
- Does the question mention a location, station, area, map, carte, distribution spatiale?

If yes → the graph must include the geographic dimension:
- **map**: station distribution on a real cartopy map with coastlines and projection
- **geo scatter**: abundance or biomass as a function of position (lat or lon on X axis)
- **bar by station**: compare a variable across named stations

**In NeoLab data, "where" comes before "what".** Analyses without geographic anchoring lose critical information.

### Choosing the right map type

| Situation | Graph type | Projection |
|-----------|-----------|------------|
| Show station locations (Arctic/Amundsen, lat > 55°N) | **map** with cartopy NorthPolarStereo | `NorthPolarStereo` |
| Show station locations (Hawke Channel, Hudson Strait, Ungava Bay, lat 52–63°N) | **map** with cartopy LambertConformal or PlateCarree | `LambertConformal` |
| Color stations by a variable (abundance, temp, salinity) | **map** with cartopy + color scale | same as above |
| Variable vs latitude/longitude profile | **geo scatter** (simple scatter, no cartopy) | none |
| Compare named stations | **bar by station** | none |

**Known NeoLab zones and their projection:**

| Zone | Lat range | Lon range | Projection recommandée |
|---|---|---|---|
| Hawke Channel | 52–56°N | 53–57°W | `LambertConformal(central_longitude=-55, central_latitude=54)` |
| Détroit d'Hudson | 60–63°N | 64–80°W | `LambertConformal(central_longitude=-72, central_latitude=61)` |
| Baie d'Ungava | 58–62°N | 67–74°W | `LambertConformal(central_longitude=-70, central_latitude=60)` |
| Baie d'Hudson | 51–65°N | 77–95°W | `LambertConformal(central_longitude=-86, central_latitude=58)` |
| Arctique / Amundsen | > 65°N | — | `NorthPolarStereo` |

**Always use `map` (cartopy) when the user asks for a geographic map, carte, or spatial distribution.** Never produce a plain scatter on lon/lat axes for a map request — it has no geographic context (no coastlines, no projection).

## Step 0b — NeoLabs taxonomy-abundance level check

If the loaded table has NeoLabs abundance columns such as `SAMPLE_ID`, `ANALYSIS_ID`, `TAXON_ID`, `ZOOPLANKTON_CATEGORY`, and `Total abundance (ind./m3 depth vol)`, treat it as a taxon-level table.

Mandatory rule:
- For temporal, spatial, station-level, CTD, diversity, anomaly, and ordination plots, first rebuild `sample_df` with one row per `SAMPLE_ID + ANALYSIS_ID`.
- Do not plot raw taxon-level rows as independent samples for station/date/environment summaries.
- Use `Total abundance (ind./m3 depth vol)` as the default abundance column and label the unit as `ind./m3`.
- Use `ctd_match_status == "matched"` before plotting abundance against Amundsen CTD variables.
- For top-taxon plots, raw taxon-level rows are valid, but aggregate by `TAXON_ID` first.

Recommended `sample_df` contents:
- sample key: `SAMPLE_ID + ANALYSIS_ID`
- metadata: station, year, month, latitude, longitude, depth interval
- biology: total abundance, copepod abundance, taxon richness
- CTD QA: `ctd_match_status`, `ctd_distance_km`, `ctd_time_delta_min`, `ctd_depth_coverage_m`
- environment: temperature, salinity, oxygen, fluorescence, nitrate from Amundsen interval means

For ordination requests (`PCA`, `PCoA`, `NMDS`, `RDA`, `CCA`, `ordination`):
- plan a taxon matrix (`sample x taxon`) plus an environmental `sample_df`
- filter to positive-abundance samples
- use Bray-Curtis for PCoA/NMDS taxonomic composition
- standardize CTD variables for PCA/RDA
- present the result as exploratory unless a formal model/test is included

## Required steps

1. Identify the relevant columns in the loaded file
2. Check the geographic dimension (step 0)
3. Check whether NeoLabs taxon-level data requires a rebuilt `sample_df` (step 0b)
4. Decide the output type based on the user's prompt:
   - If the prompt explicitly mentions "graphique", "graphe", "carte", "visualise", "plot", "chart", "map", "trace", "tracer", "affiche", "montre", "profil vertical", "profil verticale", "vertical profile", or asks to produce a profile, map, chart, graph, plot, or figure → **visual output** (use run_graph after graph_writer)
   - Otherwise → **table output** (use run_pandas to return a markdown table)
5. If visual output: choose the graph type:
   - **map**: spatial distribution of stations or observations
   - **sampling gap map**: stations coloured by coverage status (present / sparse / absent) per zone — use when the user asks about undersampled zones, lacunes, missing coverage, or where to sample next. Color: green = ≥ 10 obs, orange = 1–9 obs, red = 0 obs.
   - **climate delta map**: stations coloured by delta (Bio-ORACLE projected − CTD current) — use when the user asks about warming, SSP projections, or climate change impact by zone. Use a diverging colormap (coolwarm), centre at 0.
   - **geo scatter**: variable as a function of latitude or longitude
   - **bar by station**: comparison across named stations
   - **bar**: compare categories without geo component (e.g. abundance by taxon)
   - **line**: evolution over time or depth
   - **scatter**: relationship between two numeric variables (e.g. temperature vs depth)
   - **histogram**: distribution of a numeric variable
6. Define the relevant columns, aggregations (groupby, pivot, agg), and filters
   - For station/sample/profile/cast/taxon filters, preserve identifiers as labels and normalize comparisons as text. Example: use `df["STATION_NAME"].astype(str).str.strip() == str(station).strip()`, never `int(station)` for filtering.
7. Flag any missing values that could affect the output
8. **Uncertainty assessment (CT-AG-27)** — for each row going into the graph, classify it as:
   - **confirmed**: validated source (EcoTaxa statut V), required columns complete, no missing volume/calibration
   - **exploratory**: at least one of — taxon not validated (statut != V), partial column (NaN in a non-critical field), join with tolerance, derived variable without canonical method
   - **uncertain identification**: morphologically ambiguous taxon (e.g. *C. glacialis* vs *C. finmarchicus* in overlap zones), historical pre-molecular identification
   Count each category and report the confidence level: `high` (≥ 95% confirmed), `medium` (≥ 70% confirmed), `low` (< 70% confirmed). Pass these counts to `graph_writer` via the plan.

## Plan format

Output the plan wrapped in a `<details>` block so it is hidden by default:

```
<details>
<summary>Output plan</summary>

- Output: <visual | table>
- Type: <map | geo scatter | bar by station | bar | line | scatter | histogram | table>
- Geo dimension: <yes — lat/lon/station columns used | no>
- X / Rows: <column name>
- Y / Values: <column name>
- Aggregation: <sum | mean | count | none>
- Filter: <condition or "none">
- Confidence: <high | medium | low>
- Rows confirmed / exploratory / uncertain: <n_confirmed> / <n_exploratory> / <n_uncertain>
- Uncertainty notes: <short reason — e.g. "12 rows without volume", "3 rows pre-molecular ID">

</details>
```

The plan is not the final answer for visual output. For any visual output, after this plan the agent must immediately use `graph_writer` and execute the generated matplotlib code with `run_graph` in the same turn. Never answer the user with only this `<details>` block unless a real blocker makes the figure impossible.
