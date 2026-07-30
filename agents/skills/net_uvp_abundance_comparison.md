---
name: net_uvp_abundance_comparison
version: 2.1.3
triggers:
  - User asks to compare net (NeoLabs) abundance against UVP (EcoTaxa/EcoPart) abundance
  - User asks to join net and UVP data, compute density, make comparisons by taxon or stage
forbidden_when:
  - No NeoLabs file is loaded
  - df_net_uvp_matches does not exist yet — call find_uvp_matches_for_net_table first
requires:
  - "file:loaded"
next_tool: run_pandas
max_tokens: 3500
size_exemption: The certified net↔UVP chain and the stratum-matched profile method share one mandatory procedure; the size allowance prevents those safeguards from diverging.
description: >
  Guided certified preparation for net↔UVP comparisons, followed by open
  analysis where the user drives taxon, stage, and depth range.
---

# Skill: net_uvp_abundance_comparison

## What is in session

After the guided preparation steps, the session contains:

| Variable | Content |
|---|---|
| `df_net_uvp_matches` | Correspondence table: `net_sample_id`, `net_deployment_id`, `station`, `uvp_sample_id`, `uvp_profile_str`, `distance_km`, `time_gap_days`, `ctd_filename_match_status`, `amundsen_filename`, `station_name_match`, `match_status`, `join_eligible` |
| exact variable returned by the EcoTaxa export | Consolidated multi-project UVP objects with `export_project_id` |
| exact variable returned by the EcoPart enrichment | Multi-project UVP objects enriched with EcoPart volumes |
| `df_net_uvp_ecopart` | Canonical final object table created by `join_net_uvp_enriched`; it contains certified rows or explicitly confirmed exploratory rows |
| `df_file_neolabs_abundance` | Net tow taxonomy: `SAMPLE_ID`, `STATION_NAME`, `CLASS`, `ORDER`, `FAMILY`, per-stage abundance columns (`C1_ABUND ...`, `ALL_STAGES_ABUND ...`) |
| `df_file_neolabs_sample` | Net tow metadata: `SAMPLE_ID`, `STATION_NAME`, `latitude`, `longitude`, `deployment_datetime_start` |

Variable names come from successful tool results:
- `load_file("neolabs_abundance.csv")` → `df_file_neolabs_abundance`
- `load_file("neolabs_sample.csv")` → `df_file_neolabs_sample`
- `find_uvp_matches_for_net_table(...)` → `df_net_uvp_matches`
- `join_net_uvp_enriched(...)` → `df_net_uvp_ecopart`

All of these are automatically injected into every `run_pandas` call — no reload needed.

## Guided preparation: audit → export → EcoPart → final join

1. If the user requests a filet subset, create it with `run_pandas` and an
   explicit `persist_as`. Use the **exact persistent variable returned** in
   `Persistence: persisted=true` for the audit. If the audit rejects a wrong
   table name, read the **available persistent variables** from that blocked
   result and **retry the audit with that exact name**; never guess a replacement.
2. Run `find_uvp_matches_for_net_table` on that exact table. A normalized
   station match is mandatory; spatial and temporal information only choose
   among candidates from that same station. The certified export scope is only
   the rows where `join_eligible=True` and
   `ctd_filename_match_status="matched"`.
   - If the audit says the CTD source is unavailable, ask in plain language:
     “La vérification CTD n’est pas accessible pour le moment : ces
     correspondances ne peuvent pas être certifiées. Souhaites-tu quand même
     préparer un export provisoire, clairement signalé comme non vérifié ?”
     Do not expose internal labels, tool arguments, or selection identifiers.
     A natural “oui, continue sans CTD” is sufficient confirmation.
   - On that confirmation, do not merely acknowledge the exploratory
     confirmation: the very next tool call must be `find_uvp_matches_for_net_table`
     with the exact same audit arguments plus `allow_unverified_ctd=True`.
   - That re-audit makes its exact selection the active selection. Call
     `export_ecotaxa_samples(selection_name="latest", confirmed=False)` in the
     same turn: it cannot accidentally use a guessed selection identifier.
     This dry-run downloads nothing. Then wait for a separate explicit export confirmation
     before calling `confirmed=True`.
   - **Never use the exploratory override for a CTD no match.** For a no-match,
     stop before `export_ecotaxa_samples`, keep the audit visible, and do not
     create an export plan.
3. Reuse the **exact certified selection identifier returned by the audit**, or
   the exact exploratory selection identifier returned by the re-audit.
   For the certified path, call `export_ecotaxa_samples(confirmed=False)` for
   the project-by-project dry-run. For the exploratory path, that dry-run was
   already performed in step 2: do not repeat it. Wait for the separate export
   confirmation, then call the same selection with `confirmed=True`. Never
   rebuild its sample IDs manually.
4. On the consolidated multi-project EcoTaxa table, call
   `enrich_ecotaxa_with_ecopart_remote(confirmed=False)`. Present the EcoPart
   project-by-project plan, wait for a new explicit confirmation, then call
   `confirmed=True`. Keep partial-project coverage visible.
5. Call `join_net_uvp_enriched` with the exact persisted filet, audit, and
   enriched-campaign variable names. This local tool is the only final bridge.
   Pass `allow_unverified_ctd=True` when the persisted audit and selection are
   marked `ctd_verification="unavailable"` and `exploratory=True`.
   Continue calculations only from its canonical `df_net_uvp_ecopart` result.
   Keep `export_project_id` in every canonical aggregation and pair it with
   `uvp_profile_str`; profile labels are not globally unique across projects.

The exploratory override, EcoTaxa object export, and later EcoPart downloads
each require their own distinct confirmation.

## Non-negotiable validation gate

An audit row can authorize a certified filet↔UVP abundance comparison only when
`join_eligible=True` and `ctd_filename_match_status="matched"`. This proves a
normalized station match, the net↔UVP position and time checks **and** a shared
CTD-rosette file validated in Amundsen against its station, time, and
coordinates. A differently named station is excluded before the spatial/time
comparison. A `spatial_only`,
`filename_candidate`, missing CTD evidence, or station-name resemblance remains
an auditable candidate, never an export or analysis row. The sole exception is
the confirmed source-unavailable path above; its rows must retain
`ctd_verification="unavailable"` and `exploratory=True`. A CTD no-match is never
eligible. Do not fall back to a station-, zone-, or spatial-only comparison.

The certification call is filename-led and metadata-only. Retrieve `PRES` or
other vertical CTD variables only after validation, when the user explicitly
requests CTD enrichment.

For every authorized comparison, keep these audit fields in the paired table
or accompanying audit: `distance_km`, `time_gap_days`, `uvp_ctd_filename`,
`amundsen_filename`, `station_match`, `ctd_filename_distance_km`,
`ctd_filename_time_delta_min`, and `match_status`.

## How to compute UVP density (run_pandas)

```python
from core.copepod_sample_depth import build_canonical_sample_depth

# taxon_filter examples:
#   None          → copepods only (copepod_hierarchy_mask)
#   "Calanus"     → any object whose hierarchy contains "Calanus"
#   "Copepoda"    → all copepods via substring match
#   "Appendicularia" → appendicularians
#   "*"           → all organisms

canonical = build_canonical_sample_depth(
    df_net_uvp_ecopart,                  # certified final object table
    taxon_filter="Calanus",              # ← user's choice
    volume_column="ecopart_Sampled volume [L]",
    stable_columns=("uvp_profile_str",),
)
# canonical columns include export_project_id, uvp_profile_str, sample_id,
# depth_bin, target_count, sampled_volume_L, abundance_ind_L, abundance_ind_m3.

# Aggregate per project + profile (mean over casts and depth bins).
uvp_density = (
    canonical
    .groupby(
        ["export_project_id", "uvp_profile_str"],
        as_index=False,
    )["abundance_ind_m3"]
    .mean()
)
```

Restrict to a depth range before aggregating if the user asks:
```python
bins = canonical[(canonical["depth_bin"] >= 0) & (canonical["depth_bin"] <= 200)]
```

## How to compute net density (run_pandas)

```python
from core.neolabs_abundance import neolabs_copepod_density, STAGE_GROUPS

# stages presets:
#   "ALL_STAGES"   → all stages combined (default)
#   "late_stages"  → C4+C5+M+F  (comparable to UVP, >~600 µm)
#   "adults"       → M+F only
#   "copepodites"  → C1 to C5
#   "nauplii"      → N1 to N6
#   ["C5","M","F"] → explicit list

# taxon_filter matches the CLASS column (or pass taxon_column="FAMILY" for family-level)
net_density = neolabs_copepod_density(
    df_file_neolabs_abundance,
    stages="late_stages",            # ← user's choice
    taxon_filter="Copepoda",         # ← user's choice
    taxon_column="CLASS",
)
# net_density columns: STATION_NAME, copepod_density_ind_m3, n_samples,
#                      stages_used, taxon_filter
```

## Compare from the canonical final table (run_pandas)

```python
from core.net_uvp_comparison import compare_paired_density

# The certified final table already carries the audited net/profile bridge.
# Reduce it to one mapping row per profile before attaching calculated densities.
certified_bridge = df_net_uvp_ecopart[
    [
        "export_project_id",
        "uvp_profile_str",
        "station",
        "join_eligible",
        "ctd_filename_match_status",
    ]
].drop_duplicates()

if (
    certified_bridge.empty
    or not certified_bridge["join_eligible"].all()
    or not certified_bridge["ctd_filename_match_status"].eq("matched").all()
):
    raise ValueError("Table finale non certifiée : comparaison non réalisable.")

paired = (
    certified_bridge
    .merge(
        net_density.rename(
            columns={
                "STATION_NAME": "station",
                "copepod_density_ind_m3": "net_ind_m3",
            }
        ),
        on="station",
        how="inner",
    )
    .merge(
        uvp_density.rename(columns={"abundance_ind_m3": "uvp_ind_m3"}),
        on=["export_project_id", "uvp_profile_str"],
        how="inner",
    )
)

result = compare_paired_density(paired, net_col="net_ind_m3", uvp_col="uvp_ind_m3")
# adds: abundance_delta_ind_m3, abundance_abs_delta_ind_m3,
#       abundance_ratio (uvp/net), abundance_log2_ratio
```

## Interpretation rules

- `abundance_ratio` near 1 = concordant; >> 1 = UVP reads higher; << 1 = net reads higher.
- Net tows and UVP are not expected to give identical numbers: different sampling volumes,
  size selectivity, detection thresholds. Never present one as "more correct".
- UVP detects organisms reliably above ~600 µm → compare `late_stages` (C4+C5+M+F)
  on the net side when comparing totals, not `ALL_STAGES` which includes nauplii.
- Always keep the CTD audit fields named above visible in the paired table or
  accompanying audit; never reduce them to a station name or a distance alone.
- No causal or biological interpretation: describe the numbers, state the comparison basis.

## Stratified vertical profile (mandatory for filet ↔ UVP)

Use this procedure when the user asks for a vertical profile or a comparison by
depth stratum. It is an analytical calculation, then the already-active graph
rules render its exact persisted result.

1. Start from the canonical final object table, never from a whole UVP profile
   or from an unaudited candidate. A profile can serve several net strata.
2. Inspect the available net abundance fields. If more than one metric or stage
   scope is plausible, name the choices and ask the user. For the chosen field,
   remove object-expanded duplicates at the net taxon-row grain, then **sum**
   taxon rows once per `net_sample_id` and `[min_sample_depth,
   max_sample_depth]`. Never average taxon rows and never sum their copies
   repeated by the object join.
3. For each audited net stratum, retain UVP records from the same project and
   profile whose depth bin lies in that **same depth interval**. Count unique
   target object identifiers for the numerator. For the denominator, take the
   sampled volume once per depth bin and use the **sum of sampled volumes**.
   Convert the resulting UVP density to `ind./m³` before comparison.
4. Retain a zero UVP abundance only when the selected interval has a positive,
   documented sampled volume. If volume coverage for a bin or interval cannot
   be established, mark that stratum incomplete and exclude it rather than
   treating it as zero.
5. Never compare a full UVP profile with one net stratum. A profile plot uses
   one paired UVP value and one paired net value per common interval. Draw the
   net interval itself (its lower and upper depth), not only a point detached
   from the sampled stratum.

Persist the prepared comparison table. It must retain at least: net sample,
station, project, UVP profile, lower and upper depth, net abundance in
`ind./m³`, UVP target-object count, UVP sampled volume in L, UVP abundance in
`ind./m³`, and the CTD/exploratory status.

### Method disclosure

With every such graph, state concisely:

- **Filet** — selected abundance field, taxon/stage scope, and aggregation by
  depth stratum;
- **UVP** — target annotation criterion, same depth interval, unique-object
  numerator, and sampled-volume denominator;
- **Common unit** — `ind./m³` and any conversion used;
- **Zeros and coverage** — whether a zero has documented volume coverage or a
  stratum was excluded as incomplete;
- **Validation** — certified or exploratory, with the reason when exploratory.

The user may change the net metric or stages, taxon criterion, depth interval,
binning, volume basis, zero policy, or graph scale. On a requested change,
rebuild the named comparison table and repeat this disclosure; never silently
keep the old parameters.

## Graphs

After building `result`, use the already-active graph rules, then call `run_graph` for:
- Scatter: `net_ind_m3` vs `uvp_ind_m3` per station (1:1 line reference)
- Bar: `abundance_log2_ratio` per station (0 = perfect agreement)
- Map: station bubbles coloured by ratio (needs lat/lon from `df_file_neolabs_sample`)
- Vertical profile: paired net and UVP values by the same net stratum. Use a
  segment spanning each net interval for both methods; a connector may show the
  within-stratum comparison. Keep exploratory and certified series visually
  distinguishable.
