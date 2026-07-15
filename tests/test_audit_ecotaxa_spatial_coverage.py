"""Tool `audit_ecotaxa_spatial_coverage` — audit spatial par zone nommée."""

from tools.copepod_sources import make_source_tools
from core.ecotaxa_browser.cache.repo import init_schema, open_connection, upsert_sample


def _tool(thread_id: str):
    return next(
        t
        for t in make_source_tools(thread_id)
        if t.name == "audit_ecotaxa_spatial_coverage"
    )


def test_spatial_audit_places_samples_in_named_zones(tmp_path, monkeypatch):
    cache = tmp_path / "ecotaxa_cache.sqlite"
    conn = open_connection(str(cache))
    init_schema(conn)
    # Deux samples clairement dans la baie de Baffin.
    for sid, (lat, lon) in ((1, (74.0, -70.0)), (2, (75.5, -68.0))):
        upsert_sample(
            conn, sample_id=sid, project_id=17498, lat_avg=lat, lon_avg=lon,
            date_min="2024-09-10", date_max="2024-09-10", object_count=100,
            instrument="UVP6", last_synced="ts",
        )
    conn.close()
    monkeypatch.setenv("ECOTAXA_CACHE_DB", str(cache))

    out = _tool("thread-spatial-1").invoke({})

    assert "Baie de Baffin" in out
    assert "2 samples géolocalisés" in out
    # Section lacunes présente.
    assert "Lacunes" in out


def test_spatial_audit_reports_no_geolocated_samples(tmp_path, monkeypatch):
    cache = tmp_path / "empty.sqlite"
    conn = open_connection(str(cache))
    init_schema(conn)
    conn.close()
    monkeypatch.setenv("ECOTAXA_CACHE_DB", str(cache))

    out = _tool("thread-spatial-2").invoke({})

    assert "aucun sample" in out.lower()
