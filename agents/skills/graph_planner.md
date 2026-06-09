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
| Color stations by a variable (abundance, temp, salinity) | **map** with cartopy + color scale | `NorthPolarStereo` |
| Variable vs latitude/longitude profile | **geo scatter** (simple scatter, no cartopy) | none |
| Compare named stations | **bar by station** | none |

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

## Plan format

Return the plan in this format before writing any code:

```
Output plan:
- Output: <visual | table>
- Type: <map | geo scatter | bar by station | bar | line | scatter | histogram | table>
- Geo dimension: <yes — lat/lon/station columns used | no>
- X / Rows: <column name>
- Y / Values: <column name>
- Aggregation: <sum | mean | count | none>
- Filter: <condition or "none">
```
