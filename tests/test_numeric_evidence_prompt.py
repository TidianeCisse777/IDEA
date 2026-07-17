"""Contrats du system prompt pour l'autorité des preuves numériques."""

from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT


def test_specialized_tool_value_is_direct_numeric_evidence():
    assert "A numeric value already returned by a specialized tool" in COPEPOD_SYSTEM_PROMPT
    assert "do not call `run_pandas` only to reproduce it" in COPEPOD_SYSTEM_PROMPT


def test_derived_table_value_requires_controlled_execution():
    assert "Use `run_pandas` for a derived value" in COPEPOD_SYSTEM_PROMPT
    assert "computed from a persisted table" in COPEPOD_SYSTEM_PROMPT


def test_absent_numeric_value_remains_unknown():
    assert "report it as unknown" in COPEPOD_SYSTEM_PROMPT
    assert "Never estimate, infer, or invent it" in COPEPOD_SYSTEM_PROMPT


def test_numeric_rules_are_canonical_and_injected_once():
    from agents.numeric_evidence_rules import NUMERIC_EVIDENCE_RULES

    assert COPEPOD_SYSTEM_PROMPT.count(NUMERIC_EVIDENCE_RULES) == 1
    assert "Always call `run_pandas` to produce any numeric value" not in COPEPOD_SYSTEM_PROMPT
