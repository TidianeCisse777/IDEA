"""Canonical prompt contract for numeric evidence routing."""

NUMERIC_EVIDENCE_RULES = """## Numeric Evidence Rules
- A numeric value already returned by a specialized tool is authoritative for that request. Use it directly with its provenance; do not call `run_pandas` only to reproduce it.
- Use `run_pandas` for a derived value: any new aggregation, transformation, metric, ratio, ranking, filter count, or statistic computed from a persisted table.
- If the requested numeric value is absent and no persisted structure can produce it, report it as unknown. Never estimate, infer, or invent it.
- Text visible only in conversation is not a calculable table. Materialize the required data first or state the limit."""
