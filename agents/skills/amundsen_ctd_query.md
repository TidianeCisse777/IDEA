# Skill: amundsen_ctd_query

## Activation precondition

Apply this skill only when the current user request explicitly names Amundsen CTD
and the active session does not forbid Amundsen CTD. Do not load or apply this
skill for generic requests about samples, projects, stations, positions, zones,
temperature, salinity, environment, maps, or analyses. A loaded table remains
the primary source; Amundsen is only the requested enrichment source.

## Current explicit enrichment request

When the user says “enrichis avec Amundsen”, “ajoute le CTD Amundsen”, “joins
mon sample avec Amundsen”, or equivalent, call `enrich_with_amundsen_ctd`
directly on the exact active variable. This is the only canonical loaded-table
enrichment path.

- Do not run discovery, preview, or raw CTD retrieval first.
- Do not require station/cast identifiers.
- Do not reuse an earlier assistant refusal or schema assessment.
- Pass `source_variable` only when several datasets are live and the active
  capsule does not already identify the intended table.

The canonical enrichment auto-detects supported latitude, longitude, time, and
depth aliases, including EcoTaxa/NeoLabs forms. It deduplicates repeated source
points, batches ERDDAP requests, matches by spatial/temporal/depth proximity,
and preserves source rows. Let the tool return its own blocked diagnostic when
required metadata is absent.

## Optional user constraints

Pass only constraints the user actually supplied:

- requested CTD variables via `variables`;
- `zone_name` for an explicitly named geographic subset;
- `date_range` for an explicit temporal restriction;
- explicit column overrides or tolerance changes.

Otherwise keep canonical defaults.

## Result contract

- Treat only a successful tool result as enrichment success.
- Report total rows, matched rows, status counts, distance/time quality metrics,
  exact persisted variable, download link, and Amundsen provenance.
- Preserve `no_match`, `matched_no_value`, and `outside_amundsen_ctd_range` as
  visible limits.
- Do not substitute OGSL, Bio-ORACLE, EcoPart, or any other source after an
  empty, blocked, or failed result.
- Do not add scientific or biological interpretation.
