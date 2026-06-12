"""TDD — tools/ecopart_sources.py."""


def test_make_ecopart_tools_exposes_expected_tools():
    from tools.ecopart_sources import make_ecopart_tools

    tools = make_ecopart_tools("thread-1")
    tool_names = {t.name for t in tools}

    assert "list_ecopart_samples" in tool_names
    assert "preview_ecopart_sample" in tool_names
    assert "query_ecopart" in tool_names


def test_list_ecopart_samples_returns_markdown_table():
    from unittest.mock import MagicMock, patch

    from tools.ecopart_sources import make_ecopart_tools

    fake_samples = [
        {"id": 1, "name": "ips_007", "visibility": "P"},
        {"id": 2, "name": "ips_008", "visibility": "P"},
    ]
    mock_client = MagicMock()
    mock_client.list_samples.return_value = fake_samples

    with patch("tools.ecopart_sources.EcopartClient", return_value=mock_client):
        tools = make_ecopart_tools("thread-list")
        list_tool = next(t for t in tools if t.name == "list_ecopart_samples")
        result = list_tool.invoke({"project_id": 105})

    mock_client.login.assert_called_once()
    mock_client.list_samples.assert_called_once_with(105)
    assert "ips_007" in result
    assert "ips_008" in result


def test_preview_ecopart_sample_returns_text():
    from unittest.mock import MagicMock, patch

    from tools.ecopart_sources import make_ecopart_tools

    mock_client = MagicMock()
    mock_client.preview_sample.return_value = {
        "sample_id": 42,
        "accessible": True,
        "text": "Station ips_007 — 120 profils CTD",
    }

    with patch("tools.ecopart_sources.EcopartClient", return_value=mock_client):
        tools = make_ecopart_tools("thread-preview")
        preview_tool = next(t for t in tools if t.name == "preview_ecopart_sample")
        result = preview_tool.invoke({"sample_id": 42})

    mock_client.login.assert_called_once()
    mock_client.preview_sample.assert_called_once_with(42)
    assert "ips_007" in result
    assert "120 profils" in result


def test_preview_ecopart_sample_inaccessible():
    from unittest.mock import MagicMock, patch

    from tools.ecopart_sources import make_ecopart_tools

    mock_client = MagicMock()
    mock_client.preview_sample.return_value = {"sample_id": 99, "accessible": False, "text": ""}

    with patch("tools.ecopart_sources.EcopartClient", return_value=mock_client):
        tools = make_ecopart_tools("thread-preview-na")
        preview_tool = next(t for t in tools if t.name == "preview_ecopart_sample")
        result = preview_tool.invoke({"sample_id": 99})

    assert "99" in result
    assert "non accessible" in result


def test_query_ecopart_stores_dataframe_and_returns_download_link():
    import pandas as pd
    from unittest.mock import MagicMock, patch

    from tools.ecopart_sources import make_ecopart_tools
    from tools.session_store import default_store as _store

    _store._store.clear()

    fake_df = pd.DataFrame(
        [
            {
                "Profile": "ips_007",
                "Depth [m]": 10.0,
                "Sampled volume [L]": 5.3,
                "temperature": -1.1,
                "practical_salinity": 31.2,
            }
        ]
    )
    mock_client = MagicMock()
    mock_client.start_export.return_value = ["https://ecopart.obs-vlfr.fr/download/export.zip"]
    mock_client.download_tsv.return_value = fake_df

    with patch("tools.ecopart_sources.EcopartClient", return_value=mock_client):
        tools = make_ecopart_tools("thread-query")
        query_tool = next(t for t in tools if t.name == "query_ecopart")
        result = query_tool.invoke({"project_id": 105})

    mock_client.login.assert_called_once()
    mock_client.start_export.assert_called_once_with(105, None, None)
    mock_client.download_tsv.assert_called_once()

    assert _store.has("thread-query")
    assert "EcoPart chargé" in result
    assert "Télécharger :" in result
    assert "run_pandas" in result


def test_query_ecopart_also_stores_named_slot_for_join():
    import pandas as pd
    from unittest.mock import MagicMock, patch

    from tools.ecopart_sources import make_ecopart_tools
    from tools.session_store import default_store as _store

    _store._store.clear()

    fake_df = pd.DataFrame({"Profile": ["ips_007"], "Depth [m]": [10.0]})
    mock_client = MagicMock()
    mock_client.start_export.return_value = ["https://ecopart.obs-vlfr.fr/download/x.zip"]
    mock_client.download_tsv.return_value = fake_df

    with patch("tools.ecopart_sources.EcopartClient", return_value=mock_client):
        tools = make_ecopart_tools("thread-join-ep")
        query_tool = next(t for t in tools if t.name == "query_ecopart")
        query_tool.invoke({"project_id": 105})

    assert _store.has("thread-join-ep:ecopart")
    assert _store.get("thread-join-ep:ecopart")["df"].shape == (1, 2)


def test_query_ecopart_preserves_multiple_projects_and_latest_alias():
    import pandas as pd
    from unittest.mock import MagicMock, patch

    from tools.ecopart_sources import make_ecopart_tools
    from tools.session_store import default_store as _store

    thread_id = "thread-multi-ecopart"
    keys = [
        thread_id,
        f"{thread_id}:ecopart",
        f"{thread_id}:ecopart:105",
        f"{thread_id}:ecopart:42",
    ]
    for key in keys:
        _store.clear(key)

    df_105 = pd.DataFrame({"Profile": ["ips_105"], "project_value": [105]})
    df_42 = pd.DataFrame({"Profile": ["ips_042"], "project_value": [42]})
    mock_client = MagicMock()
    mock_client.start_export.side_effect = [["task-105"], ["task-42"]]
    mock_client.download_tsv.side_effect = [df_105, df_42]

    with patch("tools.ecopart_sources.EcopartClient", return_value=mock_client):
        query_tool = next(
            tool for tool in make_ecopart_tools(thread_id) if tool.name == "query_ecopart"
        )
        result_105 = query_tool.invoke({"project_id": 105})
        result_42 = query_tool.invoke({"project_id": 42})

    assert _store.get(f"{thread_id}:ecopart:105")["df"].equals(df_105)
    assert _store.get(f"{thread_id}:ecopart:42")["df"].equals(df_42)
    assert _store.get(f"{thread_id}:ecopart")["df"].equals(df_42)
    assert _store.get(thread_id)["df"].equals(df_42)
    assert "df_ecopart_105" in result_105
    assert "df_ecopart" in result_105
    assert "df_ecopart_42" in result_42

    for key in keys:
        _store.clear(key)


def test_make_ecopart_tools_includes_join_tool():
    from tools.ecopart_sources import make_ecopart_tools

    tools = make_ecopart_tools("thread-join-check")
    tool_names = {t.name for t in tools}

    assert "join_ecotaxa_ecopart" in tool_names


def test_join_ecotaxa_ecopart_produces_merged_dataframe():
    import pandas as pd
    from tools.ecopart_sources import make_ecopart_tools
    from tools.session_store import default_store as _store

    _store._store.clear()

    df_ecotaxa = pd.DataFrame({
        "obj_orig_id": ["ips_007_1", "ips_007_2", "ips_008_1"],
        "object_major": [12.5, 8.3, 5.0],
        "taxon": ["Calanus", "Calanus", "Oithona"],
    })
    df_ecopart = pd.DataFrame({
        "Profile": ["ips_007", "ips_008"],
        "Depth [m]": [10.0, 25.0],
        "temperature": [-1.1, -0.8],
    })
    _store.set("thread-join:ecotaxa", df_ecotaxa, {"source": "ecotaxa:1165"})
    _store.set("thread-join:ecopart", df_ecopart, {"source": "ecopart:105"})

    tools = make_ecopart_tools("thread-join")
    join_tool = next(t for t in tools if t.name == "join_ecotaxa_ecopart")
    result = join_tool.invoke({})

    assert _store.has("thread-join")
    merged = _store.get("thread-join")["df"]
    assert "obj_orig_id" in merged.columns
    assert "temperature" in merged.columns
    assert len(merged) == 3
    assert "3 lignes" in result


def test_join_ecotaxa_ecopart_missing_source_returns_error():
    from tools.ecopart_sources import make_ecopart_tools
    from tools.session_store import default_store as _store

    _store._store.clear()

    tools = make_ecopart_tools("thread-join-missing")
    join_tool = next(t for t in tools if t.name == "join_ecotaxa_ecopart")
    result = join_tool.invoke({})

    assert "query_ecotaxa" in result
    assert "query_ecopart" in result
