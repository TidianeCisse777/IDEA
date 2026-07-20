# EcoTaxa sample-level deployment metadata

Date: 2026-07-20

## Goal

Let the agent answer EcoTaxa questions about sample dates, hours, depths,
positions, instruments, casts, and object counts without exporting individual
objects. The SQLite cache remains the primary exploration path and keeps
exactly one row per sample. A direct EcoTaxa call supplies a detailed or
fallback view for one resolved sample.

EcoTaxa sample statistics are the authoritative source for object and
classification counts. Object metadata rows are used only to compute temporal
and depth envelopes.

## Scope

The change covers:

- sample-level cache schema and migration in
  `core/ecotaxa_browser/cache/repo.py`;
- cache synchronization and sample-level aggregation in
  `core/ecotaxa_browser/cache/sync.py`;
- direct sample deployment summaries in
  `core/ecotaxa_browser/deployment_summary.py`;
- rendering and cache-query documentation in `tools/copepod_sources.py`;
- EcoTaxa navigation instructions in `agents/skills/ecotaxa_navigation.md` and
  the compact routing rule in `agents/copepod_system_prompt.py`;
- the matching inventory entry in `TOOLS.md`;
- focused repository, synchronization, navigation, source-tool, prompt, and
  skill tests.

The following remain unchanged:

- one `samples_cache` row is one EcoTaxa sample;
- `profile_id`, station handling, and cast inference;
- the 50,000-object cap per project during cache synchronization;
- object exports, images, taxonomy semantics, and source authorization.

## Architecture

### Cached exploration

Questions spanning samples or projects use `query_ecotaxa_cache`. This includes:

- samples before, after, or overlapping a date range;
- samples observed within an hour-of-day range;
- samples overlapping a date-time interval;
- samples whose scanned depth envelope overlaps a requested depth range;
- groupings by year, hour, project, zone, instrument, station, or cast;
- authoritative object and V/P/D/U counts at sample grain.

The query result persists in the existing canonical EcoTaxa cache DataFrame.
No project-by-project live API sweep is introduced for ordinary exploration.

### Direct sample detail and fallback

Once a sample is resolved, `summarize_ecotaxa_sample_deployment` provides its
detailed deployment view directly from EcoTaxa. This path is also the fallback
when a selected cache row has missing or partial temporal/depth metadata.

The fallback remains one-sample-at-a-time. The agent must not silently call it
for a large set of incomplete cache rows. For a multi-sample query, it reports
cache coverage and offers targeted verification rather than creating an
unbounded remote scan. A direct verification is session-local and does not
write through to the shared cache; the next synchronization remains responsible
for cache refresh.

## Official API composition

Both synchronization and direct detail preserve EcoTaxa's sample grain while
composing four official resources:

1. `GET /sample/{sample_id}` or `GET /samples/search` supplies sample identity,
   project, position, and sample free columns.
2. `GET /acquisitions/search?project_id=...` supplies acquisitions linked to a
   sample, including instrument and acquisition free columns.
3. `GET /sample_set/taxo_stats?sample_ids=...` supplies authoritative
   `nb_validated`, `nb_predicted`, `nb_dubious`, and `nb_unclassified` counts.
4. `POST /object_set/{project_id}/query` supplies only the metadata required for
   the sample envelope: `obj.objdate,obj.objtime,obj.depth_min,obj.depth_max`
   and, for direct detail, `obj.acquisid`.

Object queries stay ordered by the unique `obj.objid` field so pagination is
stable. The authoritative object total is the sum of the four sample-stat
counters. The object-query `total_ids` value is a consistency signal and never
silently replaces the sample-stat total.

## Cache schema

`samples_cache` keeps its existing columns and adds:

| Column | Type | Meaning |
|---|---|---|
| `datetime_min` | TEXT | Earliest complete object timestamp scanned, ISO 8601 |
| `datetime_max` | TEXT | Latest complete object timestamp scanned, ISO 8601 |
| `time_min` | TEXT | Earliest non-null object time-of-day scanned, `HH:MM:SS` |
| `time_max` | TEXT | Latest non-null object time-of-day scanned, `HH:MM:SS` |
| `temporal_precision` | TEXT | `datetime`, `date`, `partial`, or `none` |
| `missing_date_count` | INTEGER | Scanned rows without a valid object date |
| `missing_time_count` | INTEGER | Scanned rows without a valid object time |
| `missing_depth_min_count` | INTEGER | Scanned rows without `depth_min` |
| `missing_depth_max_count` | INTEGER | Scanned rows without `depth_max` |
| `depth_complete` | INTEGER | 1 only when the full sample was scanned and every row had both depths |
| `metadata_objects_scanned` | INTEGER | Object metadata rows aggregated for this sample |
| `metadata_complete` | INTEGER | 1 only when every authoritative sample object was scanned |
| `metadata_coverage_pct` | REAL | Scanned metadata rows divided by authoritative object count |

The existing fields remain:

- `date_min` and `date_max` for date-only queries and compatibility;
- `depth_min` and `depth_max` for the scanned vertical envelope;
- `object_count` and V/P/D/U counters from sample statistics;
- identifiers, position, instrument, free fields, and zone.

An index is added for `datetime_min, datetime_max`. Existing date and depth
indexes remain. Hour-of-day queries use `time_min` and `time_max`; they do not
require an additional index at the current cache size.

## Migration and refresh

The cache schema version increments. `init_schema` adds the new nullable
columns idempotently. Existing rows remain readable while their new fields are
null. The current schema-version mechanism marks the database as needing a full
resynchronization; the new version is stamped only after that synchronization
succeeds.

No value is derived from stale `date_min` alone during migration. Time and
coverage fields are populated only from a new EcoTaxa synchronization.

## Sample aggregation

For every scanned object row:

- preserve every valid `objdate` for `date_min/max`;
- preserve every valid `objtime` for `time_min/max`;
- combine valid date/time pairs into normalized ISO timestamps for
  `datetime_min/max`;
- take the minimum non-null `obj.depth_min`;
- take the maximum non-null `obj.depth_max`;
- count missing or invalid date, time, and depth values separately;
- increment the sample's `metadata_objects_scanned` counter.

No time, date, or depth is inferred or repaired.

`temporal_precision` is:

- `datetime` when every scanned row carries a valid date and time;
- `date` when every scanned row carries a valid date but one or more times are
  absent or invalid;
- `partial` when at least one valid date exists but other scanned rows have no
  valid date;
- `none` when no valid object date was scanned.

After sample statistics are fetched:

- `object_count` is the authoritative V/P/D/U sum;
- `metadata_complete` is true only when
  `metadata_objects_scanned == object_count`;
- `metadata_coverage_pct` is the ratio of those values, capped at 100%;
- `depth_complete` is true only when metadata coverage is complete and no
  scanned row is missing either depth bound;
- an empty sample has exact zero counts, 100% metadata coverage, no temporal or
  depth envelope, zero missing-value counts, and no invented values.

If sample statistics are unavailable or contain no entry for a sample,
`object_count`, V/P/D/U, `metadata_complete`, `metadata_coverage_pct`, and
`depth_complete` remain null for that sample. The synchronization may still
cache its identity, position, and scanned envelopes, but it must not substitute
the capped object-scan count. A real empty sample is distinguishable because
EcoTaxa sample statistics return an explicit record whose four counters are
zero.

Because the project scan remains capped, some samples will legitimately have
partial or absent envelopes. Their exact counts and positions remain usable,
but temporal/depth filters must not treat their absence as proof that they do
not match.

## Query semantics and reliability

Cache SQL examples and navigation instructions explicitly cover:

- date overlap:
  `date_min <= :end_date AND date_max >= :start_date`;
- date-time overlap:
  `datetime_min <= :end_datetime AND datetime_max >= :start_datetime`;
- hour-of-day overlap:
  `time_min <= :end_time AND time_max >= :start_time`;
- depth overlap:
  `depth_min <= :requested_max AND depth_max >= :requested_min`.

For exact sample-envelope claims, queries use these guards:

- date: `metadata_complete = 1 AND missing_date_count = 0`;
- hour of day: `metadata_complete = 1 AND missing_time_count = 0`;
- date-time: `metadata_complete = 1 AND temporal_precision = 'datetime'`;
- depth: `depth_complete = 1`.

Query results also report how many cache rows were incomplete or lacked the
requested field for the requested scope.

A filter over complete rows is an exact result for those rows, not proof that
incomplete rows do not match. User-facing responses state this limitation and
offer direct verification of a specific sample when needed.

Hour-of-day envelopes are clock-time ranges over the scanned object metadata;
matching means the sample envelope overlaps the requested range, not that an
individual object is returned from the cache.
For an interval crossing midnight, the SQL predicate must use the explicit
wraparound envelope form (`time_max >= :start_time OR time_min <= :end_time`)
rather than a simple `BETWEEN`.
Queries tied to concrete dates should prefer `datetime_min/max`.

## Direct deployment summary

The direct summary retains the existing sample, position, acquisition, and
free-field sections. It adds:

- authoritative V/P/D/U and total counts from sample statistics;
- `obj.objtime` in the object metadata scan;
- `datetime_min/max`, `time_min/max`, and `temporal_precision`;
- `objects_scanned`, authoritative total, coverage percentage, and
  `metadata_complete`;
- the object-query total and a discrepancy flag when it differs from sample
  statistics.

The existing 50,000-object direct scan limit remains. When the scan is partial,
date/time and depth extrema are labeled as partial values over scanned rows and
are never presented as the definitive deployment envelope.

## Error handling

- Failure to retrieve or resolve the sample is fatal because the project and
  sample scope cannot be established.
- Failure of sample statistics is fatal for the direct summary; object-query
  totals are not used as a silent fallback.
- Existing API exceptions continue through the structured EcoTaxa error
  boundary.
- A disagreement between successful endpoints is data-quality information, not
  an exception: return both totals, mark the metadata incomplete, and expose the
  discrepancy.
- A cache row with null or incomplete metadata remains a valid sample row. The
  agent reports incomplete coverage instead of converting null to zero or
  claiming absence.
- Failure of one cache sample-stat batch is non-fatal for synchronization, but
  all count and completeness fields for affected samples remain null; no scan
  count is promoted to an authoritative total.

## Tool and instruction behavior

`query_ecotaxa_cache` remains the default for cross-sample time, date, depth,
zone, station, cast, project, and count questions. Its schema description and
examples include the new columns and reliability predicates.

`ecotaxa_navigation` documents:

- which cached fields are authoritative sample-level values;
- which fields are object-derived envelopes;
- how to write date, date-time, hour, and depth overlap predicates;
- how to report incomplete cache coverage;
- when to use the direct one-sample deployment summary as fallback.

The compact system prompt names hour/date-time/depth questions explicitly in
the cache-first routing rule. It does not duplicate the detailed policy owned
by the skill.

## Testing strategy

Implementation follows the repository TDD rule. Tests are written before code
for these cases:

1. Schema initialization and migration add every new column and datetime index
   without changing existing rows or cast fields.
2. A stale schema version requests a full resynchronization and the new version
   is stamped only after success.
3. Synchronization requests `obj.objtime` and aggregates date, time, datetime,
   depth, and scanned-row counts per sample.
4. Sample statistics remain the source of object and V/P/D/U counts.
5. Samples before and after the 50,000-object project cap receive correct
   `metadata_complete` and coverage values.
6. Missing or invalid times retain the date envelope without inventing a
   timestamp and set `temporal_precision=date`.
7. Empty samples have exact zero counts, complete coverage, and null envelopes.
8. Cache SQL can query date-time, hour-of-day, date, and depth ranges, including
   a wraparound hour interval.
9. The direct summary requests `obj.objtime`, uses sample statistics for counts,
   and exposes partial coverage or endpoint discrepancies.
10. User-facing rendering visibly distinguishes exact counts from partial
    temporal/depth envelopes.
11. The navigation skill and compact prompt keep cache-first routing and include
    the new reliability rules.
12. Existing cast/profile, zone, sample-stat, cache-query, and deployment tests
    remain green.

Focused verification runs repository/cache-sync/navigation/source-tool tests
first, then the broader EcoTaxa test set. A final live read-only check uses an
accessible sample and the refreshed cache without exporting objects or images.

## Acceptance criteria

- The cache remains strictly one row per sample.
- Cast, profile, and station behavior are unchanged.
- Cross-sample date, hour, date-time, and depth questions use the cache.
- All object and V/P/D/U counts come from sample statistics.
- EcoTaxa object times are retained when present and never invented.
- Partial cache or direct scans are visible and cannot be reported as complete
  deployment envelopes.
- A resolved sample with incomplete cached metadata can be verified through the
  existing direct sample summary.
- No credential, scientific interpretation, source-policy duplication, image
  download, or object export is introduced.
