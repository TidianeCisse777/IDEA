# Unified enrichment routing design

Date: 2026-07-16
Scope: Step 6 follow-up for EcoPart, Amundsen CTD, Bio-ORACLE, and OGSL

## Problem

An explicit request such as “enrichis le sample avec Bio-ORACLE” or “enrichis
avec EcoPart” must select the named source even when the conversation previously
used other external sources. The executable Step 6 policy already maps each
source to one canonical enrichment tool, but its regression coverage is centred
on Amundsen and the model-facing instructions still contain legacy routes:

- the Amundsen skill prefers a station/cast enrichment tool hidden by Step 6;
- the Bio-ORACLE skill prefers an older coupling tool hidden by Step 6;
- the system prompt’s explicit-enrichment rule omits EcoPart;
- OGSL has no dedicated runtime skill documenting its canonical enrichment path.

These contradictions can make the model refuse, navigate to an unrelated source,
or request identifiers that the canonical enrichment tool does not need.

## Considered approaches

### A. One shared contract, projected into policy, prompt, and skills — selected

Keep the existing generic source decision and canonical exposure map. Align the
system prompt and every source skill with that executable contract, then
parameterize the stale-affinity regression tests across all four sources.

Advantages: one routing rule, no source-specific dispatcher, no second model,
and failures remain visible through the canonical tool’s own validation.

### B. Add a deterministic branch for every source

Create separate routing code paths for EcoPart, Amundsen, Bio-ORACLE, and OGSL.

Rejected because it duplicates the same intent rule and makes future source
additions require changes in several branches.

### C. Change only the prompt

Tell the model more strongly which tool to use but leave tests and skills as-is.

Rejected because the contradictory skills would remain and the executable
allowlist would not have complete regression coverage.

## Unified contract

When the current user explicitly asks to enrich the active table with a named
source:

1. The named source replaces stale external affinities; the active file/table
   remains primary.
2. Step 6 exposes core, geography, file analysis, and only the named source’s
   canonical enrichment tool.
3. The model calls that canonical tool directly. It does not preflight with a
   discovery/query tool and does not reuse an earlier assistant refusal.
4. Column and identifier validation belongs to the canonical tool. The model
   must not demand station/cast or other direct join identifiers when the tool
   supports automatic schema resolution.
5. A blocked/empty/error tool result is reported as such; no other external
   source is substituted.

Canonical mapping:

| Source | Canonical enrichment path | Confirmation |
|---|---|---|
| EcoPart | `enrich_ecotaxa_with_ecopart_remote` | Always dry-run first; execute only after explicit confirmation |
| Amundsen CTD | `enrich_with_amundsen_ctd` | Direct; tool validates lat/lon/time/depth |
| Bio-ORACLE | `enrich_with_bio_oracle` | Direct for light defaults; confirmation for more than 10 rows with multiple variables × scenarios |
| OGSL | `enrich_with_ogsl` | Direct; tool validates lat/lon/time/depth |

## Model-facing changes

### System prompt

Replace the Amundsen/OGSL/Bio-only wording with a unified explicit-enrichment
rule covering all four sources. State the canonical confirmation exception for
EcoPart and the size/scenario exception for Bio-ORACLE. Keep the rule that prior
assistant conclusions never override the current request or active dataset
capsule.

### Source skills

- `amundsen_ctd_query.md`: make `enrich_with_amundsen_ctd` the only generic
  loaded-table enrichment route and remove the hidden station/cast route from
  model instructions.
- `bio_oracle_query.md`: make `enrich_with_bio_oracle` the generic loaded-table
  route; retain zone and single-point routes only for explicitly different
  requests.
- `ecopart_query.md`: make the dry-run/confirmation/replay sequence explicit and
  forbid a detour through EcoTaxa discovery when the active table is grounded.
- Add `ogsl_query.md` with the explicit-source precondition, canonical direct
  route, schema auto-detection, confirmation/limit behaviour, and neutral result
  reporting.

## Executable policy and tests

No new dispatcher is introduced. The existing `_ENRICHMENT_GROUP_BY_SOURCE`
mapping remains the source of canonical exposure.

Regression tests will be parameterized across all four sources and prove that:

- stale EcoTaxa/EcoPart/other affinities are removed;
- `authorized_sources` becomes `file + explicitly named source`;
- exactly one canonical enrichment tool is exposed;
- unrelated EcoTaxa, SQL, and other enrichment groups remain hidden;
- the policy stays under the 15-tool limit without fallback;
- EcoPart confirmation and Bio-ORACLE conditional confirmation remain intact.

Two real curl scenarios complete verification:

1. Bio-ORACLE: an explicit request reaches the canonical enrichment tool on the
   active sample and returns either a grounded enrichment result or its genuine
   tool-level blocker.
2. EcoPart: the first request returns the dry-run confirmation plan; after
   confirmation, the same canonical tool performs the download/join and reports
   match coverage.

## Non-goals

- No regex-based geography routing.
- No second intent model.
- No reintroduction of legacy enrichment tools into the Step 6 allowlist.
- No silent confirmation bypass for expensive operations.
- No scientific interpretation of enrichment results.
