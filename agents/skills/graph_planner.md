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

## Required steps

1. Identify the relevant columns in the loaded file
2. Check the geographic dimension (step 0)
3. Decide the output type based on the user's prompt:
   - If the prompt explicitly mentions "graphique", "carte", "visualise", "plot", "chart", "map" → **visual output** (use run_graph after graph_writer)
   - Otherwise → **table output** (use run_pandas to return a markdown table)
4. If visual output: choose the graph type:
   - **map**: spatial distribution of stations or observations
   - **geo scatter**: variable as a function of latitude or longitude
   - **bar by station**: comparison across named stations
   - **bar**: compare categories without geo component (e.g. abundance by taxon)
   - **line**: evolution over time or depth
   - **scatter**: relationship between two numeric variables (e.g. temperature vs depth)
   - **histogram**: distribution of a numeric variable
5. Define the relevant columns, aggregations (groupby, pivot, agg), and filters
6. Flag any missing values that could affect the output
7. **Uncertainty assessment (CT-AG-27)** — for each row going into the graph, classify it as:
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
