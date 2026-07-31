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

Apply only when the Source Selection Gateway authorizes Bio-ORACLE for the
current request or active-source follow-up. Do not apply it to generic sample,
station, zone, environment, map, scenario, or analysis requests. A loaded table
remains primary; Bio-ORACLE is the requested enrichment source.

## Current explicit enrichment request

When the user asks to enrich a loaded sample, file, table, or its stations with
Bio-ORACLE, call `enrich_with_bio_oracle` directly on the exact active variable.
This is the only canonical loaded-table enrichment path.

- Before calling the tool, propose the copépode variable preset and the complete
  catalog, then wait for the user's explicit selections. The user must choose
  one or more variables, one or more scenarios, a vertical layer, and a
  statistic. Never apply a preset silently.
- The canonical tool enriches every source row by latitude/longitude, preserves every source row, and never aggregates by zone.
- For « par station » or « les mêmes stations », enrich the source rows first.

## Variables and scenarios

The proposed copepod variables are `temperature`, `salinity`, `oxygen`,
`nitrate`, `phosphate`, `silicate`, `chlorophyll`, `primary_productivity`,
`mixed_layer_depth`, `par`, and `diffuse_attenuation`. The full catalog also
has current, ice, atmospheric, and other layers; each entry has a label, group,
unit, and factual description. Explain from that metadata: nutrients/oxygen/
iron are dissolved chemicals; chlorophyll/productivity are biological
indicators; currents are speed/direction; ice is thickness/coverage; PAR and
attenuation are underwater light. Proposed scenarios are `baseline`,
`SSP1-1.9`, `SSP2-4.5`, `SSP3-7.0`, `SSP4-6.0`, `SSP5-8.5`; baseline is historical
and SSP labels range from very low to very high emissions. Alias
`SSP1-2.6` and numeric/RCP aliases (`4.5` → `SSP2-4.5`) remain accepted.
Never turn a scenario label into an observed value or biological conclusion.
If a scenario has no value on some rows, report its missing/no_value coverage
alongside the comparison; never silently replace or invent it.

- The vertical layer is mandatory: choose `surface`, `benthic_min`,
  `benthic_mean`, or `benthic_max`.
- The statistic is mandatory and must be supported by the selected variables:
  `mean`, `min`, `max`, `lt_min`, `lt_max`, or `range`.

- Pass only variables/scenarios explicitly selected by the user; if they are
  absent, stop and present the catalog instead of invoking the tool.
- If the user specifies a future year or horizon, pass `target_year` (for
  example `target_year=2050`).
- Never reuse an older SSP value when its persisted time metadata misses target.

## Confirmation

When unique queries exceed 1,000 (after coordinate binning × variables ×
scenarios), `confirmed=False` returns a plan. Report it and wait; after explicit
confirmation, retry the same canonical enrichment with `confirmed=True`.

## Result contract

- Treat only a successful tool result as enrichment success.
- Report rows, matched/no-value counts, exact persisted variable, selections,
  target year when applicable, download link, and provenance.
- Preserve tool-reported coverage and limits; do not fabricate placeholder
  columns or substitute another source.
- Do not add scientific or biological interpretation.
