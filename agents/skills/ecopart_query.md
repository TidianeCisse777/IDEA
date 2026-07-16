# Skill: ecopart_query

## Activation precondition

Apply this skill only when the current user request explicitly names EcoPart
and the active session does not forbid EcoPart. Do not load or apply this skill
for generic requests about samples, projects, stations, positions, zones, maps,
counts, environmental variables, or analyses. A loaded EcoTaxa-derived table
remains primary; EcoPart is only the requested enrichment source.

## Current explicit enrichment request

When the user asks to enrich the active sample, file, or table with EcoPart,
call `enrich_ecotaxa_with_ecopart_remote` directly. This is the only canonical
remote enrichment path. Do not detour through source discovery, a fresh EcoTaxa
export, a standalone EcoPart download, or a hand-written pandas join.

The canonical tool resolves the grounded EcoTaxa project metadata when
available, finds the related EcoPart project, downloads it, and joins on the
tool’s validated sample/profile and depth-bin logic. Let the tool diagnose
missing grounded metadata or incompatible schemas.

## Mandatory dry-run and confirmation

EcoPart enrichment is always a heavy operation:

1. First call the canonical enrichment with `confirmed=False` and otherwise
   minimal arguments. It returns the resolved project and join plan without a
   download.
2. Report that plan and wait for explicit confirmation.
3. After “oui”, “go”, “lance”, “confirme”, or “ok”, call the same canonical enrichment
   with `confirmed=True` and the same grounded project parameters.

Never skip the dry-run, and never interpret the user’s initial enrichment
request as confirmation of the download.

## Result contract

- Treat only a successful confirmed tool result as enrichment success.
- Always report match coverage: total EcoTaxa rows, rows matched on an EcoPart
  bin, unmatched/partial rows, and the depth range actually covered.
- If coverage is zero or weak, report that the enrichment did not really take;
  never present NaN-filled output or derived metrics as success.
- Include the exact persisted variable and download link returned by the tool.
- Do not substitute another campaign/source after an empty, blocked, or failed
  result.
- Do not add scientific or biological interpretation.
