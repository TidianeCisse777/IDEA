import sqlite3


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
