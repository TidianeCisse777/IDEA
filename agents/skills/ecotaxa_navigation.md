---
name: ecotaxa_navigation
version: 3.0.0
triggers:
  - Explicit EcoTaxa discovery, sample-level exploration, read-only inspection, or export planning intent
forbidden_when:
  - EcoTaxa is not authorized by the source decision
requires:
  - "source:ecotaxa"
next_tool: null
max_tokens: 4500
size_exemption: ecotaxa_navigation owns the complete cache SQL vocabulary including table schema, join patterns, and SQL prohibitions shared by all EcoTaxa cache queries; its full body is delivered with a manifest-governed cap instead of the generic tool truncation.
---

# EcoTaxa navigation

## Scope

Use this skill only when the Source Selection Gateway authorizes EcoTaxa.
Stay at sample level unless the user explicitly needs individual objects.

- Sample-level questions use the local SQLite cache.
- One incomplete sample may use the targeted live deployment fallback.
- Taxon names/counts and project export schemas use the dedicated read-only API tools.
- Individual objects require an export plan and explicit confirmation.

## Visible tool map

| Need | Tool |
|---|---|
| Discover the actual cache | `list_ecotaxa_cache_tables` |
| Inspect one cache table | `describe_ecotaxa_cache_table` |
| Filter, join, count, group, rank, or resolve samples | `query_ecotaxa_cache` |
| Complete one partially cached sample | `summarize_ecotaxa_sample_deployment` |
| Resolve a taxon name | `search_ecotaxa_taxa` |
| Count V/P/D/U for project × taxon | `count_ecotaxa_taxa` |
| Inspect fields available for an API export | `inspect_ecotaxa_project_schema` |
| Inspect one API/export column | `inspect_ecotaxa_column` |
| Compare export schemas across projects | `compare_ecotaxa_projects` |
| Export one project or several samples from one project | `query_ecotaxa` |
| Export one sample without a known project | `query_ecotaxa_sample` |
| Export a saved or multi-project sample selection | `export_ecotaxa_samples` |

Do not route navigation through project/sample convenience wrappers or
paginated object browsing. They remain registered only for compatibility.

## Cache-first route

`query_ecotaxa_cache` accepts read-only `SELECT` and `WITH`/CTE queries,
including joins, subqueries and aggregations. Add `LIMIT` only when the user
asks for an overview, top, or page.

When a query returns `sample_id`, pass a short descriptive `selection_name`
(for example `baffin_2024` or `project_17498_deep`). The complete result is
persisted under a stable unique `df_ecotaxa_selection_*` variable. Every saved
selection remains available in `WORKING TABLES` for `run_pandas` and
`run_graph` until the conversation is cleared. `df_ecotaxa_cache_query` and
`latest` always point to the newest result; they do not replace older named
selections. Reuse the exact saved variable whose description matches the
follow-up instead of rerunning its SQL.

**Schema-first rule**: if you are unsure whether a column or table exists,
call `list_ecotaxa_cache_tables` (full map) or `describe_ecotaxa_cache_table`
(one table) before writing SQL. Never refuse a query or invent a workaround
(e.g. `json_extract`) when a direct column exists — check first.

Use the table map once when the schema is unknown, before a join, or after an
unknown-column error. Otherwise query directly. Use the single-table
description only when column types or indexes matter.

### Core sample grain

One row in `samples_cache` is one EcoTaxa sample. Important columns:

| Field | Meaning |
|---|---|
| `sample_id`, `project_id` | Stable identifiers |
| `original_id`, `station_id`, `profile_id` | Deployment label, station, and cast/profile |
| `lat_avg`, `lon_avg`, `iho_zone` | Cached location and polygon-derived zone |
| `instrument` | Sampling instrument |
| `object_count` | Authoritative total from sample statistics |
| `nb_validated`, `nb_predicted`, `nb_dubious`, `nb_unclassified` | Authoritative sample-level V/P/D/U counts |
| `used_taxa` | JSON list of taxon IDs observed in the sample |
| `date_min`, `date_max`, `datetime_min`, `datetime_max`, `time_min`, `time_max` | Object-derived temporal envelopes |
| `depth_min`, `depth_max` | Object-derived depth envelope |
| `metadata_complete`, `metadata_coverage_pct`, `depth_complete` | Envelope completeness guards |
| `free_fields_json` | Cached sample free fields |

`profile_id` is the cast. `station_id` is a location and must never be renamed
or counted as a cast. Count samples with `COUNT(DISTINCT sample_id)` and casts
with `COUNT(DISTINCT profile_id)`.

Never derive V/P/D/U from `object_count`. Never sum a sample-level count after
joining samples to multiple object rows; pre-aggregate objects by `sample_id`
or count distinct samples.

### Resolving labels and samples

Resolve a numeric ID, label, station, profile, deployment, or free-field value
with one cache query. Preserve every match; if several rows match, present the
candidate `sample_id` and `project_id` values and ask the user to choose.

```sql
SELECT sample_id, project_id, original_id, station_id, profile_id,
       instrument, iho_zone
FROM samples_cache
WHERE sample_id = :numeric_id
   OR original_id LIKE :pattern
   OR station_id LIKE :pattern
   OR profile_id LIKE :pattern
   OR free_fields_json LIKE :pattern
```

Do not infer a project from a label prefix.

### Geography, dates and depth

Use the cached `iho_zone`; never invent a bounding box. Prefer `LIKE` for named
zones and inspect distinct matches when a word can identify multiple zones.

```sql
SELECT sample_id, project_id, original_id, lat_avg, lon_avg, iho_zone,
       date_min, date_max, depth_min, depth_max, instrument
FROM samples_cache
WHERE iho_zone LIKE '%Baffin%'
  AND metadata_complete = 1
  AND missing_date_count = 0
  AND date_min <= '2024-12-31'
  AND date_max >= '2024-01-01'
ORDER BY date_min
```

Exact time/depth claims require their guards:

- datetime: `metadata_complete = 1 AND temporal_precision = 'datetime'`
- time: `metadata_complete = 1 AND missing_time_count = 0`
- depth: `depth_complete = 1`

For an interval `[a,b]`, use envelope overlap: `min <= b AND max >= a`.
Also count rows excluded by completeness guards in the same scope and report
them as unknown, not as non-matches.

### Resolving project metadata

`projects_cache` is the single project reference table. One row per synced
project. Columns: `project_id`, `title`, `instrument`, `description`, `status`,
`contact_name`, `objcount`, `pctvalidated`, `pctclassified`, `last_synced`.

JOIN it whenever the user asks for project names, description, validation rate,
or object counts in a table or legend.

```sql
SELECT sc.project_id,
       p.title,
       p.instrument,
       p.status,
       p.contact_name,
       p.objcount,
       p.pctvalidated,
       COUNT(sc.sample_id) AS n_samples
FROM samples_cache AS sc
LEFT JOIN projects_cache AS p USING (project_id)
GROUP BY sc.project_id
ORDER BY n_samples DESC;
```

Do **not** tell the user that project metadata is unavailable — `title` is
always present; `description`, `status`, `contact_name` may be NULL for real
projects not yet resynced, but are never missing from fat-cache campaigns.

When displaying `description`, always reproduce the full text verbatim — never
summarize, paraphrase, or replace it with a placeholder like "description
longue" or "description disponible". If the text is long, display it in full.

### Counts and groupings

```sql
-- Project summary
SELECT project_id, COUNT(*) AS n_samples,
       SUM(object_count) AS n_objects,
       SUM(nb_validated) AS n_validated,
       SUM(nb_predicted) AS n_predicted,
       SUM(nb_dubious) AS n_dubious,
       SUM(nb_unclassified) AS n_unclassified
FROM samples_cache
GROUP BY project_id;

-- Zone ranking
SELECT iho_zone,
       COUNT(DISTINCT profile_id) AS n_casts,
       COUNT(DISTINCT sample_id) AS n_samples
FROM samples_cache
GROUP BY iho_zone
ORDER BY n_samples DESC;
```

For a map, return `sample_id`, `lat_avg`, `lon_avg`, `iho_zone`, and the metric
to encode, then use `run_graph` on the persisted result. Aggregate coincident
coordinates so overlapping samples remain countable.

### SQL prohibitions

**Never filter out samples without a zone in global counts or discovery queries.**
`iho_zone` is NULL for samples uploaded without GPS coordinates — they are real
samples and must appear in any global count, summary, or campaign listing.

```sql
-- FORBIDDEN: silently drops all samples where iho_zone IS NULL
WHERE iho_zone != 'Hors zone référencée'
WHERE iho_zone IS NOT NULL
WHERE iho_zone != ''

-- CORRECT for global count: no iho_zone filter
SELECT COUNT(*) AS n_samples, COUNT(DISTINCT project_id) AS n_projects
FROM samples_cache;

-- CORRECT for zone breakdown: include NULL as explicit group
SELECT COALESCE(iho_zone, 'Sans coordonnées GPS') AS zone,
       COUNT(*) AS n_samples
FROM samples_cache
GROUP BY iho_zone
ORDER BY n_samples DESC;
```

**For global discovery questions** ("qu'est-ce qu'on a ?", "liste les campagnes"),
call `list_ecotaxa_campaigns` — do not write a SQL aggregation from scratch.
`list_ecotaxa_campaigns` counts all samples including those without coordinates
and returns a structured campaign table.

**Never run the same SQL query twice in a row.** If a first result looks
incomplete, check the result before retrying — the cache is read-only and
deterministic.

## Taxonomy

The cache stores taxon IDs, not a complete name dictionary.

1. Resolve an ambiguous or named taxon with `search_ecotaxa_taxa`.
2. Find samples containing the resolved ID through `used_taxa`:

```sql
SELECT s.sample_id, s.project_id, s.original_id, s.iho_zone
FROM samples_cache AS s
WHERE EXISTS (
  SELECT 1 FROM json_each(s.used_taxa)
  WHERE CAST(value AS INTEGER) = :taxon_id
);
```

3. Use `count_ecotaxa_taxa` only for exact project × taxon V/P/D/U counts.
It is not a per-sample taxon count.

Exact taxon counts per sample/cast, morphology, scores, or individual object
statuses require the object cache when present, otherwise an export.

## Live fallback for one sample

Use `summarize_ecotaxa_sample_deployment` only when:

- the sample has already been resolved from the cache;
- the question concerns that one sample's deployment metadata; and
- its cache row has incomplete temporal/depth coverage.

Do not repeat this live call across a batch. For complete rows, answer directly
from the cache.

An empty cache result is not proof that EcoTaxa has no data. Check `sync_runs`
and cache coverage, state that the requested record is not indexed, and never
turn an absent cache row into a scientific absence.

## Schema questions

- Cached table/column question: use the cache map or table description.
- Fields available in a project export: `inspect_ecotaxa_project_schema`.
- Distribution of one export/API column: `inspect_ecotaxa_column`.
- Compatibility of multiple project exports: `compare_ecotaxa_projects`.

Schema inspection is read-only and does not require an object export.

## Object export

Choose the narrowest export:

| Scope | Tool |
|---|---|
| One sample | `query_ecotaxa_sample` |
| One project or selected samples in one project | `query_ecotaxa` |
| Saved selection or samples spanning projects | `export_ecotaxa_samples` |

Every object export follows two turns:

1. Resolve the scope from the cache and present project/sample scope, status,
   taxon and depth filters. For saved/multi-project selections, call
   `export_ecotaxa_samples(..., confirmed=False)` to obtain the dry-run.
2. Wait for a new explicit confirmation referring to that plan, then execute
   exactly that scope (`confirmed=True` for the saved/multi-project route).

If the scope changes, prepare a new plan. Never export merely for a sample-level
count, summary, preview, or graph.

When a cache query returns `sample_id`, the selection is saved automatically as
`selection_name="latest"`. Reuse it for export instead of copying IDs from a
displayed preview.

After a successful export, use the returned persistent dataset with
`run_pandas` or `run_graph`. A multi-project export contains
`export_project_id`; keep that provenance. On `EXPORT_FAILED`, report the
failure and stop—do not substitute a partial page or fabricate rows.

## Quick routing

| User intent | Route |
|---|---|
| List/search projects, campaigns, samples, labels | cache SQL |
| Sample/project counts or V/P/D/U totals | cache SQL |
| Zone, date, hour, depth, station, cast, instrument | cache SQL |
| Resolve one label or sample ID | cache SQL |
| Complete one incomplete sample | targeted live deployment fallback |
| Named taxon | taxon resolution, then cache SQL |
| Exact project × taxon V/P/D/U | taxon count API |
| Export field/schema question | schema inspection |
| Individual objects or object-level analysis | confirmed export |

After any cache query, use `run_pandas` for derived tables and joins and
`run_graph` for requested visuals. Always use the exact persistent variable
names shown in WORKING TABLES; never expose internal tool or variable names in
the user-facing answer.
