"""Static contracts for source routing and tool-result truth in the prompt."""

from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT


def test_source_gateway_precedes_source_specific_routing():
    gateway = COPEPOD_SYSTEM_PROMPT.index("## Source Selection Gateway")
    ecotaxa = COPEPOD_SYSTEM_PROMPT.index("EcoTaxa")
    assert gateway < ecotaxa


def test_generic_requests_default_to_loaded_file():
    assert "A loaded file is the default source" in COPEPOD_SYSTEM_PROMPT
    assert "Generic words are never external-source signals" in COPEPOD_SYSTEM_PROMPT


def test_external_sources_require_exact_name():
    for source in ("EcoTaxa", "EcoPart", "Amundsen CTD", "Bio-ORACLE", "OGSL"):
        assert f"name `{source}` explicitly" in COPEPOD_SYSTEM_PROMPT


def test_project_number_alone_is_not_ecotaxa():
    assert "A project number alone is not an EcoTaxa signal" in COPEPOD_SYSTEM_PROMPT


def test_explicit_lock_requires_explicit_release():
    assert (
        "persists across turns until the user explicitly releases it"
        in COPEPOD_SYSTEM_PROMPT
    )
