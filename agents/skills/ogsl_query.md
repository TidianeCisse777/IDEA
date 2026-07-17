---
name: ogsl_query
version: 1.0.0
triggers:
  - Explicit OGSL query or loaded-table enrichment intent
forbidden_when:
  - OGSL is not authorized by the source decision
requires:
  - "source:ogsl"
next_tool: null
max_tokens: 600
---

# Skill: ogsl_query

## Activation precondition

Apply this skill only when the Source Selection Gateway authorizes OGSL, either
by an explicit current request or an inherited active-source follow-up, and the
active session does not forbid OGSL. Do not load or apply this skill for
generic requests about samples, projects, stations, positions, zones,
temperature, salinity, environment, maps, or analyses. A loaded table remains
the primary source; OGSL is only the requested enrichment source.

## Current explicit enrichment request

When the user says “enrichis avec OGSL”, “ajoute le CTD OGSL”, “joins ce sample
avec OGSL”, or equivalent, call `enrich_with_ogsl` directly on the exact active
variable. This is the only canonical loaded-table enrichment path.

- Do not run discovery or raw CTD retrieval first.
- Do not require station/cast identifiers.
- Do not reuse an earlier assistant refusal or schema assessment.
- Pass `source_variable` only when several live datasets make the target
  ambiguous.

The canonical enrichment auto-detects supported latitude, longitude, time, and
depth aliases, batches OGSL ERDDAP requests, matches by spatial/temporal/depth
proximity, and preserves every source row. Let the tool return its own blocked
diagnostic when required metadata is absent.

## Optional user constraints

Pass only constraints the user explicitly supplied: `variables`, `zone_name`,
`date_range`, column overrides, or tolerance changes. Otherwise keep canonical
defaults.

## Result contract

- Treat only a successful tool result as enrichment success.
- Report total rows, matched rows, status counts, distance/time quality metrics,
  exact persisted variable, download link, and OGSL provenance.
- Preserve no-match/no-value statuses as visible limits.
- Do not substitute Amundsen, Bio-ORACLE, EcoPart, or another source after an
  empty, blocked, or failed result.
- Do not add scientific or biological interpretation.
