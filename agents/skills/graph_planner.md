# Skill: graph_planner

You must plan a graph before writing any code.

## Execution truth

- If the selected table has zero rows, stop: report the empty result and do not
  plan or execute a graph.
- Never invent or reuse an artifact URL. Only the exact artifact returned by a
  successful `run_graph` call may appear in the final answer.
- A blocked contract, exception, or error is not a graph result. Surface the
  failure and do not claim that a figure exists.
- Plan only from the explicitly selected source variable. Never switch sources
  or transcribe values to make a graph possible.

## Step 0 — Geographic dimension (FIRST CHECK)

Before any other decision, check whether the question has a spatial component:
- Are there columns named `latitude`, `longitude`, `STATION_NAME`, `station`, `deployment_id`?
- Does the question mention a location, station, area, map, carte, distribution spatiale?

If yes → the graph must include the geographic dimension. A cartopy map takes
one of two contract kinds (never `kind:"map"` or `kind:"scatter"` — the
validator rejects those):
- **`station_map`**: sample positions on a real cartopy map with coastlines and
  projection; optional size/colour for a **non-abundance** variable (number of
  samples per position, taxa richness, counts). This is the default for
  "positions des échantillons", "où sont les samples", "nombre de taxons par
  échantillon". Do **not** manufacture an `abundance_ind_L` column for it.
- **`abundance_environment_map`**: only when size encodes measured
  `abundance_ind_L` and colour encodes an environmental variable.
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

**Known NeoLab zones and their projection** (centres only — for accurate
filtering use `get_zone_info(zone_name=...)` which returns the precise polygon
and bbox from the IHO-based registry):

| Zone | Centre approx. | Projection recommandée |
|---|---|---|
| Hawke Channel | 54°N, -55°W | `LambertConformal(central_longitude=-55, central_latitude=54)` |
| Détroit d'Hudson | 61°N, -72°W | `LambertConformal(central_longitude=-72, central_latitude=61)` |
| Baie d'Ungava | 60°N, -70°W | `LambertConformal(central_longitude=-70, central_latitude=60)` |
| Baie d'Hudson | 58°N, -86°W | `LambertConformal(central_longitude=-86, central_latitude=58)` |
| Baie de James | 53°N, -81°W | `LambertConformal(central_longitude=-81, central_latitude=53)` |
| Mer du Labrador | 58°N, -55°W | `LambertConformal(central_longitude=-55, central_latitude=58)` |
| Baie de Baffin | 75°N, -65°W | `LambertConformal(central_longitude=-65, central_latitude=75)` |
| Arctique / Amundsen | > 65°N | `NorthPolarStereo` |

**Always use a cartopy map (`station_map`, or `abundance_environment_map` for true abundance) when the user asks for a geographic map, carte, or spatial distribution.** Never produce a plain scatter on lon/lat axes for a map request — it has no geographic context (no coastlines, no projection) — and never emit `kind:"map"` or `kind:"scatter"` in the contract.

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
4. Decide from the requested output intent, not from a closed list of words:
   - A request for or clear implication of a visual representation of the data is a **visual output**. This includes a map or a plotted profil vertical even when the user does not explicitly say "graph".
   - A number, calculation, ranking, summary, coordinates, or table is **non-visual** unless the user also asks for a graphical representation. General presentation verbs such as "show", "display", or "present" do not make it visual by themselves.
   - If the format is genuinely ambiguous, prefer the minimal non-visual answer and do not load this skill. Ask only when the format would materially change the requested result.
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
   - **vertical profile**: abundance, biomass, temperature, salinity, oxygen, or fluorescence by depth. Put the measurement on X, depth on Y, and invert Y so deeper values are lower.
   - **taxonomic composition**: stacked bar chart of relative or absolute abundance by taxon across station, month, depth bin, sample, or zone.
   - **composition heatmap**: heatmap of log1p or relative abundance for dominant taxa across station, month, depth bin, sample, or zone.
   - **rarefaction**: expected taxon richness as a function of sample size / sampling effort. Use only count-like non-negative taxon matrices.
   - **species accumulation**: cumulative observed richness as sites/samples are added, preferably with permutation mean and interval if enough samples exist.
   - **rank-abundance**: taxa ordered by decreasing total or relative abundance.
   - **NMDS**: exploratory Bray-Curtis ordination of taxonomic composition.
   - **PCoA**: exploratory Bray-Curtis principal coordinates ordination of taxonomic composition.
   - **PCA/RDA/CCA**: exploratory environment/community ordination when the request explicitly names the method or asks for community-environment structure.
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

The plan is not the final answer for visual output. For any visual output, after this plan the agent must immediately use `graph_writer` and execute the generated matplotlib code with `run_graph` in the same turn. Never call `run_graph` immediately after `load_skill("graph_planner")`: first call `load_skill("graph_writer")`, then the next execution call is `run_graph`. Never answer the user with only this `<details>` block unless a real blocker makes the figure impossible.
