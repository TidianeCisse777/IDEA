"""Contradictions de routage actuellement portées par des sources distinctes."""

from __future__ import annotations

import pytest


def test_bare_project_id_does_not_authorize_ecotaxa():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT
    from tools.source_scope import ecotaxa_signal

    assert "A project number alone is not an EcoTaxa signal" in COPEPOD_SYSTEM_PROMPT
    assert ecotaxa_signal("résume le projet 17498") is False, (
        "source_scope.py autorise actuellement EcoTaxa avec un project_id nu, "
        "contrairement au Source Selection Gateway"
    )


@pytest.mark.xfail(
    strict=True,
    reason="Étape 4: réserver run_pandas aux valeurs dérivées ou non fournies par un tool",
)
def test_specialized_numeric_tool_results_do_not_require_run_pandas():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "always call `run_pandas` to produce any numeric value" not in prompt, (
        "la règle absolue contredit les tools spécialisés de count/summarize"
    )
    assert "derived" in prompt and "specialized" in prompt
