# EcoTaxa sample deployment API alignment

Date: 2026-07-20

## Goal

Make the direct EcoTaxa deployment summary for one sample use the current API
semantics precisely while keeping remote work bounded. EcoTaxa sample statistics
are the authoritative source for object and classification counts. Object rows
are used only to compute the temporal and depth envelope of the sample.

## Scope

The change is limited to the direct path behind
`summarize_ecotaxa_sample_deployment`:

- `core/ecotaxa_browser/deployment_summary.py`
- the rendering and tool docstring in `tools/copepod_sources.py`
- focused tests in `tests/test_ecotaxa_browser_navigation.py` and
  `tests/test_copepod_sources.py`
- the matching inventory entry in `TOOLS.md`

The EcoTaxa SQLite cache, its 50,000-object project scan, `profile_id`, cast
inference, source routing, and export behavior are explicitly out of scope.

## API contract

The direct summary composes four official EcoTaxa resources at sample grain:

1. `GET /sample/{sample_id}` supplies the sample identity, project, position,
   and sample free columns.
2. `GET /acquisitions/search?project_id=...` supplies acquisitions linked to
   the sample, including instrument and acquisition free columns.
3. `GET /sample_set/taxo_stats?sample_ids=...` supplies authoritative
   `nb_validated`, `nb_predicted`, `nb_dubious`, and `nb_unclassified` counts.
4. `POST /object_set/{project_id}/query` supplies only
   `obj.objdate,obj.objtime,obj.depth_min,obj.depth_max,obj.acquisid`, filtered
   by the exact sample ID and ordered by the unique `obj.objid` field.

The authoritative object total is the sum of the four sample-stat counters. The
object-query `total_ids` value is retained only as a consistency check and must
not silently replace the sample-stat total.

## Bounded metadata scan

The existing 50,000-object limit remains on the direct object metadata scan.
The returned summary distinguishes exact counts from potentially partial
metadata:

- `total_objects`: authoritative sample-stat total.
- `nb_validated`, `nb_predicted`, `nb_dubious`, `nb_unclassified`: exact
  sample-stat counters.
- `objects_scanned`: number of object metadata rows actually processed.
- `query_total_objects`: `total_ids` reported by the object query.
- `metadata_complete`: true only when all authoritative objects were scanned
  and the query total agrees with the sample-stat total.
- `metadata_coverage_pct`: scanned rows divided by the authoritative total,
  capped at 100%; 100% for an empty sample.
- `count_discrepancy`: true when the object-query total and sample-stat total
  differ.

When `metadata_complete` is false, date/time and depth extrema remain available
as exploratory values over the scanned rows, but the user-facing output must
label them as partial. They must never be described as the definitive deployment
envelope.

## Temporal semantics

The object query adds `obj.objtime`; no time value is inferred.

- `date_min` and `date_max` remain for backward compatibility and use every
  non-null `objdate`.
- `datetime_min` and `datetime_max` are computed only when every scanned row
  carrying a date also carries a time.
- `temporal_precision` is `datetime` when the complete timestamp envelope is
  available, `date` when only the date envelope is reliable, and `none` when no
  object date is available.
- `missing_date_count` and `missing_time_count` make the precision decision
  observable.

ISO date and time strings can be ordered lexicographically after normalization
to `YYYY-MM-DDTHH:MM:SS`. Invalid values are ignored for the datetime envelope,
counted as missing for precision purposes, and never repaired or invented.

## Depth semantics

The vertical envelope remains:

- minimum of all non-null `obj.depth_min` values scanned;
- maximum of all non-null `obj.depth_max` values scanned.

The response also reports missing-value counts for both depth fields. If the
metadata scan is partial, the rendered envelope is explicitly marked partial.

## User-facing response

The deployment summary keeps the existing sample, position, acquisition, and
free-field sections. It adds:

- the authoritative V/P/D/U counts and total;
- a date-time envelope when EcoTaxa provides complete times;
- the metadata coverage (`objects_scanned / total_objects` and percentage);
- a visible warning when coverage is partial or when API totals disagree.

No internal tool name is exposed. Counts are identified as coming from EcoTaxa
sample statistics; extrema are identified as computed from scanned object
metadata.

## Error handling

- Failure to retrieve the sample remains fatal because the project and exact
  sample scope cannot be established.
- Failure of sample statistics remains fatal; the implementation must not fall
  back to a less authoritative object count.
- Existing API exceptions continue through the current structured EcoTaxa error
  boundary.
- A disagreement between two successful endpoints is data quality information,
  not an exception: return both totals, set `count_discrepancy=true`, and mark
  metadata incomplete.
- Empty samples return exact zero counters, 100% metadata coverage, no temporal
  or depth envelope, and no invented values.

## Testing strategy

Implementation follows the repository TDD rule. Tests are written before code
for these cases:

1. The object query requests `obj.objtime` and remains filtered to the exact
   sample with stable pagination.
2. V/P/D/U and total come from sample statistics, including when
   `object_query.total_ids` disagrees.
3. Complete date and time values produce exact ISO `datetime_min/max` and
   `temporal_precision=datetime`.
4. A missing or invalid time preserves the date envelope, returns no exact
   datetime envelope, and sets `temporal_precision=date`.
5. A sample above the 50,000-row limit keeps exact counts while returning
   partial metadata coverage and a visible user warning.
6. Depth extrema and missing-value counters are computed from scanned rows.
7. An empty sample produces zero counts and no fabricated metadata.
8. The existing deployment summary tests remain green after extending their
   fixtures with sample statistics and object time.

Focused verification runs the two deployment test groups first, followed by the
complete EcoTaxa browser/source test modules. A final live read-only check uses
an accessible sample without exporting objects or images.

## Acceptance criteria

- The cache and cast behavior are unchanged.
- The direct summary uses sample statistics for all object counts.
- EcoTaxa object time is preserved when present.
- The agent cannot present a capped scan as a complete deployment envelope.
- Counts and metadata coverage have explicit provenance and consistency status.
- No credential, scientific interpretation, source-policy duplication, or
  expensive export is introduced.
