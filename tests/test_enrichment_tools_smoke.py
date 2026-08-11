"""One successful offline smoke path for each remote tool family."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from langchain_core.messages import ToolMessage
import pandas as pd
import pytest

from tools.session_store import SessionStore
from tools.tool_result import validate_tool_artifact


@pytest.fixture()
def store(tmp_path, monkeypatch):
    isolated = SessionStore(tmp_path / "sessions")
    monkeypatch.setattr("tools.session_store.default_store", isolated)
    for module in (
        "tools.amundsen_sources",
        "tools.bio_oracle_sources",
        "tools.ecopart_sources",
        "tools.ogsl_sources",
    ):
        monkeypatch.setattr(f"{module}._store", isolated)
    return isolated


def _call(item, call_id: str, **arguments) -> ToolMessage:
    message = item.invoke({
        "type": "tool_call",
        "id": call_id,
        "name": item.name,
        "args": arguments,
    })
    assert isinstance(message, ToolMessage)
    return message


def test_ecopart_preview_success_is_structured(tmp_path, monkeypatch):
    from tools.ecopart_sources import make_ecopart_tools

    monkeypatch.setenv("ECOPART_CACHE_DIR", str(tmp_path / "ecopart-cache"))
    client = MagicMock()
    client.preview_sample.return_value = {
        "sample_id": 42,
        "accessible": True,
        "text": "Station ips_007",
    }
    with patch("tools.ecopart_sources.bootstrap_consumer_cache", return_value=True), patch(
        "tools.ecopart_sources.EcopartClient", return_value=client
    ):
        item = {tool.name: tool for tool in make_ecopart_tools("smoke-ecopart")}["preview_ecopart_sample"]
        message = _call(item, "ecopart-preview", sample_id=42)

    assert validate_tool_artifact(message.artifact).status == "success"
    assert "ips_007" in message.content


def test_amundsen_enrichment_success_persists_dataframe(store):
    from tools.amundsen_sources import make_amundsen_tools

    thread_id = "smoke-amundsen"
    store.set(
        thread_id,
        pd.DataFrame({
            "latitude": [74.1],
            "longitude": [-80.2],
            "object_date": ["2018-08-01"],
        }),
        {"source": "file:stations.csv"},
    )

    def fake_fetch(**_kwargs):
        return pd.DataFrame([{
            "time": "2018-08-01T12:00:00Z",
            "latitude": 74.1,
            "longitude": -80.2,
            "station": "BRK-15",
            "cast_number": 7,
            "PRES": 2.0,
            "TE90": -1.2,
            "PSAL": 31.4,
        }])

    with patch("tools.amundsen_sources._fetch_amundsen_bbox", side_effect=fake_fetch):
        item = {tool.name: tool for tool in make_amundsen_tools(thread_id)}["enrich_with_amundsen_ctd"]
        message = _call(
            item,
            "amundsen-enrich",
            variables=["temperature", "salinity"],
            initial_batch_spatial_degrees=30,
        )

    result = validate_tool_artifact(message.artifact)
    assert result.status == "success" and result.persisted is True
    enriched = store.get(f"{thread_id}:dataset:{result.data_ref}")["df"]
    assert enriched["amundsen_match_status"].tolist() == ["matched"]
    assert enriched["amundsen_te90_degC"].tolist() == [-1.2]


def test_bio_oracle_enrichment_success_persists_dataframe(store):
    from tools.bio_oracle_sources import make_bio_oracle_tools

    thread_id = "smoke-bio-oracle"
    store.set(
        thread_id,
        pd.DataFrame({"latitude": [60.0], "longitude": [-65.0]}),
        {"source": "file:stations.csv"},
    )

    def fake_fetch(**_kwargs):
        frame = pd.DataFrame([{
            "time": "2050-01-01T00:00:00Z",
            "latitude": 60.0,
            "longitude": -65.0,
            "value": 8.42,
        }])
        frame.attrs["dataset_id"] = "thetao_ssp585_2020_2100_depthsurf"
        return frame

    with patch("tools.bio_oracle_sources._fetch_bio_oracle_bbox", side_effect=fake_fetch):
        item = {tool.name: tool for tool in make_bio_oracle_tools(thread_id)}["enrich_with_bio_oracle"]
        message = _call(
            item,
            "bio-enrich",
            variables=["temperature"],
            scenarios=["SSP5-8.5"],
            depth_layer="surface",
            statistic="mean",
            target_year=2050,
        )

    result = validate_tool_artifact(message.artifact)
    assert result.status == "success" and result.persisted is True
    enriched = store.get(f"{thread_id}:dataset:{result.data_ref}")["df"]
    assert enriched["bio_oracle_match_status"].tolist() == ["matched"]
    assert enriched["bio_oracle_temperature_ssp5_8_5"].tolist() == [8.42]


def test_ogsl_enrichment_success_persists_dataframe(store):
    from tools.ogsl_sources import make_ogsl_tools

    thread_id = "smoke-ogsl"
    store.set(
        thread_id,
        pd.DataFrame({
            "latitude": [48.7],
            "longitude": [-68.5],
            "object_date": ["2024-06-01"],
        }),
        {"source": "file:stations.csv"},
    )

    def fake_fetch(**_kwargs):
        return pd.DataFrame([{
            "time": "2024-06-01T12:00:00Z",
            "latitude": 48.7,
            "longitude": -68.5,
            "cruiseID": "IML-2024",
            "stationID": "STN-4",
            "cast_number": 1,
            "PRES": 2.0,
            "TE90": 4.1,
            "PSAL": 30.5,
            "OXYM": 280.0,
        }])

    with patch("tools.ogsl_sources._fetch_ogsl_bbox", side_effect=fake_fetch):
        item = {tool.name: tool for tool in make_ogsl_tools(thread_id)}["enrich_with_ogsl"]
        message = _call(item, "ogsl-enrich")

    result = validate_tool_artifact(message.artifact)
    assert result.status == "success" and result.persisted is True
    enriched = store.get(f"{thread_id}:dataset:{result.data_ref}")["df"]
    assert enriched["ogsl_match_status"].tolist() == ["matched"]
    assert enriched["ogsl_te90_degC"].tolist() == [4.1]
