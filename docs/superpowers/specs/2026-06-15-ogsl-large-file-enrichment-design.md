# OGSL Large-File Enrichment Design

## Goal

Enrich large biological tables with OGSL CTD measurements without issuing one
remote request per source row. Preserve every source row and expose explicit
match-quality fields.

## Scope

This design covers files containing thousands of observations where station,
sampling time, and optionally sampling depth vary by row.

It extends the existing `query_ogsl` LangChain tool. The tool remains responsible
for reading source values directly from the active session; the agent never
transcribes observation rows into tool arguments.

## Tool Contract

`query_ogsl` accepts:

- `station_column`: required source station identifier column.
- `time_column`: required source sampling timestamp column.
- `depth_column`: optional source depth or pressure column.
- `variables`: optional OGSL variables, defaulting to `PRES`, `TE90`, `PSAL`,
  and `OXYM`.
- `time_tolerance_hours`: default `24`.
- `depth_tolerance_m`: default `10`.

The tool returns the names of two persisted tables:

- `df_ogsl`: raw OGSL measurements downloaded for the requested station windows.
- A stable derived enrichment table containing all source rows and OGSL match
  columns.

## Acquisition Strategy

1. Parse source timestamps as UTC without modifying the source table.
2. Group valid source rows by unique station identifier.
3. For each station, compute:
   - `start = minimum source time - 24 hours`
   - `end = maximum source time + 24 hours`
4. Send one OGSL ERDDAP request per unique station with that station-specific
   window.
5. Concatenate all returned profiles into the raw `df_ogsl` table.

The number of remote requests therefore scales with unique stations, not source
rows. Ten thousand observations across twenty stations require twenty requests.

## Matching Strategy

Matching is local after acquisition.

For each source row:

1. Restrict candidates to the same station.
2. Select the nearest OGSL cast timestamp.
3. Reject the candidate when the absolute time difference exceeds 24 hours.
4. If `depth_column` is present:
   - select the candidate measurement with nearest `PRES`;
   - reject it when the absolute pressure/depth difference exceeds 10 m/dbar.
5. If `depth_column` is absent:
   - select the minimum `PRES` measurement from the nearest cast.

Pressure in dbar is treated as an approximate depth in metres for this matching
threshold. The output field keeps the neutral name `ogsl_depth_delta_m`.

## Output Columns

The derived table preserves all source columns and adds:

- Selected OGSL variables with an `ogsl_` prefix.
- `ogsl_station_id`
- `ogsl_time`
- `ogsl_pres`
- `ogsl_cruise_id`
- `ogsl_cast_number`
- `ogsl_time_delta_min`
- `ogsl_depth_delta_m`
- `ogsl_match_status`

`ogsl_match_status` values:

- `matched`
- `no_match`
- `missing_station`
- `missing_time`
- `invalid_time`
- `missing_depth`
- `invalid_depth`

Rows outside either tolerance remain in the derived table with OGSL measurement
columns empty and `ogsl_match_status="no_match"`.

## Raw Data Integrity

- The uploaded source DataFrame is never modified in place.
- The downloaded OGSL table is stored separately as `df_ogsl`.
- The enriched table is a new persisted dataset.
- Source row order and cardinality are preserved.

## Volume And Safety

- Remote requests are deduplicated by station.
- Requests are sequential initially to avoid overloading the public OGSL ERDDAP
  service.
- More than ten unique stations requires explicit agent confirmation under the
  existing heavy-operation policy.
- Empty OGSL responses for one station do not fail the full acquisition.
- Invalid source rows are retained and classified through match status.

## Agent Routing

For OGSL enrichment, the system prompt instructs the agent to call `query_ogsl`
with source column names. The tool performs acquisition and enrichment itself.
The agent must not execute a second manual join through `run_pandas`.

`load_skill("environmental_join")` remains appropriate for exploratory or
non-standard joins, but is not required for this standard OGSL enrichment path.

## Testing

Deterministic tests cover:

- thousands of source rows causing one request per unique station;
- station-specific minimum and maximum windows with 24-hour padding;
- nearest-time matching;
- nearest-pressure matching within 10 m/dbar;
- surface selection when depth is absent;
- unmatched and invalid metadata statuses;
- source row order, row count, and column preservation;
- persistence of raw and derived tables.

The LangSmith trajectory dataset is updated to expect:

`load_file -> query_ogsl`

The evaluator verifies safe column-name arguments, raw OGSL persistence, derived
table persistence, row-count preservation, and match-quality columns.
