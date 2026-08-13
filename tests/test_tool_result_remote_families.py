"""Structured-result contracts for the canonical enrichment tools."""

from __future__ import annotations

import pandas as pd
import pytest
from langchain_core.messages import ToolMessage


REMOTE_FAMILIES = {"ecopart", "amundsen", "bio_oracle", "ogsl"}


def _call(item, call_id: str, **arguments) -> ToolMessage:
    message = item.invoke({
        "type": "tool_call",
        "id": call_id,
        "name": item.name,
        "args": arguments,
    })
    assert isinstance(message, ToolMessage)
    return message


def test_eight_remote_tools_declare_structured_results(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    from tools.tool_catalog import build_tool_catalog

    catalog = build_tool_catalog("remote-result-contract")
    names = {
        name for name, policy in catalog.policies.items()
        if policy.family in REMOTE_FAMILIES
    }
    by_name = {item.name: item for item in catalog.tools}

    assert len(names) == 8
    for name in names:
        assert by_name[name].response_format == "content_and_artifact"
        assert catalog.policy(name).result_schema == "tool_result_v1"


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("enrich_ecotaxa_with_ecopart_remote", {"confirmed": False}),
        ("enrich_with_amundsen_ctd", {}),
        ("enrich_with_bio_oracle", {}),
        ("enrich_with_ogsl", {}),
    ],
)
def test_enrichments_without_a_dataframe_are_blocked(monkeypatch, name, arguments):
    monkeypatch.setenv("DATABASE_URL", "")
    from tools.tool_catalog import build_tool_catalog
    from tools.tool_result import validate_tool_artifact

    item = {tool.name: tool for tool in build_tool_catalog("remote-blocked").tools}[name]
    message = _call(item, f"blocked-{name}", **arguments)

    assert validate_tool_artifact(message.artifact).status == "blocked"


def test_ecopart_inconclusive_preflight_is_short_and_unambiguous(
    tmp_path,
    monkeypatch,
):
    from tools import ecopart_sources
    from tools.session_store import SessionStore

    class FakeEcopartClient:
        def login(self):
            return None

        def search_samples(self, **kwargs):
            assert kwargs["project_id"] == 1100
            return [
                {"name": f"EP-{index:02d}", "visibility": "PUBLIC Y"}
                for index in range(64)
            ]

    thread_id = "ecopart-short-preflight"
    store = SessionStore(tmp_path / "sessions")
    store.set(
        f"{thread_id}:ecotaxa",
        pd.DataFrame({
            "sample_profileid": [f"UVP-{index:02d}" for index in range(23)],
            "object_depth_min": range(23),
        }),
        {"project_id": 17498},
    )
    monkeypatch.setattr(ecopart_sources, "_store", store)
    monkeypatch.setattr(ecopart_sources, "EcopartClient", FakeEcopartClient)
    monkeypatch.setattr(ecopart_sources, "bootstrap_consumer_cache", lambda *_: None)

    item = {
        tool.name: tool for tool in ecopart_sources.make_ecopart_tools(thread_id)
    }["enrich_ecotaxa_with_ecopart_remote"]
    message = _call(
        item,
        "ecopart-short-preflight-call",
        ecotaxa_project_id=17498,
        ecopart_project_id=1100,
        confirmed=False,
    )

    assert message.content == (
        "Préflight EcoPart — aucun téléchargement.\n"
        "EcoTaxa 17498 → EcoPart 1100 : INCONCLUSIF.\n"
        "Profils EcoTaxa examinés (23) : UVP-00, UVP-01, UVP-02, UVP-03, "
        "UVP-04, UVP-05, UVP-06, UVP-07, +15 autres.\n"
        "Profils EcoPart reconnus exactement (0) : aucun.\n"
        "Contrôle rapide : 0 correspondance textuelle "
        "(23 identifiants EcoTaxa, 64 profils EcoPart).\n"
        "Jointure réelle non exécutée; confirmation requise pour l’essayer."
    )
