"""TDD — tools/ecopart_sources.py."""

import pytest

from tools.session_store import SessionStore


@pytest.fixture(autouse=True)
def _isolated_store(monkeypatch):
    """Force a fresh in-memory SessionStore so tests are backend-agnostic.

    The tools bind their store via the module global ``tools.ecopart_sources._store``
    (imported from ``default_store``). Patching both that global and
    ``tools.session_store.default_store`` keeps tool writes and test reads on the
    same in-memory store, independent of ``SESSION_STORE_DATABASE_URL`` (which would
    otherwise swap in ``SessionStorePG``, breaking ``_store._store.clear()``).
    """
    store = SessionStore()
    monkeypatch.setattr("tools.session_store.default_store", store)
    monkeypatch.setattr("tools.ecopart_sources._store", store)
    # copepod_sources (query_ecotaxa) binds its own module-global store; share the
    # same instance so the full-remote chain (query_ecotaxa → enrich) is coherent.
    monkeypatch.setattr("tools.copepod_sources._store", store)
    return store


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
    assert "enrich_ecotaxa_with_ecopart_remote" in tool_names


def test_enrich_remote_errors_without_ecotaxa_and_without_project_id():
    """With no EcoTaxa in session AND no project id to auto-load, enrich still
    errors (the guard only auto-loads when a project id is provided)."""
    from tools.ecopart_sources import make_ecopart_tools
    from tools.session_store import default_store as _store

    _store._store.clear()
    for key in ("thread-remote-no-et", "thread-remote-no-et:ecotaxa"):
        _store.clear(key)  # also drop any on-disk session for this thread

    tool = next(
        t for t in make_ecopart_tools("thread-remote-no-et")
        if t.name == "enrich_ecotaxa_with_ecopart_remote"
    )
    result = tool.invoke({})  # no ecotaxa_project_id -> nothing to auto-load
    assert "Données EcoTaxa manquantes" in result


def test_enrich_remote_errors_when_no_project_id_resolvable():
    import pandas as pd
    from tools.ecopart_sources import make_ecopart_tools
    from tools.session_store import default_store as _store

    _store._store.clear()

    _store.set(
        "thread-remote-no-pid:ecotaxa",
        pd.DataFrame({"obj_orig_id": ["ips_007_1"], "object_depth_min": [3.0]}),
        {"source": "file:foo.tsv"},  # no project_id in meta
    )

    tool = next(
        t for t in make_ecopart_tools("thread-remote-no-pid")
        if t.name == "enrich_ecotaxa_with_ecopart_remote"
    )
    result = tool.invoke({})
    assert "impossible" in result and "ecotaxa_project_id" in result


def test_enrich_remote_uses_session_project_id_when_query_ecotaxa_was_run():
    from unittest.mock import MagicMock, patch

    import pandas as pd
    from tools.ecopart_sources import make_ecopart_tools
    from tools.session_store import default_store as _store

    _store._store.clear()

    _store.set(
        "thread-remote-meta:ecotaxa",
        pd.DataFrame({
            "obj_orig_id": ["ips_007_1"],
            "object_depth_min": [3.0],
        }),
        {"source": "ecotaxa:1165", "project_id": 1165},
    )

    mock_client = MagicMock()
    mock_client.start_export.return_value = ["/Task/Show/42"]
    mock_client.download_tsv.return_value = pd.DataFrame({
        "Profile": ["ips_007"],
        "Depth [m]": [2.5],
        "Sampled volume [L]": [100.0],
    })

    with patch("tools.ecopart_sources.EcopartClient", return_value=mock_client):
        tool = next(
            t for t in make_ecopart_tools("thread-remote-meta")
            if t.name == "enrich_ecotaxa_with_ecopart_remote"
        )
        result = tool.invoke({})

    mock_client.start_export.assert_called_once_with(
        project_id=None, ecotaxa_project_id=1165
    )
    assert "Enrichissement terminé" in result
    merged = _store.get("thread-remote-meta")["df"]
    assert merged.loc[0, "ecopart_Sampled volume [L]"] == 100.0


def test_enrich_remote_auto_loads_ecotaxa_when_project_named_but_not_in_session():
    """Guard: enrich called with an ecotaxa_project_id but no EcoTaxa in session
    (query_ecotaxa skipped) must auto-load the project instead of failing."""
    from unittest.mock import MagicMock, patch

    import pandas as pd
    from tools.ecopart_sources import make_ecopart_tools
    from tools.session_store import default_store as _store

    _store._store.clear()  # NO EcoTaxa preloaded
    # get() falls back to on-disk sessions, so also purge this thread's disk state.
    for key in ("thread-autoload", "thread-autoload:ecotaxa"):
        _store.clear(key)

    mock_et = MagicMock()
    mock_et.start_export.return_value = "job-1"
    mock_et.download_tsv.return_value = pd.DataFrame(
        {"obj_orig_id": ["ips_007_1"], "object_depth_min": [3.0]}
    )

    mock_ep = MagicMock()
    mock_ep.start_export.return_value = ["/Task/Show/7"]
    mock_ep.download_tsv.return_value = pd.DataFrame({
        "Profile": ["ips_007"],
        "Depth [m]": [2.5],
        "Sampled volume [L]": [100.0],
    })

    with patch("tools.ecopart_sources.EcotaxaClient", return_value=mock_et), \
         patch("tools.ecopart_sources.EcopartClient", return_value=mock_ep):
        tool = next(
            t for t in make_ecopart_tools("thread-autoload")
            if t.name == "enrich_ecotaxa_with_ecopart_remote"
        )
        result = tool.invoke({"ecotaxa_project_id": 14853})

    mock_et.start_export.assert_called_once()  # auto-loaded the EcoTaxa project
    assert "Données EcoTaxa manquantes" not in result
    assert "Enrichissement terminé" in result
    assert _store.get("thread-autoload:ecotaxa") is not None


def test_full_remote_workflow_query_ecotaxa_then_enrich_remote():
    """Integration — Workflow 3 (full remote): real query_ecotaxa → real enrich_remote.

    No local file, no hand-built session: query_ecotaxa downloads EcoTaxa and is the
    only thing that leaves `:ecotaxa` + `meta.project_id` in session. The remote enrich
    must then reuse that project_id with no args and produce a matched join. This locks
    the contract (session key + meta) between the two tools.
    """
    from unittest.mock import MagicMock, patch

    import pandas as pd
    from tools.copepod_sources import make_source_tools
    from tools.ecopart_sources import make_ecopart_tools
    from tools.session_store import default_store as _store

    thread_id = "thread-full-remote"

    # --- Step 1: real query_ecotaxa (EcoTaxa client mocked at the HTTP boundary) ---
    ecotaxa_client = MagicMock()
    ecotaxa_client.start_export.return_value = "job-1"
    ecotaxa_client.download_tsv.return_value = pd.DataFrame({
        "obj_orig_id": ["ips_007_1", "ips_007_2"],
        "object_depth_min": [3.0, 7.0],
        "taxon": ["Calanus", "Calanus"],
    })

    with patch("tools.copepod_sources.EcotaxaClient", return_value=ecotaxa_client):
        query_ecotaxa = next(
            t for t in make_source_tools(thread_id) if t.name == "query_ecotaxa"
        )
        et_result = query_ecotaxa.invoke({"project_id": 1165})

    # query_ecotaxa is the sole writer of the session here.
    assert "chargé" in et_result
    session_et = _store.get(f"{thread_id}:ecotaxa")
    assert session_et is not None
    assert session_et["meta"]["project_id"] == 1165

    # --- Step 2: real enrich_ecotaxa_with_ecopart_remote, no args ---
    ecopart_client = MagicMock()
    ecopart_client.start_export.return_value = ["/Task/Show/42"]
    ecopart_client.download_tsv.return_value = pd.DataFrame({
        "Profile": ["ips_007", "ips_007"],
        "Depth [m]": [2.5, 7.5],
        "Sampled volume [L]": [100.0, 110.0],
    })

    with patch("tools.ecopart_sources.EcopartClient", return_value=ecopart_client):
        enrich = next(
            t for t in make_ecopart_tools(thread_id)
            if t.name == "enrich_ecotaxa_with_ecopart_remote"
        )
        result = enrich.invoke({})

    # The remote enrich reused the project_id left by query_ecotaxa, with no manual id.
    ecopart_client.start_export.assert_called_once_with(
        project_id=None, ecotaxa_project_id=1165
    )
    assert "Enrichissement terminé" in result

    merged = _store.get(f"{thread_id}:ecotaxa_ecopart")["df"]
    by_obj = merged.set_index("obj_orig_id")
    assert by_obj.loc["ips_007_1", "ecopart_Sampled volume [L]"] == 100.0
    assert by_obj.loc["ips_007_2", "ecopart_Sampled volume [L]"] == 110.0


def test_enrich_remote_surfaces_clean_message_on_server_export_error():
    from unittest.mock import MagicMock, patch

    import pandas as pd
    from core.ecopart_client import EcopartExportError
    from tools.ecopart_sources import make_ecopart_tools
    from tools.session_store import default_store as _store

    _store._store.clear()

    _store.set(
        "thread-remote-err:ecotaxa",
        pd.DataFrame({
            "obj_orig_id": ["ips_007_1"],
            "object_depth_min": [3.0],
        }),
        {"source": "ecotaxa:1165", "project_id": 1165},
    )

    mock_client = MagicMock()
    mock_client.start_export.side_effect = EcopartExportError(
        kind="empty_sample_set",
        message=(
            "Le serveur EcoPart a refusé l'export : aucun sample exportable pour ce projet "
            "(typiquement un projet récent dont les particules ne sont pas encore validées, "
            "statut « VN »)."
        ),
        task_id=60808,
    )

    with patch("tools.ecopart_sources.EcopartClient", return_value=mock_client):
        tool = next(
            t for t in make_ecopart_tools("thread-remote-err")
            if t.name == "enrich_ecotaxa_with_ecopart_remote"
        )
        result = tool.invoke({})

    assert "Export EcoPart échoué" in result
    assert "60808" in result
    assert "VN" in result
    # No giant HTML dump expected
    assert "psycopg2" not in result
    assert len(result) < 800


def test_enrich_remote_accepts_explicit_ecopart_project_id():
    from unittest.mock import MagicMock, patch

    import pandas as pd
    from tools.ecopart_sources import make_ecopart_tools
    from tools.session_store import default_store as _store

    _store._store.clear()

    _store.set(
        "thread-remote-ep:ecotaxa",
        pd.DataFrame({
            "obj_orig_id": ["ips_007_1"],
            "object_depth_min": [3.0],
        }),
        {"source": "file:foo.tsv"},
    )

    mock_client = MagicMock()
    mock_client.start_export.return_value = ["/Task/Show/99"]
    mock_client.download_tsv.return_value = pd.DataFrame({
        "Profile": ["ips_007"],
        "Depth [m]": [2.5],
        "Sampled volume [L]": [222.0],
    })

    with patch("tools.ecopart_sources.EcopartClient", return_value=mock_client):
        tool = next(
            t for t in make_ecopart_tools("thread-remote-ep")
            if t.name == "enrich_ecotaxa_with_ecopart_remote"
        )
        result = tool.invoke({"ecopart_project_id": 105})

    mock_client.start_export.assert_called_once_with(
        project_id=105, ecotaxa_project_id=None
    )
    assert "EcoPart téléchargé" in result
    merged = _store.get("thread-remote-ep")["df"]
    assert merged.loc[0, "ecopart_Sampled volume [L]"] == 222.0


def test_enrich_remote_uses_sample_lat_long_for_standard_ecotaxa_export():
    from unittest.mock import MagicMock, patch

    import pandas as pd
    from tools.ecopart_sources import make_ecopart_tools
    from tools.session_store import default_store as _store

    _store._store.clear()

    _store.set(
        "thread-remote-sample-coords:ecotaxa",
        pd.DataFrame({
            "sample_id": ["ips_007_1"],
            "sample_lat": [48.5],
            "sample_long": [-68.1],
            "object_depth_min": [3.0],
        }),
        {"source": "file:ecotaxa_sample_50.tsv"},
    )

    mock_client = MagicMock()
    mock_client.search_samples_by_bbox.return_value = [
        {"id": 11, "lat": 48.5, "lon": -68.1},
    ]
    mock_client.get_sample_metadata.return_value = {
        "profile_id": "ips_007",
        "ecopart_project_id": 105,
    }
    mock_client.start_export.return_value = ["/Task/Show/101"]
    mock_client.download_tsv.return_value = pd.DataFrame({
        "Profile": ["ips_007"],
        "Depth [m]": [2.5],
        "Sampled volume [L]": [111.0],
    })

    with patch("tools.ecopart_sources.EcopartClient", return_value=mock_client):
        tool = next(
            t for t in make_ecopart_tools("thread-remote-sample-coords")
            if t.name == "enrich_ecotaxa_with_ecopart_remote"
        )
        result = tool.invoke({})

    assert (
        "Projet EcoPart résolu automatiquement" in result
        or "Projet EcoPart résolu par fallback géographique" in result
    )
    assert "Enrichissement terminé" in result
    assert _store.get("thread-remote-sample-coords")["df"].shape[0] == 1


def test_enrich_remote_uses_sample_profileid_when_no_coordinates_are_available():
    from unittest.mock import MagicMock, patch

    import pandas as pd
    from tools.ecopart_sources import make_ecopart_tools
    from tools.session_store import default_store as _store

    _store._store.clear()

    _store.set(
        "thread-remote-profile-fallback:ecotaxa",
        pd.DataFrame({
            "sample_id": ["20130815 104200 655"],
            "sample_profileid": ["1.0"],
            "sample_stationid": ["101"],
            "sample_cruise": ["ArcticNet2013"],
            "object_depth_min": [3.0],
        }),
        {"source": "file:ecotaxa_sample_50.tsv"},
    )

    mock_client = MagicMock()
    mock_client.search_samples.return_value = [{"id": 11, "name": "1.0", "visibility": "YY"}]
    mock_client.get_sample_metadata.return_value = {
        "profile_id": "1.0",
        "ecopart_project_id": 105,
    }
    mock_client.start_export.return_value = ["/Task/Show/101"]
    mock_client.download_tsv.return_value = pd.DataFrame({
        "Profile": ["1.0"],
        "Depth [m]": [2.5],
        "Sampled volume [L]": [111.0],
    })

    with patch("tools.ecopart_sources.EcopartClient", return_value=mock_client):
        tool = next(
            t for t in make_ecopart_tools("thread-remote-profile-fallback")
            if t.name == "enrich_ecotaxa_with_ecopart_remote"
        )
        result = tool.invoke({})

    assert "Projet EcoPart résolu automatiquement" in result
    assert "105" in result and "profil" in result
    assert "Enrichissement terminé" in result


def test_lookup_ecopart_project_prefers_ecotaxa_link_and_is_deterministic():
    """Two EcoPart projects share the bbox; the one linked to the known EcoTaxa
    project must win even if it has fewer samples, and the choice must be stable
    regardless of the order the server returns candidates in (the 59/105 flip)."""
    from unittest.mock import MagicMock, patch

    import pandas as pd
    from tools.ecopart_sources import _lookup_ecopart_project_for_ecotaxa

    df_et = pd.DataFrame({
        "object_lat": [72.69, 73.79],
        "object_lon": [-70.10, -66.83],
        "sample_id": ["14853000003", "14853000002"],
    })

    # id 1 & 3 -> EcoPart 59 (unrelated, statut VN); id 2 -> EcoPart 105 linked
    # to EcoTaxa 14853. Project 59 has the majority of bbox candidates.
    meta = {
        1: {"profile_id": "ips_007", "ecopart_project_id": 59, "ecotaxa_project_id": 999},
        2: {"profile_id": "am_leg5_TCA_T3_09_02", "ecopart_project_id": 105, "ecotaxa_project_id": 14853},
        3: {"profile_id": "ips_008", "ecopart_project_id": 59, "ecotaxa_project_id": 999},
    }
    base = [
        {"id": 1, "lat": 72.6, "lon": -70.0},
        {"id": 2, "lat": 73.7, "lon": -66.8},
        {"id": 3, "lat": 74.3, "lon": -66.7},
    ]

    import tools.ecopart_sources as es
    for order in (base, list(reversed(base))):
        es._ECOPART_RESOLUTION_CACHE.clear()
        mock_client = MagicMock()
        mock_client.search_samples.return_value = []  # force the bbox fallback path
        mock_client.search_samples_by_bbox.return_value = order
        mock_client.get_sample_metadata.side_effect = lambda sid: meta[sid]
        with patch("tools.ecopart_sources.EcopartClient", return_value=mock_client):
            res = _lookup_ecopart_project_for_ecotaxa(df_et, known_ecotaxa_pid=14853)
        assert res["project_id"] == 105, f"order={order} -> {res}"
        assert "lien EcoTaxa" in res["resolution"]


def test_lookup_ecopart_uses_filt_proj_fast_path_and_caches():
    """When the EcoTaxa project id is known, resolve via the server filt_proj link
    (one search + one popover, no bbox scan) and serve repeats from cache."""
    from unittest.mock import MagicMock, patch

    import pandas as pd
    import tools.ecopart_sources as es

    es._ECOPART_RESOLUTION_CACHE.clear()

    df_et = pd.DataFrame({"object_lat": [72.7], "object_lon": [-70.1]})

    mock_client = MagicMock()
    mock_client.search_samples.return_value = [{"id": 58321, "lat": 60.0, "lon": -69.6}]
    mock_client.get_sample_metadata.return_value = {
        "profile_id": "am_leg5_TCA_BB2_01",
        "ecopart_project_id": 1063,
        "ecopart_project_name": "uvp6_sn000006hf_2024_am_leg5",
        "ecotaxa_project_id": 14853,
    }

    with patch("tools.ecopart_sources.EcopartClient", return_value=mock_client):
        res = es._lookup_ecopart_project_for_ecotaxa(df_et, known_ecotaxa_pid=14853)

    assert res["project_id"] == 1063
    assert "filt_proj" in res["resolution"]
    mock_client.search_samples.assert_called_once_with(ecotaxa_project_id=14853)
    mock_client.search_samples_by_bbox.assert_not_called()  # no bbox scan needed

    # Second call is served from the cache — the client is never instantiated.
    with patch(
        "tools.ecopart_sources.EcopartClient",
        side_effect=AssertionError("resolution should be cached"),
    ):
        res2 = es._lookup_ecopart_project_for_ecotaxa(df_et, known_ecotaxa_pid=14853)
    assert res2["project_id"] == 1063


def test_join_ecotaxa_ecopart_produces_merged_dataframe():
    import math

    import pandas as pd
    from tools.ecopart_sources import make_ecopart_tools
    from tools.session_store import default_store as _store

    _store._store.clear()

    # Objects at depths 3 m, 7 m, 12 m → expected bins 2.5, 7.5, 12.5.
    df_ecotaxa = pd.DataFrame({
        "obj_orig_id": ["ips_007_1", "ips_007_2", "ips_008_1"],
        "object_depth_min": [3.0, 7.0, 12.0],
        "object_major": [12.5, 8.3, 5.0],
        "taxon": ["Calanus", "Calanus", "Oithona"],
    })
    # Two bins per profile; only the matching bins should be picked up.
    df_ecopart = pd.DataFrame({
        "Profile": ["ips_007", "ips_007", "ips_008", "ips_008"],
        "Depth [m]": [2.5, 7.5, 7.5, 12.5],
        "Sampled volume [L]": [100.0, 110.0, 90.0, 95.0],
        "temperature": [-1.1, -1.2, -0.8, -0.9],
    })
    _store.set("thread-join:ecotaxa", df_ecotaxa, {"source": "ecotaxa:1165"})
    _store.set("thread-join:ecopart", df_ecopart, {"source": "ecopart:105"})

    tools = make_ecopart_tools("thread-join")
    join_tool = next(t for t in tools if t.name == "join_ecotaxa_ecopart")
    result = join_tool.invoke({})

    assert _store.has("thread-join")
    merged = _store.get("thread-join")["df"]
    assert "obj_orig_id" in merged.columns
    assert "ecopart_temperature" in merged.columns
    assert "ecopart_Sampled volume [L]" in merged.columns
    assert "_join_sample_id" not in merged.columns
    assert "_join_depth_bin" not in merged.columns
    # The 5 m bin used for the join is kept as a first-class column for m5/m6 grouping.
    assert "depth_bin" in merged.columns
    assert len(merged) == 3

    by_obj = merged.set_index("obj_orig_id")
    assert by_obj.loc["ips_007_1", "ecopart_Sampled volume [L]"] == 100.0
    assert by_obj.loc["ips_007_2", "ecopart_Sampled volume [L]"] == 110.0
    assert by_obj.loc["ips_008_1", "ecopart_Sampled volume [L]"] == 95.0
    assert by_obj.loc["ips_007_1", "ecopart_temperature"] == -1.1
    assert by_obj.loc["ips_007_2", "ecopart_temperature"] == -1.2
    # depth_bin = (depth // 5) * 5 + 2.5 → 3 m, 7 m, 12 m map to 2.5, 7.5, 12.5.
    assert by_obj.loc["ips_007_1", "depth_bin"] == 2.5
    assert by_obj.loc["ips_007_2", "depth_bin"] == 7.5
    assert by_obj.loc["ips_008_1", "depth_bin"] == 12.5
    assert "3 lignes" in result
    assert "3 matchées" in result
    assert "depth_bin" in result


def test_join_ecotaxa_ecopart_picks_key_by_overlap_not_first_row():
    """Key selection must use real overlap, not the first row.

    Here the first sample_id is absent from EcoPart but the other rows match,
    while obj_orig_id (also present) never matches. The previous first-row
    heuristic fell back to obj_orig_id and produced a silent 0-match join.
    """
    import pandas as pd
    from tools.ecopart_sources import make_ecopart_tools
    from tools.session_store import default_store as _store

    df_ecotaxa = pd.DataFrame({
        "sample_id": ["ips_999", "ips_007", "ips_008"],
        "obj_orig_id": ["zzz_1", "zzz_2", "zzz_3"],
        "object_depth_min": [3.0, 3.0, 3.0],
        "taxon": ["Calanus", "Calanus", "Oithona"],
    })
    df_ecopart = pd.DataFrame({
        "Profile": ["ips_007", "ips_008"],
        "Depth [m]": [2.5, 2.5],
        "Sampled volume [L]": [100.0, 95.0],
    })
    _store.set("thread-overlap:ecotaxa", df_ecotaxa, {"source": "ecotaxa:1165"})
    _store.set("thread-overlap:ecopart", df_ecopart, {"source": "ecopart:105"})

    join_tool = next(
        t for t in make_ecopart_tools("thread-overlap") if t.name == "join_ecotaxa_ecopart"
    )
    result = join_tool.invoke({})

    merged = _store.get("thread-overlap")["df"]
    by_id = merged.set_index("sample_id")
    assert by_id.loc["ips_007", "ecopart_Sampled volume [L]"] == 100.0
    assert by_id.loc["ips_008", "ecopart_Sampled volume [L]"] == 95.0
    assert pd.isna(by_id.loc["ips_999", "ecopart_Sampled volume [L]"])
    assert "2 matchées" in result


def test_join_ecotaxa_ecopart_reports_zero_overlap_clearly():
    """When no candidate key overlaps EcoPart profiles, surface a clear diagnostic."""
    import pandas as pd
    from tools.ecopart_sources import make_ecopart_tools
    from tools.session_store import default_store as _store

    df_ecotaxa = pd.DataFrame({
        "sample_id": ["aaa", "bbb"],
        "object_depth_min": [3.0, 3.0],
    })
    df_ecopart = pd.DataFrame({
        "Profile": ["ips_007"],
        "Depth [m]": [2.5],
        "Sampled volume [L]": [100.0],
    })
    _store.set("thread-no-overlap:ecotaxa", df_ecotaxa, {"source": "ecotaxa:1165"})
    _store.set("thread-no-overlap:ecopart", df_ecopart, {"source": "ecopart:105"})

    join_tool = next(
        t for t in make_ecopart_tools("thread-no-overlap") if t.name == "join_ecotaxa_ecopart"
    )
    result = join_tool.invoke({})

    assert "Aucune correspondance" in result
    assert "ips_007" in result
    # No join table should be stored on a zero-overlap result.
    assert not _store.has("thread-no-overlap:ecotaxa_ecopart")


def test_join_ecotaxa_ecopart_leaves_unmatched_bin_as_nan():
    import pandas as pd
    from tools.ecopart_sources import make_ecopart_tools
    from tools.session_store import default_store as _store

    _store._store.clear()

    # Object at depth 100 m → bin 102.5, not present in EcoPart.
    df_ecotaxa = pd.DataFrame({
        "obj_orig_id": ["ips_007_1", "ips_007_2"],
        "object_depth_min": [3.0, 100.0],
        "taxon": ["Calanus", "Oithona"],
    })
    df_ecopart = pd.DataFrame({
        "Profile": ["ips_007"],
        "Depth [m]": [2.5],
        "Sampled volume [L]": [100.0],
    })
    _store.set("thread-join-nan:ecotaxa", df_ecotaxa, {"source": "ecotaxa:1165"})
    _store.set("thread-join-nan:ecopart", df_ecopart, {"source": "ecopart:105"})

    join_tool = next(
        t for t in make_ecopart_tools("thread-join-nan") if t.name == "join_ecotaxa_ecopart"
    )
    join_tool.invoke({})

    merged = _store.get("thread-join-nan")["df"]
    by_obj = merged.set_index("obj_orig_id")
    assert by_obj.loc["ips_007_1", "ecopart_Sampled volume [L]"] == 100.0
    assert pd.isna(by_obj.loc["ips_007_2", "ecopart_Sampled volume [L]"])


def test_join_ecotaxa_ecopart_errors_without_depth_column():
    import pandas as pd
    from tools.ecopart_sources import make_ecopart_tools
    from tools.session_store import default_store as _store

    _store._store.clear()

    df_ecotaxa = pd.DataFrame({
        "obj_orig_id": ["ips_007_1"],
        "taxon": ["Calanus"],
    })
    df_ecopart = pd.DataFrame({
        "Profile": ["ips_007"],
        "Depth [m]": [2.5],
        "Sampled volume [L]": [100.0],
    })
    _store.set("thread-join-nodepth:ecotaxa", df_ecotaxa, {"source": "ecotaxa:1165"})
    _store.set("thread-join-nodepth:ecopart", df_ecopart, {"source": "ecopart:105"})

    join_tool = next(
        t for t in make_ecopart_tools("thread-join-nodepth") if t.name == "join_ecotaxa_ecopart"
    )
    result = join_tool.invoke({})

    assert "Colonne de profondeur introuvable" in result


def test_join_ecotaxa_ecopart_preserves_named_join_after_later_dataset_load():
    import pandas as pd
    from tools.dataset_registry import store_dataset
    from tools.data_tools import make_tools
    from tools.ecopart_sources import make_ecopart_tools
    from tools.session_store import default_store as _store

    thread_id = "thread-join-then-bio-oracle"
    for key in [
        thread_id,
        f"{thread_id}:ecotaxa",
        f"{thread_id}:ecopart",
        f"{thread_id}:ecotaxa_ecopart",
        f"{thread_id}:dataset:df_ecotaxa_ecopart_105",
        f"{thread_id}:dataset:df_bio_oracle_zones_temperature_ssp5_8_5_surface",
    ]:
        _store.clear(key)

    df_ecotaxa = pd.DataFrame({
        "obj_orig_id": ["ips_007_1", "ips_008_1"],
        "object_depth_min": [3.0, 3.0],
        "object_annotation_category": ["Copepoda", "Copepoda"],
    })
    df_ecopart = pd.DataFrame({
        "Profile": ["ips_007", "ips_008"],
        "Depth [m]": [2.5, 2.5],
        "Sampled volume [L]": [218.835, 160.671],
    })
    _store.set(f"{thread_id}:ecotaxa", df_ecotaxa, {"source": "ecotaxa:1165"})
    _store.set(
        f"{thread_id}:ecopart",
        df_ecopart,
        {"source": "ecopart:105", "project_id": 105},
    )
    _store.set(
        f"{thread_id}:ecopart:105",
        df_ecopart,
        {"source": "ecopart:105", "project_id": 105},
    )

    join_tool = next(
        t for t in make_ecopart_tools(thread_id) if t.name == "join_ecotaxa_ecopart"
    )
    result = join_tool.invoke({"project_id": 105})
    assert "df_ecotaxa_ecopart_105" in result

    store_dataset(
        _store,
        thread_id,
        pd.DataFrame({"zone": ["Arctique"], "temperature_projected": [7.9085]}),
        variable_name="df_bio_oracle_zones_temperature_ssp5_8_5_surface",
        meta={"source": "bio_oracle_zones"},
        latest_alias="bio_oracle",
    )

    run_pandas = next(t for t in make_tools(thread_id) if t.name == "run_pandas")
    output = run_pandas.invoke({
        "code": (
            "result = (list(df.columns), "
            "list(df_ecotaxa_ecopart.columns), "
            "list(df_ecotaxa_ecopart_105.columns), "
            "list(df_bio_oracle.columns))"
        )
    })

    assert "temperature_projected" in output
    assert "object_annotation_category" in output
    assert "ecopart_Sampled volume [L]" in output


def test_join_ecotaxa_ecopart_selects_explicit_project():
    import pandas as pd
    from tools.dataset_registry import store_dataset
    from tools.ecopart_sources import make_ecopart_tools
    from tools.session_store import default_store as _store

    thread_id = "thread-join-explicit"
    df_ecotaxa = pd.DataFrame({
        "obj_orig_id": ["ips_007_1"],
        "object_depth_min": [3.0],
    })
    df_105 = pd.DataFrame({
        "Profile": ["ips_007"],
        "Depth [m]": [2.5],
        "project_value": [105],
    })
    df_42 = pd.DataFrame({
        "Profile": ["ips_007"],
        "Depth [m]": [2.5],
        "project_value": [42],
    })
    _store.set(f"{thread_id}:ecotaxa", df_ecotaxa, {"source": "ecotaxa:1165"})
    store_dataset(
        _store,
        thread_id,
        df_105,
        variable_name="df_ecopart_105",
        meta={"source": "ecopart:105", "project_id": 105},
        latest_alias="ecopart",
    )
    store_dataset(
        _store,
        thread_id,
        df_42,
        variable_name="df_ecopart_42",
        meta={"source": "ecopart:42", "project_id": 42},
        latest_alias="ecopart",
    )

    join_tool = next(
        t for t in make_ecopart_tools(thread_id) if t.name == "join_ecotaxa_ecopart"
    )
    result = join_tool.invoke({"project_id": 105})

    joined = _store.get(thread_id)
    assert joined["df"]["ecopart_project_value"].iloc[0] == 105
    assert joined["meta"]["source"] == "join:ecotaxa+ecopart:105"
    assert "105" in result


def test_join_ecotaxa_ecopart_defaults_to_latest_project():
    import pandas as pd
    from tools.dataset_registry import store_dataset
    from tools.ecopart_sources import make_ecopart_tools
    from tools.session_store import default_store as _store

    thread_id = "thread-join-latest"
    _store.set(
        f"{thread_id}:ecotaxa",
        pd.DataFrame({
            "obj_orig_id": ["ips_007_1"],
            "object_depth_min": [3.0],
        }),
        {"source": "ecotaxa:1165"},
    )
    store_dataset(
        _store,
        thread_id,
        pd.DataFrame({
            "Profile": ["ips_007"],
            "Depth [m]": [2.5],
            "project_value": [42],
        }),
        variable_name="df_ecopart_42",
        meta={"source": "ecopart:42", "project_id": 42},
        latest_alias="ecopart",
    )

    join_tool = next(
        t for t in make_ecopart_tools(thread_id) if t.name == "join_ecotaxa_ecopart"
    )
    result = join_tool.invoke({})

    assert _store.get(thread_id)["df"]["ecopart_project_value"].iloc[0] == 42
    assert "42" in result


def test_join_ecotaxa_ecopart_reports_missing_explicit_project():
    import pandas as pd
    from tools.ecopart_sources import make_ecopart_tools
    from tools.session_store import default_store as _store

    thread_id = "thread-join-missing-project"
    _store.set(
        f"{thread_id}:ecotaxa",
        pd.DataFrame({"obj_orig_id": ["ips_007_1"]}),
        {"source": "ecotaxa:1165"},
    )
    join_tool = next(
        t for t in make_ecopart_tools(thread_id) if t.name == "join_ecotaxa_ecopart"
    )

    result = join_tool.invoke({"project_id": 999})

    assert "query_ecopart(project_id=999)" in result


def test_join_ecotaxa_ecopart_missing_source_returns_error():
    from tools.ecopart_sources import make_ecopart_tools
    from tools.session_store import default_store as _store

    _store._store.clear()

    tools = make_ecopart_tools("thread-join-missing")
    join_tool = next(t for t in tools if t.name == "join_ecotaxa_ecopart")
    result = join_tool.invoke({})

    assert "query_ecotaxa" in result
    assert "query_ecopart" in result
