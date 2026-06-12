# Multi-EcoPart Session Design

## Goal

Allow one agent thread to load, persist, inspect, compare, and join several
EcoPart projects without replacing previously loaded EcoPart DataFrames.

## Session Keys

Loading EcoPart project `105` stores the same DataFrame under:

- `<thread_id>`: the last DataFrame loaded in the thread.
- `<thread_id>:ecopart`: backward-compatible alias for the latest EcoPart project.
- `<thread_id>:ecopart:105`: stable project-specific entry.

Loading project `42` afterward updates the first two entries but leaves
`<thread_id>:ecopart:105` intact and creates `<thread_id>:ecopart:42`.

Project-specific entries use the existing `SessionStore` persistence mechanism,
so they remain available after a process restart.

## DataFrame Variables

`run_pandas` and `run_graph` expose:

```python
df                 # Last DataFrame loaded from any source
df_ecopart         # Latest EcoPart project
df_ecopart_105     # EcoPart project 105
df_ecopart_42      # EcoPart project 42
```

The project-specific variable suffix is derived from the integer `project_id`,
so every generated variable is a valid and predictable Python identifier.

Existing variables such as `df_ecotaxa`, `df_ctd`, and `df_bio_oracle` remain
unchanged.

## Project Discovery

`SessionStore` will provide a method to list stored entries whose keys begin
with a thread-specific prefix. This avoids reaching into its private in-memory
dictionary and also discovers entries persisted on disk.

The data tools use this method to find all keys matching:

```text
<thread_id>:ecopart:<project_id>
```

Each matching DataFrame is injected into the pandas or graph execution
environment under `df_ecopart_<project_id>`.

## EcoPart Query Behavior

After a successful `query_ecopart(project_id=105)`:

1. Store the DataFrame as the thread's current `df`.
2. Update the latest-EcoPart alias.
3. Store the stable project-specific entry.
4. Return a message that names `df_ecopart_105` and `df_ecopart`.

Loading the same project again replaces only that project's stored version and
refreshes the latest aliases.

## Join Behavior

The tool signature becomes:

```python
join_ecotaxa_ecopart(project_id: int | None = None)
```

- With `project_id=105`, it reads `<thread_id>:ecopart:105`.
- Without `project_id`, it reads `<thread_id>:ecopart`, preserving current
  behavior by using the latest EcoPart project.
- If an explicit project is unavailable, the error identifies that project and
  asks the agent to call `query_ecopart(project_id=<id>)`.
- Successful joins include the selected EcoPart project in their metadata and
  response.

EcoTaxa selection remains unchanged in this scope: the join uses the current
`<thread_id>:ecotaxa` entry.

## Compatibility

No existing session key or DataFrame variable is removed. Existing prompts and
code using `df`, `df_ecopart`, or `join_ecotaxa_ecopart()` continue to work.

This change does not introduce automatic merging between EcoPart projects.
Users compare or combine explicit variables through `run_pandas`.

## Tests

Tests will verify:

1. Loading two EcoPart projects preserves both project-specific entries.
2. The latest aliases point to the most recently loaded project.
3. Project-specific entries survive a new `SessionStore` instance.
4. `run_pandas` exposes both explicit variables and `df_ecopart`.
5. `run_graph` receives the same variables.
6. An explicit join selects the requested EcoPart project.
7. A join without `project_id` selects the latest EcoPart project.
8. A missing explicit project returns an actionable error.
