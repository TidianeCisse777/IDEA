# Skill: bio_oracle_query

Bio-ORACLE data is now loaded or being requested. Follow the workflow below.

---

## Tool selection

| Request | Tool to call |
|---|---|
| Values for one or more **named zones** (Hawke Channel, Mer du Labrador, Baie d'Hudson…) | `query_bio_oracle_zones` |
| Values for a **single lat/lon point** | `preview_bio_oracle_point` |
| Couple zooplankton rows (< 10) with Bio-ORACLE | `couple_zooplankton_bio_oracle` |
| List available datasets/variables | `list_bio_oracle_datasets` |

**Always use `query_bio_oracle_zones` for zone-level requests — never batch `preview_bio_oracle_point` in a loop.**

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
| `SSP1-2.6` | Low emissions 2100 |
| `SSP2-4.5` | Intermediate emissions 2100 |
| `SSP5-8.5` | High emissions 2100 |

---

## Workflow — CTD × climate projection (funding argument)

This is the most impactful analysis for grant justification. Execute all steps in **one single `run_pandas` call** after getting Bio-ORACLE values:

```
Step 1 — call query_bio_oracle_zones(zones=[...], variable="temperature", scenario="SSP5-8.5", depth_layer="surface")
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
