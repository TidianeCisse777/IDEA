# Skill: bio_oracle_query

Bio-ORACLE data is now loaded or being requested. Follow the workflow below.

---

## Tool selection

| Request | Tool to call |
|---|---|
| Values for one or more **named zones** (Hawke Channel, Mer du Labrador, Baie d'Hudson…) | `query_bio_oracle_zones` |
| Values for a **single lat/lon point** | `preview_bio_oracle_point` |
| Couple zooplankton rows, stations, "les mêmes stations", or top N stations with Bio-ORACLE | `couple_zooplankton_bio_oracle` |
| List available datasets/variables | `list_bio_oracle_datasets` |

**Always use `query_bio_oracle_zones` for zone-level requests — never batch `preview_bio_oracle_point` in a loop.**
**Never use `query_bio_oracle_zones` for a per-station request**, even if the stations are in named zones. Zone queries return one value per zone centre; station coupling needs one value per station coordinate.

For per-row coupling, pass the latitude and longitude column names from the
loaded table. The coupling tool reads the session directly and preserves all
source columns. Never construct or transcribe station rows in tool arguments.

For "top 10 stations", "les mêmes stations", or "par station" follow-up requests,
pass `station_column`, `sample_column`, `top_n_stations`, and `scenarios` to
`couple_zooplankton_bio_oracle`. Do not create placeholder columns with `pd.NA`.

`couple_zooplankton_bio_oracle` can:
- enrich each source row at its own latitude/longitude;
- build a station table internally for top N / "les mêmes stations" requests;
- compare multiple Bio-ORACLE scenarios in one call;
- apply a requested future horizon with `target_year` to SSP scenarios;
- return traceability columns: value, `time` / `time_<scenario>`, and
  `dataset_id` / `dataset_id_<scenario>`.

---

## Variable names (always use these — never ERDDAP internal names)

| Friendly name | Use for |
|---|---|
| `temperature` | Sea surface / subsurface temperature |
| `salinity` | Salinity |
| `oxygen` | Dissolved oxygen |
| `chlorophyll` | Chlorophyll-a |
| `nitrate` | Nitrate concentration |

## Scenarios

| Friendly name | Meaning |
|---|---|
| `baseline` | Present-day (2000–2018) |
| `SSP1-2.6` | Low emissions future scenario |
| `SSP2-4.5` | Intermediate emissions future scenario |
| `SSP5-8.5` | High emissions future scenario |

If the user mentions a year or horizon (`2050`, `en 2050`, `horizon 2050`,
`2041-2060`, `milieu de siècle`, `fin de siècle`), pass `target_year` to the
Bio-ORACLE tool. Baseline is historical, not future: do not expect
`time_baseline` to equal 2050. The tools ignore `target_year` for baseline and
apply it only to SSP datasets. Verify year-specific requests on `time_ssp*`
columns. Never answer a year-specific request by reusing a previously loaded
scenario column unless the associated `time` / `time_<scenario>` column or
metadata matches that requested year. A column named `temperature_ssp1_2_6` by
itself does not prove whether it is 2050 or the dataset's last time slice.

### SSP decadal slices and how to be honest about the target year

Bio-ORACLE SSP datasets contain 8 decadal time slices (2020, 2030, 2040,
2050, 2060, 2070, 2080, 2090); each value is a 10-year mean. When a
`target_year` is passed, the ERDDAP client returns the nearest decade;
without one, it returns the **last available slice** (2090).

The huge gap between mid- and end-of-century is real (Labrador Sea
SSP5-8.5 surface temperature: ~3.4 °C at 2050 vs ~5.9 °C at 2090). Always
state the decade in the answer to avoid the reader misreading the table:

- If the user named a year/horizon, pass `target_year` and write
  `"Année cible : 2050"` in the answer.
- If the user did NOT name one, do not invent one — let the client default
  to 2090, write `"Année cible : 2090 (dernière décennie SSP, par défaut)"`,
  and add a short note offering to redo at 2050 or 2070 if needed.

For `baseline`, no year disclosure is needed (single climatology).

---

## Workflow — CTD × climate projection (funding argument)

This is the most impactful analysis for grant justification. Choose the workflow
by requested granularity.

### Per-station workflow

Use this when the user says "par station", "chaque station", "les mêmes
stations", "top 10 stations", or provides a station table with latitude/longitude:

```
Step 1 — call couple_zooplankton_bio_oracle(
  latitude_column="latitude",
  longitude_column="longitude",
  variable="temperature",
  scenario="baseline",
  depth_layer="surface",
  station_column="STATION_NAME",
  sample_column="SAMPLE_ID",
  top_n_stations=10,
  scenarios=["baseline", "SSP1-2.6", "SSP5-8.5"],
  target_year=2050  # only when the user requested 2050 or a matching horizon
)
Step 2 — use run_pandas only to summarize the coupled dataset returned by the tool.
```

### Zone workflow

Use this only when the user explicitly asks for named-zone values or zone-level
comparisons. Execute all steps in **one single `run_pandas` call** after getting
Bio-ORACLE values:

```
Step 1 — call query_bio_oracle_zones(zones=[...], variable="temperature", scenario="SSP5-8.5", depth_layer="surface", target_year=2050 if requested)
Step 2 — in ONE run_pandas call:
  a. filter the loaded DataFrame to the zones
  b. compute mean CTD temperature per station (amundsen_temperature_degC_nearest or _mean_sample_interval)
  c. join with Bio-ORACLE projected value (from the table returned in Step 1)
  d. compute delta = bio_oracle_projected - ctd_current
  e. assign result to a variable AND return it
Step 3 — call load_skill("graph_planner") then run_graph for a map coloured by delta
```

**Critical**: compute the delta and the summary statistics in the same `run_pandas` call — do not split into two calls or you will get a NameError on the second call.

---

## Limits

- Bio-ORACLE resolution ~5 arc-minutes (~9 km) — one value per zone centre, not per station.
- Interpretation of ecological impact belongs to the researcher.
- `depth_layer="surface"` is the default for sea surface temperature comparison with CTD surface observations.
