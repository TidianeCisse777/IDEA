---
name: bio_oracle_query
version: 1.0.0
triggers:
  - Explicit Bio-ORACLE query or loaded-table enrichment intent
forbidden_when:
  - Bio-ORACLE is not authorized by the source decision
requires:
  - "source:bio_oracle"
next_tool: enrich_with_bio_oracle
max_tokens: 850
---

# Skill: bio_oracle_query

## Activation precondition

Apply this skill only when the Source Selection Gateway authorizes Bio-ORACLE,
either by an explicit current request or an inherited active-source follow-up,
and the active session does not forbid Bio-ORACLE. Do not load or apply this
skill for generic requests about samples, projects, stations, positions, zones,
temperature, environment, maps, scenarios, or analyses. A loaded table remains
the primary source; Bio-ORACLE is only the requested enrichment source.

## Current explicit enrichment request

When the user asks to enrich a loaded sample, file, table, or its stations with
Bio-ORACLE, call `enrich_with_bio_oracle` directly on the exact active variable.
This is the only canonical loaded-table enrichment path.

- Before calling the tool, propose the copépode variable preset and the complete
  catalog, then wait for the user's explicit selections. The user must choose
  one or more variables, one or more scenarios, a vertical layer, and a
  statistic. Never apply a preset silently.
- The canonical tool enriches every source row by latitude/longitude and keeps
  the DataFrame grain. It does not aggregate rows by zone.
- Do not preflight with discovery, zone, point-preview, or raw-query tools.
- Do not construct or transcribe station rows in tool arguments.
- Do not reuse an earlier assistant refusal or schema assessment.
- Do not demand station IDs: the canonical enrichment auto-detects supported
  latitude/longitude aliases and preserves every source row.
- Pass `source_variable` only when several live datasets make the target
  ambiguous.

For an explicitly named zone, pass `zone_name` to the same canonical tool. For
“par station” or “les mêmes stations”, enrich the source rows first and use the
persisted enriched table for any requested neutral aggregation.

## Variables and scenarios

The proposed copépode variables include `temperature`, `salinity`, `oxygen`,
`nitrate`, `phosphate`, `silicate`, `chlorophyll`, `primary_productivity`,
`mixed_layer_depth`, `par`, and `diffuse_attenuation`. The full catalog also
offers current, ice, atmospheric, and other environmental layers. Scenarios
include `baseline`, `SSP1-1.9`, `SSP1-2.6`, `SSP2-4.5`, `SSP3-7.0`, `SSP4-6.0`,
and `SSP5-8.5`; treat common numeric/RCP aliases as their standard SSP
equivalents (`4.5` → `SSP2-4.5`).

- The vertical layer is mandatory: choose `surface`, `benthic_min`,
  `benthic_mean`, or `benthic_max`.
- The statistic is mandatory and must be supported by the selected variables:
  `mean`, `min`, `max`, `lt_min`, `lt_max`, or `range`.

- Pass only variables/scenarios requested by the user; otherwise use canonical
  defaults.
- If the user specifies a future year or horizon, pass `target_year` (for
  example `target_year=2050`).
- Baseline is historical. SSP values use the nearest available decadal slice.
- Never reuse an older SSP value unless its persisted time metadata matches the
  current target year.

## Confirmation

When the tool estimates more than its configured limit of unique Bio-ORACLE
queries (1,000 by default, after coordinate binning × variables × scenarios),
it returns a confirmation plan when `confirmed=False`. Report that plan and
wait. After explicit confirmation, call the same canonical enrichment with
`confirmed=True` and the same parameters. Requests below that limit run
directly.

## Result contract

- Treat only a successful tool result as enrichment success.
- Report total rows, matched/no-value counts, exact persisted variable,
  variables, scenarios, target year when applicable, download link, and
  Bio-ORACLE provenance.
- Preserve tool-reported coverage and limits; do not fabricate placeholder
  columns or substitute another source.
- Do not add scientific or biological interpretation.
