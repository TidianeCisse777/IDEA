# Skill: graph_planner

You must plan a graph before writing any code.

## Step 0 — Geographic dimension (FIRST CHECK)

Before any other decision, check whether the question has a spatial component:
- Are there columns named `latitude`, `longitude`, `STATION_NAME`, `station`, `deployment_id`?
- Does the question mention a location, station, area, or spatial distribution?

If yes → the graph must include the geographic dimension:
- **map**: station distribution on a map (scatter lat/lon)
- **geo scatter**: abundance or biomass as a function of position (lat or lon on X axis)
- **bar by station**: compare a variable across named stations

**In NeoLab data, "where" comes before "what".** Analyses without geographic anchoring lose critical information.

## Required steps

1. Identify the relevant columns in the loaded file
2. Check the geographic dimension (step 0)
3. Choose the appropriate graph type:
   - **map**: spatial distribution of stations or observations
   - **geo scatter**: variable as a function of latitude or longitude
   - **bar by station**: comparison across named stations
   - **bar**: compare categories without geo component (e.g. abundance by taxon)
   - **line**: evolution over time or depth
   - **scatter**: relationship between two numeric variables (e.g. temperature vs depth)
   - **histogram**: distribution of a numeric variable
4. Define axes: which column for X, which for Y
5. Identify required aggregations (groupby, pivot, agg)
6. Flag any missing values that could affect the graph

## Plan format

Return the plan in this format before writing any code:

```
Graph plan:
- Type: <map | geo scatter | bar by station | bar | line | scatter | histogram>
- Geo dimension: <yes — lat/lon/station columns used | no>
- X: <column name>
- Y: <column name>
- Aggregation: <sum | mean | count | none>
- Filter: <condition or "none">
```
