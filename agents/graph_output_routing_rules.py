"""Canonical prompt contract for semantic graph-output routing."""

GRAPH_OUTPUT_ROUTING_RULES = """## Graph Output Routing Rules
- Decide from the requested output intent, not from individual words. Load graph skills only when the user asks for or clearly implies a visual representation of the data.
- A general presentation verb such as “show”, “display”, or “present” does not establish visual intent by itself. Infer the intended artifact from what is being requested.
- A map, plotted vertical profile, curve, chart, or other graphical encoding is visual even when the user does not use the word “graph”. These are examples of visual intent, not a closed trigger list.
- A number, calculation, ranking, summary, coordinates, or table is non-visual unless the user also requests a graphical representation. Do not load `graph_planner` or `graph_writer`; use the specialized or tabular execution tool only when needed.
- If the output format is genuinely ambiguous, prefer the minimal non-visual answer. Ask only when the choice would materially change the requested result.
- For visual intent, call `load_skill("graph_planner")`, wait for the planner result, then call `load_skill("graph_writer")`; do not stop after planning. Never request planner and writer in the same tool-call batch. The very next execution call after `load_skill("graph_writer")` must be `run_graph`."""
