"""TDD — streaming SSE endpoint pour Open WebUI.

On vérifie :
1. _make_sse_chunk  → format JSON correct
2. _format_tool_line → contient 🔧 + nom de l'outil
3. _stream_agent_sse → émet tool_call puis réponse finale, termine par [DONE]
4. _stream_agent_sse → image base64 remplacée par URL hébergée
"""
import asyncio
import json
import pytest
from unittest.mock import MagicMock
from langchain_core.messages import AIMessage, ToolMessage


# ── helpers purs ───────────────────────────────────────────────────────────────

def test_sse_chunk_contains_content():
    from serve import _make_sse_chunk
    line = _make_sse_chunk("cid-001", "bonjour")
    assert line.startswith("data: ")
    payload = json.loads(line[len("data: "):])
    assert payload["choices"][0]["delta"]["content"] == "bonjour"
    assert payload["choices"][0]["finish_reason"] is None


def test_sse_chunk_stop_has_no_content_key():
    from serve import _make_sse_chunk
    line = _make_sse_chunk("cid-001", "", finish_reason="stop")
    payload = json.loads(line[len("data: "):])
    assert "content" not in payload["choices"][0]["delta"]
    assert payload["choices"][0]["finish_reason"] == "stop"


def test_format_tool_line_contains_icon_and_name():
    from serve import _format_tool_line
    line = _format_tool_line("load_file")
    assert "🔧" in line
    assert "load_file" in line


def test_format_tool_line_skill():
    from serve import _format_tool_line
    line = _format_tool_line("skill_tool")
    assert "skill_tool" in line


def test_is_data_source_tool_recognizes_known_sources():
    from serve import _is_data_source_tool
    assert _is_data_source_tool("query_ecotaxa")
    assert _is_data_source_tool("query_ecotaxa_sample")
    assert _is_data_source_tool("find_ecotaxa_observations")
    assert _is_data_source_tool("summarize_ecotaxa_samples")
    assert _is_data_source_tool("summarize_ecotaxa_projects")
    assert _is_data_source_tool("export_ecotaxa_samples")
    assert _is_data_source_tool("query_ecopart")
    assert _is_data_source_tool("query_amundsen_ctd")
    assert _is_data_source_tool("enrich_loaded_table_with_amundsen_ctd")
    assert _is_data_source_tool("query_bio_oracle")
    assert _is_data_source_tool("query_ogsl")
    assert _is_data_source_tool("preview_sql_table")
    assert not _is_data_source_tool("run_pandas")
    assert not _is_data_source_tool("run_graph")
    assert not _is_data_source_tool("load_file")
    assert not _is_data_source_tool("load_skill")


def test_normalize_postgres_dsn_for_langgraph_strips_sqlalchemy_driver():
    from serve import _normalize_postgres_dsn_for_langgraph

    assert _normalize_postgres_dsn_for_langgraph(
        "postgresql+psycopg://copepod:pass@postgres:5432/copepod_sessions"
    ) == "postgresql://copepod:pass@postgres:5432/copepod_sessions"
    assert _normalize_postgres_dsn_for_langgraph(
        "postgresql+psycopg2://copepod:pass@postgres:5432/copepod_sessions"
    ) == "postgresql://copepod:pass@postgres:5432/copepod_sessions"
    assert _normalize_postgres_dsn_for_langgraph(
        "postgresql://copepod:pass@postgres:5432/copepod_sessions"
    ) == "postgresql://copepod:pass@postgres:5432/copepod_sessions"


def test_format_tool_result_details_wraps_in_collapsible_block():
    from serve import _format_tool_result_details
    block = _format_tool_result_details(
        "query_ecotaxa",
        "| project_id | name |\n|---|---|\n| 42 | …|",
        {"project_id": 42},
    )
    assert "<details>" in block
    assert "</details>" in block
    assert "<summary>" in block
    # Libellé FR au lieu du nom interne du tool.
    assert "EcoTaxa" in block
    assert "query_ecotaxa" not in block
    # Résumé des args dans le titre.
    assert "projet 42" in block
    # Source EcoTaxa affichée explicitement.
    assert "ecotaxa.obs-vlfr.fr" in block
    # project_id 42 devient un lien cliquable vers la page projet.
    assert "(https://ecotaxa.obs-vlfr.fr/prj/42)" in block


def test_format_tool_result_details_linkifies_sample_and_project_columns():
    from serve import _format_tool_result_details
    content = (
        "| sample_id | projet | lat |\n"
        "|---:|---:|---:|\n"
        "| 42000002 | 1165 | 70.123 |\n"
    )
    block = _format_tool_result_details(
        "find_ecotaxa_samples_in_region", content, {"zone_name": "Baie de Baffin"},
    )
    # sample_id pointe vers le projet filtré sur ce sample (EcoTaxa n'a pas de
    # page sample isolée).
    assert "(https://ecotaxa.obs-vlfr.fr/prj/1165?samples=42000002)" in block
    assert "(https://ecotaxa.obs-vlfr.fr/prj/1165)" in block
    assert "Baie de Baffin" in block


def test_format_tool_result_details_matches_p8_ecotaxa_samples_contract():
    from serve import _format_tool_result_details

    content = (
        "| sample_id | project_id | date |\n"
        "|---:|---:|---|\n"
        "| 14853000001 | 14853 | 2024-10-06 |\n"
    )
    block = _format_tool_result_details(
        "find_ecotaxa_samples_in_region",
        content,
        {
            "zone_name": "Baie de Baffin",
            "date_range": {"from": "2024-01-01", "to": "2024-12-31"},
        },
    )

    assert (
        "📊 EcoTaxa · samples par zone / période — "
        "Baie de Baffin · 2024-01-01 → 2024-12-31"
    ) in block
    assert "find_ecotaxa_samples_in_region" not in block
    assert (
        "[14853000001](https://ecotaxa.obs-vlfr.fr/prj/14853?samples=14853000001)"
    ) in block
    assert "[14853](https://ecotaxa.obs-vlfr.fr/prj/14853)" in block
    assert "*Source : EcoTaxa — [https://ecotaxa.obs-vlfr.fr](https://ecotaxa.obs-vlfr.fr)*" in block


def test_format_tool_result_details_summarize_ecotaxa_keeps_source_links():
    from serve import _format_tool_result_details

    content = (
        "| sample_id | projet | V | P | total |\n"
        "|---:|---:|---:|---:|---:|\n"
        "| 14853000001 | 14853 | 80 | 8348 | 8428 |\n"
    )
    block = _format_tool_result_details(
        "summarize_ecotaxa_samples",
        content,
        {"sample_ids": [14853000001]},
    )

    assert "📊 EcoTaxa · résumé de samples" in block
    assert "[14853000001](https://ecotaxa.obs-vlfr.fr/prj/14853?samples=14853000001)" in block
    assert "[14853](https://ecotaxa.obs-vlfr.fr/prj/14853)" in block
    assert "*Source : EcoTaxa — [https://ecotaxa.obs-vlfr.fr](https://ecotaxa.obs-vlfr.fr)*" in block


def test_format_tool_result_details_skips_sample_link_without_project():
    """Sans colonne projet dans la même ligne, on ne fabrique pas de lien
    sample (impossible à construire correctement)."""
    from serve import _format_tool_result_details
    content = (
        "| sample_id | lat |\n"
        "|---:|---:|\n"
        "| 42000002 | 70.123 |\n"
    )
    block = _format_tool_result_details("find_ecotaxa_observations", content, None)
    assert "42000002" in block
    assert "/sample/" not in block
    assert "?samples=" not in block


def test_format_tool_result_details_non_ecotaxa_tool_keeps_raw_name():
    from serve import _format_tool_result_details
    block = _format_tool_result_details("query_bio_oracle", "any content")
    # Tools non-EcoTaxa gardent l'ancien format pour l'instant.
    assert "<code>query_bio_oracle</code>" in block


def test_format_tool_result_details_shows_cache_status_banners():
    from serve import _format_tool_result_details

    empty_block = _format_tool_result_details("query_ecotaxa", "CACHE_EMPTY")
    assert "Cache EcoTaxa vide" in empty_block
    assert "CACHE_EMPTY" not in empty_block

    syncing_block = _format_tool_result_details("query_ecotaxa", "SYNC_IN_PROGRESS")
    assert "Synchronisation en cours" in syncing_block
    assert "SYNC_IN_PROGRESS" not in syncing_block


def test_format_tool_result_details_hides_raw_base64_image():
    from serve import _format_tool_result_details
    payload = "before data:image/png;base64,AAAABBBBCCCCDDDD== after"
    block = _format_tool_result_details("preview_ecotaxa_project", payload)
    assert "AAAABBBB" not in block
    assert "[image data]" in block
    assert "before" in block and "after" in block


def test_format_tool_line_run_graph_with_code_uses_details():
    """run_graph avec code → bloc <details> collapsible avec le code Python."""
    from serve import _format_tool_line
    code = "plt.scatter(df['lon'], df['lat'])\nplt.show()"
    line = _format_tool_line("run_graph", {"code": code})
    assert "🔧" in line
    assert "run_graph" in line
    assert "plt.scatter" in line
    assert "```python" in line
    assert "<details>" in line
    assert "<summary>🔧 run_graph</summary>" in line


def test_format_tool_line_run_graph_shows_loading_indicator():
    """run_graph avec code → inclut un indicateur visuel de génération du graphique."""
    from serve import _format_tool_line
    code = "plt.scatter(df['lon'], df['lat'])"
    line = _format_tool_line("run_graph", {"code": code})
    assert "Génération du graphique" in line


def test_format_tool_line_run_pandas_no_loading_indicator():
    """run_pandas → pas d'indicateur graphique (aucune image à attendre)."""
    from serve import _format_tool_line
    line = _format_tool_line("run_pandas", {"code": "result = df.mean()"})
    assert "Génération" not in line


def test_format_tool_line_run_graph_without_code_no_loading_indicator():
    """run_graph sans code → pas d'indicateur (pas de génération en cours)."""
    from serve import _format_tool_line
    line = _format_tool_line("run_graph", {})
    assert "Génération" not in line
    assert "<details>" in line


def test_format_tool_line_run_pandas_with_code_uses_details():
    """run_pandas avec code → bloc <details> avec le code."""
    from serve import _format_tool_line
    code = "df.groupby('station').mean()"
    line = _format_tool_line("run_pandas", {"code": code})
    assert "🔧" in line
    assert "run_pandas" in line
    assert "df.groupby" in line
    assert "<details>" in line
    assert "<summary>🔧 run_pandas</summary>" in line


def test_format_tool_line_run_graph_without_code_fallback():
    """run_graph sans args → fallback simple avec 🔧."""
    from serve import _format_tool_line
    line = _format_tool_line("run_graph", {})
    assert "🔧" in line
    assert "run_graph" in line
    assert "<details>" in line
    assert "Paramètres : —" in line


def test_format_tool_line_load_file_shows_filename():
    """load_file avec path → affiche le nom de fichier, pas le chemin complet."""
    from serve import _format_tool_line
    line = _format_tool_line("load_file", {"path": "/tmp/webui_uploads/stations.tsv"})
    assert "load_file" in line
    assert "stations.tsv" in line
    assert "<details>" in line


def test_format_tool_line_skill_shows_skill_name():
    """load_skill avec skill_name → affiche le nom du skill."""
    from serve import _format_tool_line
    line = _format_tool_line("load_skill", {"skill_name": "map_stations"})
    assert "load_skill" in line
    assert "map_stations" in line
    assert "<details>" in line


def test_format_tool_line_shows_generic_tool_parameters():
    from serve import _format_tool_line

    line = _format_tool_line("get_zone_info", {"zone_name": "Baie de Baffin"})

    assert "get_zone_info" in line
    assert "zone_name=`Baie de Baffin`" in line
    assert "<details>" in line
    assert "<summary>🔧 get_zone_info</summary>" in line


def test_format_tool_line_shows_nested_ecotaxa_filters():
    from serve import _format_tool_line

    line = _format_tool_line(
        "find_ecotaxa_samples_in_region",
        {
            "zone_name": "Baie de Baffin",
            "instrument": "Loki",
            "date_range": {"from": "2024-01-01", "to": "2024-12-31"},
        },
    )

    assert "find_ecotaxa_samples_in_region" in line
    assert "zone_name=`Baie de Baffin`" in line
    assert "instrument=`Loki`" in line
    assert 'date_range=`{"from": "2024-01-01", "to": "2024-12-31"}`' in line


def test_format_tool_line_omits_large_and_secret_parameters():
    from serve import _format_tool_line

    line = _format_tool_line(
        "find_ecotaxa_samples_in_region",
        {
            "zone_name": "Baie de Baffin",
            "polygon_wkt": "POLYGON((" + "0 0," * 1000 + "0 0))",
            "api_token": "secret-token",
        },
    )

    assert "zone_name=`Baie de Baffin`" in line
    assert "polygon_wkt" not in line
    assert "secret-token" not in line
    assert "api_token=`[secret]`" in line


def test_format_tool_line_query_ecotaxa_shows_waiting_message():
    """query_ecotaxa → affiche le projet et un indicateur d'attente sans faux pourcentage."""
    from serve import _format_tool_line

    line = _format_tool_line(
        "query_ecotaxa",
        {"project_id": 14622, "sample_ids": [14622000001, 14622000002], "status": "V"},
    )

    assert "query_ecotaxa" in line
    assert "<summary>🔧 query_ecotaxa</summary>" in line
    assert "project_id=`14622`" in line
    assert "sample_ids=`[14622000001, 14622000002]`" in line
    assert "status=`V`" in line
    assert "Export EcoTaxa en cours" in line
    assert "%" not in line


def test_format_tool_line_query_ecotaxa_sample_shows_waiting_message():
    """query_ecotaxa_sample → affiche le sample et un indicateur d'attente."""
    from serve import _format_tool_line

    line = _format_tool_line(
        "query_ecotaxa_sample",
        {"sample_id": 42000002, "status": "V"},
    )

    assert "query_ecotaxa_sample" in line
    assert "<summary>🔧 query_ecotaxa_sample</summary>" in line
    assert "sample_id=`42000002`" in line
    assert "status=`V`" in line
    assert "Export EcoTaxa sample en cours" in line
    assert "%" not in line


def test_format_tool_line_query_ecopart_shows_waiting_message():
    """query_ecopart → affiche un indicateur d'attente lisible."""
    from serve import _format_tool_line

    line = _format_tool_line(
        "query_ecopart",
        {"project_id": 105},
    )

    assert "query_ecopart" in line
    assert "<summary>🔧 query_ecopart</summary>" in line
    assert "project_id=`105`" in line
    assert "Téléchargement EcoPart" in line
    assert "%" not in line


def test_format_tool_line_query_bio_oracle_shows_waiting_message():
    """query_bio_oracle → affiche un indicateur d'attente sans faux pourcentage."""
    from serve import _format_tool_line

    line = _format_tool_line(
        "query_bio_oracle",
        {"scenario": "SSP245", "depth_layer": "depthsurf", "variable": "temperature"},
    )

    assert "query_bio_oracle" in line
    assert "<summary>🔧 query_bio_oracle</summary>" in line
    assert "scenario=`SSP245`" in line
    assert "depth_layer=`depthsurf`" in line
    assert "variable=`temperature`" in line
    assert "Export Bio-ORACLE en cours" in line
    assert "%" not in line


def test_format_tool_line_query_amundsen_shows_waiting_message():
    """query_amundsen_ctd → affiche un indicateur d'attente sans faux pourcentage."""
    from serve import _format_tool_line

    line = _format_tool_line(
        "query_amundsen_ctd",
        {"station": "BRK-15", "cast_number": 7},
    )

    assert "query_amundsen_ctd" in line
    assert "<summary>🔧 query_amundsen_ctd</summary>" in line
    assert "station=`BRK-15`" in line
    assert "cast_number=`7`" in line
    assert "Export Amundsen CTD en cours" in line
    assert "%" not in line


def test_format_tool_line_enrich_with_bio_oracle_shows_progress_panel():
    """Les enrichissements affichent un panneau de progression explicite."""
    from serve import _format_tool_line

    line = _format_tool_line(
        "enrich_with_bio_oracle",
        {"scenario": "SSP245", "depth_layer": "depthsurf", "variable": "temperature"},
    )

    assert "enrich_with_bio_oracle" in line
    assert "<summary>🔧 enrich_with_bio_oracle</summary>" in line
    assert "Préparation de l'enrichissement Bio-ORACLE" in line
    assert "Le cache de données sera vérifié automatiquement" in line
    assert "%" not in line


def test_render_progress_bar_is_visual():
    from serve import _render_progress_bar

    bar = _render_progress_bar(50)
    assert "█" in bar
    assert "░" in bar
    assert bar.endswith("50%")


def test_sql_workspace_config_message_matches_raw_url_and_key_value_forms():
    from serve import _is_sql_workspace_config_message

    url = "sqlite:////tmp/source.sqlite"

    assert _is_sql_workspace_config_message(url, url)
    assert _is_sql_workspace_config_message(f"DATABASE_URL={url}", url)
    assert _is_sql_workspace_config_message(f"sql_database_url={url}", url)
    assert not _is_sql_workspace_config_message("analyse-moi ça", url)


def test_prepare_user_content_preserves_image_url_parts():
    from serve import Message, _prepare_user_content

    message = Message(
        role="user",
        content=[
            {"type": "text", "text": "Que vois-tu ?"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
        ],
    )

    prepared = _prepare_user_content(message)

    assert isinstance(prepared, list)
    assert prepared[0]["type"] == "text"
    assert prepared[0]["text"] == "Que vois-tu ?"
    assert prepared[1]["type"] == "image_url"
    assert prepared[1]["image_url"]["url"].startswith("data:image/png;base64,")


# ── streaming async ────────────────────────────────────────────────────────────

def _make_mock_agent(updates: list):
    """Renvoie un agent mock dont .astream() yield les updates donnés."""
    mock = MagicMock()

    async def _astream(*args, **kwargs):
        for u in updates:
            yield u

    mock.astream = _astream
    return mock


@pytest.mark.asyncio
async def test_stream_tool_call_then_final_response():
    """Le stream émet 🔧 nom_outil puis la réponse finale."""
    from serve import _stream_agent_sse

    updates = [
        {"agent": {"messages": [AIMessage(
            content="Je vais charger le fichier.",
            tool_calls=[{"name": "load_file", "args": {"path": "/tmp/x.tsv"}, "id": "tc1", "type": "tool_call"}],
        )]}},
        {"tools": {"messages": [ToolMessage(content="Fichier chargé", tool_call_id="tc1")]}},
        {"agent": {"messages": [AIMessage(content="Voici les données.", tool_calls=[])]}},
    ]

    agent = _make_mock_agent(updates)
    chunks = [c async for c in _stream_agent_sse(agent, {}, {}, "tid-test")]
    full = "".join(chunks)

    assert "🔧" in full
    assert "load_file" in full
    assert "Voici les données." in full


@pytest.mark.asyncio
async def test_stream_ends_with_done():
    from serve import _stream_agent_sse

    updates = [
        {"agent": {"messages": [AIMessage(content="Réponse simple.", tool_calls=[])]}},
    ]
    agent = _make_mock_agent(updates)
    chunks = [c async for c in _stream_agent_sse(agent, {}, {}, "tid-test")]

    assert chunks[-1] == "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_stream_multiple_tool_calls():
    """Deux tool calls consécutifs apparaissent dans l'ordre."""
    from serve import _stream_agent_sse

    updates = [
        {"agent": {"messages": [AIMessage(
            content="",
            tool_calls=[
                {"name": "load_file", "args": {}, "id": "tc1", "type": "tool_call"},
                {"name": "run_graph", "args": {}, "id": "tc2", "type": "tool_call"},
            ],
        )]}},
        {"tools": {"messages": [
            ToolMessage(content="ok", tool_call_id="tc1"),
            ToolMessage(content="ok", tool_call_id="tc2"),
        ]}},
        {"agent": {"messages": [AIMessage(content="Voilà.", tool_calls=[])]}},
    ]
    agent = _make_mock_agent(updates)
    chunks = [c async for c in _stream_agent_sse(agent, {}, {}, "tid-test")]
    full = "".join(chunks)

    idx_load = full.index("load_file")
    idx_graph = full.index("run_graph")
    assert idx_load < idx_graph


@pytest.mark.asyncio
async def test_stream_image_in_agent_response_replaced():
    """Le base64 dans la réponse finale de l'agent est remplacé par une URL /graphs/."""
    from serve import _stream_agent_sse
    import base64

    tiny_png = base64.b64encode(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
        b"\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18"
        b"\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    ).decode()

    content_with_image = f"Voici la carte.\n\n![carte](data:image/png;base64,{tiny_png})"
    updates = [
        {"agent": {"messages": [AIMessage(content=content_with_image, tool_calls=[])]}},
    ]
    agent = _make_mock_agent(updates)
    chunks = [c async for c in _stream_agent_sse(agent, {}, {}, "tid-test")]
    full = "".join(chunks)

    assert "data:image/png;base64," not in full
    assert "/graphs/" in full


@pytest.mark.asyncio
async def test_stream_image_in_tool_result_replaced():
    """Le base64 dans le résultat d'un outil est extrait et hébergé."""
    from serve import _stream_agent_sse
    import base64

    tiny_png = base64.b64encode(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
        b"\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18"
        b"\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    ).decode()

    tool_content = f"![graph](data:image/png;base64,{tiny_png})"
    updates = [
        {"agent": {"messages": [AIMessage(
            content="",
            tool_calls=[{"name": "run_graph", "args": {}, "id": "tc1", "type": "tool_call"}],
        )]}},
        {"tools": {"messages": [ToolMessage(content=tool_content, tool_call_id="tc1")]}},
        {"agent": {"messages": [AIMessage(content="Voici la carte.", tool_calls=[])]}},
    ]
    agent = _make_mock_agent(updates)
    chunks = [c async for c in _stream_agent_sse(agent, {}, {}, "tid-test")]
    full = "".join(chunks)

    assert "data:image/png;base64," not in full
    assert "/graphs/" in full


@pytest.mark.asyncio
async def test_stream_emits_visual_progress_bar_for_slow_tool(monkeypatch):
    """Un tool lent déclenche une barre visuelle avant son résultat final."""
    from serve import _stream_agent_sse

    monkeypatch.setattr("serve._HEARTBEAT_INTERVAL", 0.01)

    async def _astream(*args, **kwargs):
        yield {
            "agent": {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "enrich_with_bio_oracle",
                                "args": {"scenario": "SSP245", "depth_layer": "surface"},
                                "id": "tc1",
                                "type": "tool_call",
                            }
                        ],
                    )
                ]
            }
        }
        await asyncio.sleep(0.03)
        yield {"tools": {"messages": [ToolMessage(content="Résultat enrichi", tool_call_id="tc1")]}}
        yield {"agent": {"messages": [AIMessage(content="Terminé.", tool_calls=[])]}}

    agent = MagicMock()
    agent.astream = _astream

    chunks = [c async for c in _stream_agent_sse(agent, {}, {}, "tid-test")]
    full = "".join(chunks)

    assert "enrich_with_bio_oracle" in full
    assert "████" in full or "░" in full
    assert "100%" in full


@pytest.mark.asyncio
async def test_stream_run_graph_url_tool_result_is_printed():
    """run_graph retourne déjà une URL /graphs ; le stream doit l'afficher sans
    dépendre de la réponse finale de l'agent."""
    from serve import _stream_agent_sse

    tool_content = (
        "![graph](https://example.test/graphs/abc123.png)\n\n"
        "Lecture rapide:\nCarte générée."
    )
    updates = [
        {"agent": {"messages": [AIMessage(
            content="",
            tool_calls=[{"name": "run_graph", "args": {}, "id": "tc1", "type": "tool_call"}],
        )]}},
        {"tools": {"messages": [ToolMessage(content=tool_content, tool_call_id="tc1")]}},
        {"agent": {"messages": [AIMessage(content="Voici la carte.", tool_calls=[])]}},
    ]
    agent = _make_mock_agent(updates)
    chunks = [c async for c in _stream_agent_sse(agent, {}, {}, "tid-test")]
    full = "".join(chunks)

    assert "![graph](https://example.test/graphs/abc123.png)" in full
    assert "Lecture rapide:" in full
    assert "Voici la carte." in full


@pytest.mark.asyncio
async def test_stream_deduplicates_run_graph_image_when_final_repeats_it():
    """If run_graph streams an image and the final AI message repeats it,
    the SSE stream should contain one image, not two."""
    from serve import _stream_agent_sse

    image = "![graph](https://example.test/graphs/abc123.png)"
    tool_content = f"{image}\n\nLecture rapide:\nCarte générée."
    final_content = f"{image}\n\nCarte des stations."
    updates = [
        {"agent": {"messages": [AIMessage(
            content="",
            tool_calls=[{"name": "run_graph", "args": {}, "id": "tc1", "type": "tool_call"}],
        )]}},
        {"tools": {"messages": [ToolMessage(content=tool_content, tool_call_id="tc1")]}},
        {"agent": {"messages": [AIMessage(content=final_content, tool_calls=[])]}},
    ]
    agent = _make_mock_agent(updates)
    chunks = [c async for c in _stream_agent_sse(agent, {}, {}, "tid-test")]
    full = "".join(chunks)

    assert full.count(image) == 1
    assert "Carte des stations." in full
