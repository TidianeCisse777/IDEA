"""Canonical prompt contract for semantic graph-output routing."""


GRAPH_OUTPUT_ROUTING_RULES = """## Graph Output Routing Rules
- Intent -> route: map/profile/curve/chart/visual encoding = visual; number,
  calculation, ranking, summary, coordinates or table = non-visual unless a
  graphic is requested. “Show/display/present” alone is not visual intent.
- Ambiguous format -> minimal non-visual answer; ask only if it changes the
  result.
- Visual -> call `run_graph` directly. EcoTaxa maps also reuse active
  `ecotaxa_navigation`. Exact cache map (`sample_id`, `iho_zone`, `lat_avg`,
  `lon_avg`) -> render directly. When the schema is known, construct `plot_df`
  and render in one `run_graph` call. Otherwise inspect candidate fields +
  complete rows, then render; preparation alone is not completion.
- Correctable `run_graph` block -> retry exactly once with its diagnostic and
  same dataframe. If still blocked, report the diagnostic; never claim a graph
  or silently return a table."""
