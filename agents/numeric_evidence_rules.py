"""Canonical prompt contract for numeric evidence routing."""

NUMERIC_EVIDENCE_RULES = """## Numeric Evidence Rules
- Specialized returned number -> authoritative; keep provenance, do not
  reproduce it with `run_pandas`.
- New aggregation/transformation/metric/ratio/ranking/filter/statistic from a
  persisted table -> `run_pandas`.
- Absent value + no calculable table -> unknown. Never estimate, infer or invent.
- Conversation text is not a table -> materialize data or state the limit."""
