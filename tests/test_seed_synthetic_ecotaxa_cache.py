import sqlite3

from scripts.dev.seed_synthetic_ecotaxa_cache import seed_synthetic_cache


def test_seed_synthetic_cache_covers_all_registered_zones(tmp_path):
    output = tmp_path / "ecotaxa_synthetic.sqlite"

    summary = seed_synthetic_cache(output)

    conn = sqlite3.connect(output)
    assert summary["zones"] == 65
    assert conn.execute("SELECT COUNT(*) FROM samples_cache").fetchone()[0] == 1170
    assert conn.execute("SELECT COUNT(*) FROM objects_cache").fetchone()[0] == 9360
    assert conn.execute("SELECT COUNT(DISTINCT project_id) FROM samples_cache").fetchone()[0] == 195
    assert conn.execute(
        "SELECT COUNT(DISTINCT json_extract(free_fields_json, '$.ecoregion')) "
        "FROM samples_cache"
    ).fetchone()[0] == 65
    assert conn.execute(
        "SELECT COUNT(*) FROM objects_cache WHERE classification_status IN ('V', 'P', 'D', 'U')"
    ).fetchone()[0] == 9360
    conn.close()
