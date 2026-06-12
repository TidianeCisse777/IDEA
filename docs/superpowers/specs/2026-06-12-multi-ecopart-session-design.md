# Persistent Multi-Dataset Session Design

## Goal

Allow one agent thread to load, persist, inspect, compare, and join every
downloaded dataset without replacing previously loaded DataFrames.

This applies to EcoPart, EcoTaxa, Amundsen, Bio-ORACLE, uploaded files, and SQL
workspace downloads.

## Stable Entries

Every downloaded dataset has a stable Python variable name and is stored under:

```text
<thread_id>:dataset:<variable_name>
```

Source-specific aliases remain for compatibility. For example, EcoPart project
`105` is stored as:

```text
<thread_id>                         # latest DataFrame from any source
<thread_id>:ecopart                # latest EcoPart DataFrame
<thread_id>:dataset:df_ecopart_105 # stable project entry
```

Loading project `42` updates the first two entries but preserves
`df_ecopart_105` and creates `df_ecopart_42`.

The same query identity replaces its own stable entry when downloaded again. A
different source identifier or query creates a separate entry.

## Variable Names

`run_pandas` and `run_graph` expose all persisted variables:

```python
df
df_ecopart
df_ecopart_105
df_ecopart_42
df_ecotaxa
df_ecotaxa_1165
df_ctd
df_amundsen_amundsen12713_brk_15_cast_7
df_bio_oracle
df_bio_oracle_thetao_ssp245_depthsurf_50_2_m65_8
df_file_stations_2024
df_sql_station_summary
```

Names are normalized to lowercase Python identifiers. Punctuation and spaces
become underscores, repeated underscores collapse, and an invalid leading
character is prefixed. Coordinate signs use `m` for negative values.

## Dataset Registry

A shared helper generates variable names and performs the three required writes:

1. Update the thread's current `df`.
2. Update the source's latest alias when one exists.
3. Store the stable dataset entry with `variable_name` in its metadata.

`SessionStore.keys()` discovers entries from memory and disk. Data tools scan
`<thread_id>:dataset:` and inject each DataFrame under its stored
`variable_name`.

## Source Naming

- EcoPart: `df_ecopart_<project_id>`.
- EcoTaxa: `df_ecotaxa_<project_id>`.
- Amundsen: dataset ID plus station and cast when supplied.
- Bio-ORACLE: variable, scenario, depth layer, latitude, and longitude.
- Uploaded file: sanitized filename stem, prefixed with `df_file_`.
- SQL workspace: sanitized requested output stem, prefixed with `df_sql_`.

Each source keeps its current latest alias where one already exists:
`df_ecopart`, `df_ecotaxa`, `df_ctd`, or `df_bio_oracle`.

## Join Behavior

The EcoTaxa/EcoPart join accepts an optional EcoPart `project_id`:

```python
join_ecotaxa_ecopart(project_id: int | None = None)
```

- With an ID, it selects `df_ecopart_<project_id>`.
- Without an ID, it uses the latest `df_ecopart`.
- Missing explicit projects produce an actionable error.

All other cross-source joins use explicit variables through `run_pandas`, which
prevents silently selecting the wrong dataset.

## Compatibility

No existing alias is removed. Existing code using `df`, `df_ecopart`,
`df_ecotaxa`, `df_ctd`, or `df_bio_oracle` continues to work.

## Tests

Tests verify:

1. Stable entries persist across `SessionStore` instances.
2. Multiple downloads from each source coexist.
3. Latest aliases point to the latest download of their source.
4. `run_pandas` and `run_graph` expose every stable variable.
5. Repeating an identical query replaces only its own entry.
6. Explicit and default EcoTaxa/EcoPart joins select the correct EcoPart data.
