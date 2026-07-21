"""TDD — séparation exécutable des référentiels de zones EcoTaxa."""

import sqlite3


def test_zone_reference_backfill_distinguishes_iho_meow_outside_and_missing():
    from core.ecotaxa_browser.cache.repo import (
        backfill_zone_references,
        init_schema,
    )

    conn = sqlite3.connect(":memory:")
    init_schema(conn)
    conn.executemany(
        """
        INSERT INTO samples_cache (sample_id, project_id, last_synced, iho_zone)
        VALUES (?, 1, 'now', ?)
        """,
        [
            (1, "Mer de Beaufort"),
            (2, "MEOW: Beaufort-Amundsen-Viscount Melville-Queen Maud"),
            (3, "Hors zone référencée"),
            (4, "Sans coordonnées"),
        ],
    )

    assert backfill_zone_references(conn) == 4

    rows = conn.execute(
        "SELECT sample_id, zone_reference FROM samples_cache ORDER BY sample_id"
    ).fetchall()
    assert rows == [
        (1, "IHO"),
        (2, "MEOW"),
        (3, "OUTSIDE"),
        (4, "MISSING_COORDINATES"),
    ]


def test_zone_grouping_guard_requires_reference_for_iho_zone_aggregation():
    from tools.copepod_sources import _zone_grouping_requires_reference

    assert _zone_grouping_requires_reference(
        "SELECT iho_zone, COUNT(*) FROM samples_cache GROUP BY iho_zone"
    )
    assert not _zone_grouping_requires_reference(
        """
        SELECT zone_reference, iho_zone, COUNT(*)
        FROM samples_cache
        GROUP BY zone_reference, iho_zone
        """
    )


def test_query_ecotaxa_cache_blocks_a_zone_grouping_without_reference(
    tmp_path, monkeypatch
):
    import tools.copepod_sources as source_module
    from core.ecotaxa_browser.cache.repo import init_schema
    from tools.session_store import SessionStore

    cache_db = tmp_path / "cache.sqlite"
    conn = sqlite3.connect(cache_db)
    init_schema(conn)
    conn.execute(
        """
        INSERT INTO samples_cache
            (sample_id, project_id, last_synced, iho_zone, zone_reference)
        VALUES (1, 1, 'now', 'Mer de Beaufort', 'IHO')
        """
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("ECOTAXA_CACHE_DB", str(cache_db))
    monkeypatch.setattr(source_module, "_store", SessionStore(tmp_path / "sessions"))
    query = next(
        tool for tool in source_module.make_source_tools("zone-reference-thread")
        if tool.name == "query_ecotaxa_cache"
    )

    result = query.invoke(
        {"sql": "SELECT iho_zone, COUNT(*) FROM samples_cache GROUP BY iho_zone"}
    )

    assert "Agrégation de zones refusée" in result
    assert "zone_reference" in result
