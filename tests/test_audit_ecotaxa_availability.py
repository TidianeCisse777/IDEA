"""Tool `audit_ecotaxa_availability` — audit de couverture cache read-only."""

from tools.copepod_sources import make_source_tools
from core.ecotaxa_browser.cache.repo import init_schema, open_connection, upsert_sample


def _seed(path: str) -> None:
    conn = open_connection(path)
    init_schema(conn)
    upsert_sample(
        conn, sample_id=1, project_id=42, lat_avg=67.0, lon_avg=-63.0,
        date_min="2015-04-19", date_max="2015-04-19", object_count=50,
        instrument="UVP5", last_synced="ts", original_id="green_edge_1",
    )
    for sid, oc in ((10, 5000), (11, 300), (12, 120)):
        upsert_sample(
            conn, sample_id=sid, project_id=17498, lat_avg=80.0, lon_avg=-70.0,
            date_min="2024-09-10", date_max="2024-09-10", object_count=oc,
            instrument="UVP6", last_synced="ts", original_id=f"leg4_{sid}",
        )
    conn.close()


def _tool(thread_id: str):
    return next(
        t
        for t in make_source_tools(thread_id)
        if t.name == "audit_ecotaxa_availability"
    )


def test_audit_ranks_sparsest_projects_first(tmp_path, monkeypatch):
    cache = tmp_path / "ecotaxa_cache.sqlite"
    _seed(str(cache))
    monkeypatch.setenv("ECOTAXA_CACHE_DB", str(cache))

    out = _tool("thread-audit-1").invoke({})

    # Les deux projets et leurs comptes de samples.
    assert "42" in out and "17498" in out
    # Distribution temporelle : les deux années couvertes.
    assert "2015" in out and "2024" in out
    # Le projet le plus pauvre (42, 1 sample) apparaît avant le plus riche.
    assert out.index("42") < out.index("17498")


def test_audit_reports_empty_cache(tmp_path, monkeypatch):
    cache = tmp_path / "empty.sqlite"
    conn = open_connection(str(cache))
    init_schema(conn)
    conn.close()
    monkeypatch.setenv("ECOTAXA_CACHE_DB", str(cache))

    out = _tool("thread-audit-2").invoke({})

    assert "aucun" in out.lower()
