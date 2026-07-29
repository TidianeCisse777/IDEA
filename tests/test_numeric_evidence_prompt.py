"""Contrats du system prompt pour l'autorité des preuves numériques."""

from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT


def test_specialized_tool_value_is_direct_numeric_evidence():
    assert "Specialized returned number -> authoritative" in COPEPOD_SYSTEM_PROMPT
    assert "do not\n  reproduce it with `run_pandas`" in COPEPOD_SYSTEM_PROMPT


def test_derived_table_value_requires_controlled_execution():
    assert "persisted table -> `run_pandas`" in COPEPOD_SYSTEM_PROMPT


def test_absent_numeric_value_remains_unknown():
    assert "-> unknown. Never estimate, infer or invent" in COPEPOD_SYSTEM_PROMPT


def test_numeric_rules_are_canonical_and_injected_once():
    from agents.numeric_evidence_rules import NUMERIC_EVIDENCE_RULES

    assert COPEPOD_SYSTEM_PROMPT.count(NUMERIC_EVIDENCE_RULES) == 1
    assert "Always call `run_pandas` to produce any numeric value" not in COPEPOD_SYSTEM_PROMPT
