# Skill: ecopart_query

## Activation precondition

Apply this skill only when the current user request explicitly names EcoPart
and the active session does not forbid EcoPart. Do not load or apply this skill
for generic requests about samples, projects, stations, positions, zones,
maps, counts, environmental variables, or analyses. A loaded file remains the
default source unless the user explicitly requests EcoPart.

You just called `query_ecopart` and EcoPart data is now loaded in the session.
This skill provides the rules for interpreting the result and guiding the user.

---

## Choosing the right tool

- To list available samples in a project: call `list_ecopart_samples`.
- To preview a sample without loading everything: call `preview_ecopart_sample`.
- To load, export or analyse the full project data: call `query_ecopart`.
- Do not call `query_ecopart` for a simple preview request.

---

## Key parameters of `query_ecopart`

| Parameter | Default | Notes |
|---|---|---|
| `project_id` | `105` | EcoPart Amundsen 2018 |
| `ctd_vars` | `["depth", "datetime", "temperature", "practical_salinity"]` | CTD variables to export |
| `gpr_vars` | `["cl6", "cl7", "cl8", "bv6", "bv7", "bv8"]` | UVP size classes (LPM) |

The defaults cover standard Amundsen usage — only change them if the user requests specific variables.

---

## Expected columns in the EcoPart TSV

| Column | Content |
|---|---|
| `Profile` | Profile identifier (e.g. `ips_007`) — join key with EcoTaxa |
| `Depth [m]` | Depth in metres |
| `Sampled volume [L]` | Volume sampled by the UVP camera |
| `temperature` | CTD temperature (°C) |
| `practical_salinity` | Practical salinity (PSU) |
| `cl6`…`cl8` | Concentration by size class (LPM, #/L) |
| `bv6`…`bv8` | Biovolume by size class (mm³/L) |

---

## After loading

1. **Check columns**:
   ```python
   result = df.columns.tolist()
   ```

2. **Inspect available profiles**:
   ```python
   result = df["Profile"].unique().tolist()
   ```

3. **If LPM metrics requested** → load skill `uvp_ecopart` for m1-m3 calculation methods.

---

## Download link

The summary returned by `query_ecopart` contains a link `http://localhost:8000/downloads/<id>.tsv`.
**Include this link in your response** — the user can click it to download the full file.

---

## Combining EcoPart with EcoTaxa

EcoPart provides **CTD + UVP particle profiles**; EcoTaxa provides **annotated taxonomy**.
Use the dedicated tools — do **not** hand-roll the merge in `run_pandas`:

1. If EcoTaxa is already in session from `load_file` or a prior export, do **not** call `query_ecotaxa` again.
2. If an EcoPart project is already loaded in session, join locally with `join_ecotaxa_ecopart`.
3. If EcoPart is not yet loaded, use `enrich_ecotaxa_with_ecopart_remote` as the default route (it auto-resolves the EcoPart project and joins).
4. Only call `query_ecotaxa(project_id=...)` when the user explicitly asks to load or export a specific EcoTaxa project.

**Join key (handled by the tool):** the join is on `(sample_id, depth_bin)`. The EcoTaxa side
resolves to the profile identifier — raw `sample_id`, `sample_id`/`obj_orig_id` stripped of the
`_NNN` object suffix (`ips_007_899` → `ips_007`), or a profile/station label — matched against the
EcoPart `Profile` column; `depth_bin` is a 5 m bin computed from the object depth. The tool picks
the EcoTaxa key with the best overlap against EcoPart profiles, so a single non-matching row never
derails the join.

If the loaded EcoTaxa export already exposes `sample_id`, `object_depth_min`, `object_lat`, or `object_lon`, the remote enrichment tool can use those columns directly; do not force a fresh EcoTaxa download.

**Always report match coverage.** The join/enrich result states how many objects matched an EcoPart bin. Relay that count, and if it is 0 or low, warn the user that the enrichment did not really take — usually because the two datasets are different campaigns (no shared profiles) or the objects sit outside the depth range the EcoPart cast actually covered (shallower than its first bin → `NaN`). Never present a `NaN`-filled enrichment, or metrics derived from it, as a success.

---

## Edge cases

- EcoPart has no REST API — the client uses a cookie session. If the export fails with an HTTP error, check that `ECOTAXA_USERNAME`/`ECOTAXA_PASSWORD` are set in `.env`.
- If `start_export` returns an empty link list, the project is not accessible with the configured account.
- The export can take 30-60 seconds for a large project — warn the user.
