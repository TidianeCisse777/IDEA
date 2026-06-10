# Skill: ecotaxa_query

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

---

## Key parameters of `query_ecotaxa`

| Parameter | Default | Notes |
|---|---|---|
| `project_id` | — | Required |
| `taxon` | `None` (all taxa) | e.g. `"Copepoda"`, `"Calanus"` — filtered server-side in EcoTaxa |
| `status` | `"V"` | `"V"` = validated only, `"P"` = predicted, `""` = all |

**Recommendation:** always use `status="V"` for quantitative analyses — unvalidated predicted objects may contain classification errors.

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
To combine the data:

1. Load EcoTaxa: `query_ecotaxa(project_id=1165)`
2. Load EcoPart: `query_ecopart(project_id=105)`
3. Join: `join_ecotaxa_ecopart`

**Join key:**
`obj_orig_id` in EcoTaxa (e.g. `ips_007_899`) → strip `_NNN` suffix → `profile_id` (`ips_007`) → matches the EcoPart sample identifier.

```python
df["profile_id"] = df["obj_orig_id"].str.replace(r"_\d+$", "", regex=True)
```

The join result contains both EcoTaxa taxonomy/morphometry and EcoPart CTD columns
(`Depth [m]`, `Sampled volume [L]`, LPM columns).
See skill `uvp_ecopart` for m1-m3 metrics computable from EcoPart.

---

## Edge cases

- If the project has >100,000 objects, the export can take 1-2 minutes — warn the user.
- If `taxon` is specified but returns 0 rows: check the exact spelling of the taxon name (case-sensitive in EcoTaxa).
- Without valid credentials (`ECOTAXA_TOKEN` or `ECOTAXA_USERNAME`/`ECOTAXA_PASSWORD`), the tool returns an error — ask the user to check their `.env`.
