# Skill: bio_oracle_query

## Activation precondition

Apply this skill only when the current user request explicitly names Bio-ORACLE
and the active session does not forbid Bio-ORACLE. Do not load or apply this
skill for generic requests about samples, projects, stations, positions, zones,
temperature, environment, maps, scenarios, or analyses. A loaded table remains
the primary source; Bio-ORACLE is only the requested enrichment source.

## Current explicit enrichment request

When the user asks to enrich a loaded sample, file, table, or its stations with
Bio-ORACLE, call `enrich_with_bio_oracle` directly on the exact active variable.
This is the only canonical loaded-table enrichment path.

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

Friendly variables include `temperature`, `salinity`, `oxygen`, `chlorophyll`,
`nitrate`, `ph`, and `iron`. Scenarios include `baseline`, `SSP1-2.6`,
`SSP2-4.5`, and `SSP5-8.5`.

- Pass only variables/scenarios requested by the user; otherwise use canonical
  defaults.
- If the user specifies a future year or horizon, pass `target_year` (for
  example `target_year=2050`).
- Baseline is historical. SSP values use the nearest available decadal slice.
- Never reuse an older SSP value unless its persisted time metadata matches the
  current target year.

## Confirmation

For more than 10 source rows with multiple variables × scenarios, the canonical
tool returns a confirmation plan when `confirmed=False`. Report that plan and
wait. After explicit confirmation, call the same canonical enrichment with
`confirmed=True` and the same parameters. Light/default enrichment runs
directly.

## Result contract

- Treat only a successful tool result as enrichment success.
- Report total rows, matched/no-value counts, exact persisted variable,
  variables, scenarios, target year when applicable, download link, and
  Bio-ORACLE provenance.
- Preserve tool-reported coverage and limits; do not fabricate placeholder
  columns or substitute another source.
- Do not add scientific or biological interpretation.
