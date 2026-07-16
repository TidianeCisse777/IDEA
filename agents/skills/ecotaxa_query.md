---
name: ecotaxa_query
version: 1.0.0
triggers:
  - Successful explicitly authorized EcoTaxa extraction requiring object-level interpretation
forbidden_when:
  - EcoTaxa extraction failed or EcoTaxa is not authorized
requires:
  - "source:ecotaxa"
  - "success:query_ecotaxa"
next_tool: run_pandas
max_tokens: 1700
---

# Skill: ecotaxa_query

## Activation precondition

Apply this skill only when the current user request explicitly names EcoTaxa
and the active session does not forbid EcoTaxa, or immediately after a
successful EcoTaxa extraction that was explicitly authorized in the current
source scope. Do not load or apply this skill for generic requests about
samples, projects, stations, positions, zones, maps, counts, or analyses. A
loaded file remains the default source unless the user explicitly requests
EcoTaxa.

You just called `query_ecotaxa` and EcoTaxa data is now loaded in the session.
This skill provides the rules for interpreting the result and guiding the user.

---

## Discovering accessible projects

The project list depends on the configured EcoTaxa account and can change.
Call `list_ecotaxa_projects` to get real-time `project_id` values and names,
then use the chosen identifier with `query_ecotaxa`.
Never present a hardcoded project list.

---

## Choosing the right tool

- To present a project, display its metadata, counts or a few objects: call `preview_ecotaxa_project`.
- To load, export, download or analyse the full data: call `query_ecotaxa`.
- Do not call `query_ecotaxa` for a simple preview request — this export can be slow and modifies the analysis session.
- Ne lance pas `query_ecotaxa` pour une simple demande d'aperçu.

---

## Key parameters of `query_ecotaxa`

| Parameter | Default | Notes |
|---|---|---|
| `project_id` | — | Required |
| `taxon` | `None` (all taxa) | e.g. `"Copepoda"`, `"Calanus"` — filtered server-side in EcoTaxa |
| `status` | `"V"` | `"V"` = validated only, `"P"` = predicted, `""` = all |
| `sample_ids` | `None` (all samples) | Restrict the export to specific samples of the project, filtered server-side |

**Recommendation:** always use `status="V"` for quantitative analyses — unvalidated predicted objects may contain classification errors.

---

## Filtering by sample(s)

When the user is interested in **specific samples** rather than the full project,
do NOT download the whole project and slice afterwards — push the filter to
EcoTaxa via `sample_ids`. This is much faster and avoids loading useless rows
in the session.

Routing rules:

- One `sample_id` and the user does **not** know the `project_id` →
  `query_ecotaxa_sample(sample_id=...)` (resolves the project automatically).
- One or several `sample_id`s **belonging to the same known project** →
  `query_ecotaxa(project_id=..., sample_ids=[id1, id2, ...])` in a single call.
- Samples spread across several projects → one `query_ecotaxa` call per project,
  each with its own `sample_ids=[...]`.

Anti-pattern to avoid: calling `query_ecotaxa(project_id=...)` (full project)
and then filtering with `run_pandas` on `sample_id`. Always pass `sample_ids`
to the tool when the target samples are known.

---

## After loading

1. **Check columns** with `run_pandas`:
   ```python
   result = df.columns.tolist()
   ```

2. **Identify the schema** — `fre_*` columns (UVP6/LOKI) or `object_*` (UVP5):
   ```python
   result = [c for c in df.columns if c.startswith("fre_") or c.startswith("object_")]
   ```

3. **If UVP columns detected** → load skill `uvp_ecotaxa` for m5/m6 calculation methods.

---

## Download link

The summary returned by `query_ecotaxa` contains a link `http://localhost:8000/downloads/<id>.tsv`.
**Include this link in your response** — the user can click it to download the full file.

---

## Combining EcoTaxa with EcoPart

EcoPart provides **CTD + UVP particle profiles** for the same Amundsen casts.
Pick the route by what is already in session — do **not** hand-roll the merge in
`run_pandas`, the dedicated tools do the binning and dtype handling for you:

- **EcoPart already loaded** (`df_ecopart` in session) → `join_ecotaxa_ecopart`.
- **EcoPart not loaded** → `enrich_ecotaxa_with_ecopart_remote` (default). It auto-resolves
  the EcoPart project from the session EcoTaxa (project id, coordinates, or profile/station
  labels) and joins — no EcoPart id needed.
- Only call `query_ecopart(project_id=...)` first when the user explicitly names a specific
  EcoPart project to load.

**Join key (handled by the tool):** the join is on `(sample_id, depth_bin)`, where the EcoTaxa
side resolves to the profile identifier (raw `sample_id`, `sample_id`/`obj_orig_id` stripped of
the `_NNN` object suffix, e.g. `ips_007_899` → `ips_007`, or the profile/station label) and
`depth_bin` is a 5 m bin computed from the object depth. Each EcoTaxa object keeps the EcoPart
columns of its own bin (`Depth [m]`, `Sampled volume [L]`, LPM, CTD), preserved not averaged.
See skill `uvp_ecopart` for m1-m3 metrics computable from EcoPart.

**Always report match coverage.** The join/enrich result states how many objects matched an
EcoPart bin. Relay that count, and if it is 0 or low, warn the user that the enrichment
did not really take — usually different campaigns (no shared profiles) or objects outside the
depth range the EcoPart cast actually covered (`NaN` columns). Never present a `NaN`-filled
enrichment, or metrics derived from it, as a success.

---

## Edge cases

- If the project has >100,000 objects, the export can take 1-2 minutes — warn the user.
- If `taxon` is specified but returns 0 rows: check the exact spelling of the taxon name (case-sensitive in EcoTaxa).
- Without valid credentials (`ECOTAXA_TOKEN` or `ECOTAXA_USERNAME`/`ECOTAXA_PASSWORD`), the tool returns an error — ask the user to check their `.env`.

## Runtime routing contract

- Only if `query_ecotaxa` succeeds, call `load_skill("ecotaxa_query")`. Do not call `load_skill("ecotaxa_query")` after an error.
- Do not call `query_ecotaxa` for preview-only requests such as "présente-moi"; reserve it for explicit "charge" or "exporte" requests.
- Preserve EcoTaxa source links and do not remove links from copied EcoTaxa tables.
