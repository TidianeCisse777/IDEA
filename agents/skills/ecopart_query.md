# Skill: ecopart_query

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
To combine:

1. If EcoTaxa is already in session from `load_file` or a prior export, do **not** call `query_ecotaxa` again.
2. If an EcoPart project is already loaded in session, join locally with `join_ecotaxa_ecopart`.
3. If EcoPart is not yet loaded, use `enrich_ecotaxa_with_ecopart_remote` as the default route.
4. Only call `query_ecotaxa(project_id=...)` when the user explicitly asks to load or export a specific EcoTaxa project.

**Join key:**
`obj_orig_id` in EcoTaxa (e.g. `ips_007_899`) → strip `_NNN` suffix → `profile_id` (`ips_007`) → matches the `Profile` column in EcoPart.

If the loaded EcoTaxa export already exposes `sample_id`, `object_depth_min`, `object_lat`, or `object_lon`, the remote enrichment tool can use those columns directly; do not force a fresh EcoTaxa download.

```python
df_ecotaxa["profile_id"] = df_ecotaxa["obj_orig_id"].str.replace(r"_\d+$", "", regex=True)
df_joined = df_ecotaxa.merge(df_ecopart, left_on="profile_id", right_on="Profile", how="left")
```

---

## Edge cases

- EcoPart has no REST API — the client uses a cookie session. If the export fails with an HTTP error, check that `ECOTAXA_USERNAME`/`ECOTAXA_PASSWORD` are set in `.env`.
- If `start_export` returns an empty link list, the project is not accessible with the configured account.
- The export can take 30-60 seconds for a large project — warn the user.
