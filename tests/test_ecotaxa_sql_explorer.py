import sqlite3

import pytest


def test_objects_cache_is_available_for_aggregate_exploration():
    from core.ecotaxa_browser.cache import sql_explorer

    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE objects_cache ("
        "object_id INTEGER, sample_id INTEGER, taxon TEXT, status TEXT)"
    )

    tables = {item["table"] for item in sql_explorer.list_tables(conn)}
    schema = sql_explorer.describe_table(conn, "objects_cache")

    assert "objects_cache" in tables
    assert schema["ok"] is True
    assert {column["name"] for column in schema["columns"]} >= {
        "sample_id", "taxon", "status"
    }


def test_run_select_without_cap_returns_all_rows():
    from core.ecotaxa_browser.cache.sql_explorer import run_select

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE samples (sample_id INTEGER, label TEXT)")
    conn.executemany(
        "INSERT INTO samples VALUES (?, ?)",
        ((index, f"sample-{index}") for index in range(501)),
    )

    result = run_select(conn, "SELECT sample_id, label FROM samples", cap=None)

    assert result["ok"] is True
    assert result["count"] == 501
    assert len(result["rows"]) == 501
    assert result["truncated"] is False


def test_table_map_covers_actual_tables_columns_grains_and_relations():
    from core.ecotaxa_browser.cache import sql_explorer

    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE samples_cache (
            sample_id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL
        );
        CREATE TABLE project_schemas_cache (
            project_id INTEGER PRIMARY KEY,
            schema_json TEXT NOT NULL
        );
        CREATE TABLE local_extension (
            extension_id INTEGER PRIMARY KEY AUTOINCREMENT,
            sample_id INTEGER,
            score REAL
        );
        """
    )

    mapped = {item["table"]: item for item in sql_explorer.list_tables(conn)}

    assert set(mapped) == {
        "samples_cache",
        "project_schemas_cache",
        "local_extension",
    }
    assert mapped["samples_cache"]["grain"].startswith("Une ligne par sample")
    assert {column["name"] for column in mapped["samples_cache"]["columns"]} == {
        "sample_id",
        "project_id",
    }
    assert mapped["samples_cache"]["relations"] == [
        {
            "from_column": "project_id",
            "to_table": "project_schemas_cache",
            "to_column": "project_id",
            "kind": "logical",
        }
    ]
    assert "extension locale" in mapped["local_extension"]["description"]
    assert sql_explorer.describe_table(conn, "local_extension")["ok"] is True


def test_run_select_accepts_cte_join_and_keeps_complete_result():
    from core.ecotaxa_browser.cache.sql_explorer import run_select

    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE samples (sample_id INTEGER PRIMARY KEY, project_id INTEGER);
        CREATE TABLE projects (project_id INTEGER PRIMARY KEY, title TEXT);
        INSERT INTO samples VALUES (1, 42), (2, 42), (3, 99);
        INSERT INTO projects VALUES (42, 'Alpha'), (99, 'Beta');
        """
    )

    result = run_select(
        conn,
        """
        WITH sample_counts AS (
            SELECT project_id, COUNT(*) AS n_samples
            FROM samples GROUP BY project_id
        )
        SELECT p.title, c.n_samples
        FROM sample_counts c
        JOIN projects p USING (project_id)
        ORDER BY p.title
        """,
        cap=None,
    )

    assert result["ok"] is True
    assert result["rows"] == [
        {"title": "Alpha", "n_samples": 2},
        {"title": "Beta", "n_samples": 1},
    ]


def test_run_select_blocks_write_cte_and_preserves_rows():
    from core.ecotaxa_browser.cache.sql_explorer import run_select

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE samples (sample_id INTEGER, label TEXT)")
    conn.execute("INSERT INTO samples VALUES (1, 'original')")
    conn.commit()

    result = run_select(
        conn,
        """
        WITH chosen AS (SELECT sample_id FROM samples)
        UPDATE samples SET label = 'changed'
        WHERE sample_id IN (SELECT sample_id FROM chosen)
        """,
    )

    assert result["ok"] is False
    assert conn.execute("SELECT label FROM samples").fetchone()[0] == "original"


def test_readonly_connection_never_creates_or_mutates_cache(tmp_path):
    from core.ecotaxa_browser.cache.repo import open_readonly_connection

    cache = tmp_path / "cache.sqlite"
    writer = sqlite3.connect(cache)
    writer.execute("CREATE TABLE samples (sample_id INTEGER PRIMARY KEY)")
    writer.execute("INSERT INTO samples VALUES (1)")
    writer.commit()
    writer.close()

    reader = open_readonly_connection(str(cache))
    with pytest.raises(sqlite3.OperationalError):
        reader.execute("INSERT INTO samples VALUES (2)")
    assert reader.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 1
    reader.close()

    missing = tmp_path / "missing.sqlite"
    with pytest.raises(sqlite3.OperationalError):
        open_readonly_connection(str(missing))
    assert not missing.exists()
