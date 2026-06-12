"""TDD — workspace SQL en lecture seule."""

import sqlite3


def test_list_sql_tables_from_readonly_database_url(tmp_path):
    from tools.sql_workspace import list_sql_tables

    db_path = tmp_path / "source.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE casts (id INTEGER PRIMARY KEY, station TEXT)")
    conn.execute("CREATE TABLE samples (id INTEGER PRIMARY KEY, cast_id INTEGER)")
    conn.commit()
    conn.close()

    database_url = f"sqlite:///{db_path}"
    tables = list_sql_tables(database_url)

    assert tables == ["casts", "samples"]


def test_resolve_sql_database_url_prefers_session_meta(tmp_path, monkeypatch):
    from tools.sql_workspace import resolve_sql_database_url, set_sql_workspace_database_url
    from tools.session_store import default_store

    db_path = tmp_path / "source.sqlite"
    sqlite3.connect(db_path).close()

    monkeypatch.delenv("DATABASE_URL", raising=False)
    default_store.clear("thread-sql-config")
    set_sql_workspace_database_url("thread-sql-config", f"sqlite:///{db_path}")

    assert resolve_sql_database_url("thread-sql-config") == f"sqlite:///{db_path}"


def test_extract_sql_workspace_database_url_from_openwebui_prompt():
    from tools.sql_workspace import extract_sql_workspace_database_url

    text = """
    SQL workspace setup
    DATABASE_URL=postgresql+psycopg://user:pass@host:5432/dbname
    """

    assert extract_sql_workspace_database_url(text) == "postgresql+psycopg://user:pass@host:5432/dbname"


def test_extract_sql_workspace_database_url_accepts_raw_url():
    from tools.sql_workspace import extract_sql_workspace_database_url

    assert extract_sql_workspace_database_url("sqlite:////tmp/source.sqlite") == "sqlite:////tmp/source.sqlite"


def test_copy_sql_query_to_workspace_writes_tsv(tmp_path):
    from tools.sql_workspace import copy_sql_query_to_workspace

    db_path = tmp_path / "source.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE casts (id INTEGER PRIMARY KEY, station TEXT)")
    conn.executemany(
        "INSERT INTO casts (id, station) VALUES (?, ?)",
        [(1, "A"), (2, "B")],
    )
    conn.commit()
    conn.close()

    workspace_dir = tmp_path / "workspace"
    output_path = copy_sql_query_to_workspace(
        database_url=f"sqlite:///{db_path}",
        query="SELECT id, station FROM casts ORDER BY id LIMIT 10",
        workspace_dir=workspace_dir,
        output_stem="casts_20260609_1015",
    )

    assert output_path.exists()
    assert output_path.suffix == ".tsv"
    assert output_path.read_text(encoding="utf-8").splitlines() == [
        "id\tstation",
        "1\tA",
        "2\tB",
    ]


def test_copy_sql_query_to_workspace_requires_explicit_limit(tmp_path):
    import pytest

    from tools.sql_workspace import copy_sql_query_to_workspace

    db_path = tmp_path / "source.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE casts (id INTEGER PRIMARY KEY, station TEXT)")
    conn.executemany(
        "INSERT INTO casts (id, station) VALUES (?, ?)",
        [(1, "A"), (2, "B")],
    )
    conn.commit()
    conn.close()

    with pytest.raises(ValueError, match="LIMIT"):
        copy_sql_query_to_workspace(
            database_url=f"sqlite:///{db_path}",
            query="SELECT id, station FROM casts ORDER BY id",
            workspace_dir=tmp_path / "workspace",
            output_stem="casts_no_limit",
        )


def test_copy_sql_query_to_workspace_rejects_result_over_row_cap(tmp_path, monkeypatch):
    import pytest

    from tools.sql_workspace import copy_sql_query_to_workspace

    db_path = tmp_path / "source.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE casts (id INTEGER PRIMARY KEY, station TEXT)")
    conn.executemany(
        "INSERT INTO casts (id, station) VALUES (?, ?)",
        [(1, "A"), (2, "B"), (3, "C")],
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("SQL_WORKSPACE_MAX_COPY_ROWS", "2")

    with pytest.raises(ValueError, match="exceeds row cap"):
        copy_sql_query_to_workspace(
            database_url=f"sqlite:///{db_path}",
            query="SELECT id, station FROM casts ORDER BY id LIMIT 3",
            workspace_dir=tmp_path / "workspace",
            output_stem="casts_over_cap",
        )


def test_preview_sql_table_returns_markdown_sample(tmp_path):
    from tools.sql_workspace import preview_sql_table

    db_path = tmp_path / "source.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE casts (id INTEGER PRIMARY KEY, station TEXT)")
    conn.executemany(
        "INSERT INTO casts (id, station) VALUES (?, ?)",
        [(1, "A"), (2, "B"), (3, "C")],
    )
    conn.commit()
    conn.close()

    preview = preview_sql_table(
        database_url=f"sqlite:///{db_path}",
        table_name="casts",
        limit=2,
    )

    assert "Table `casts`" in preview
    assert "Row count: 3" in preview
    assert "| column | type | nullable | pk |" in preview
    assert "id" in preview
    assert "INTEGER" in preview
    assert "station" in preview
    assert "TEXT" in preview
    assert "2 lignes × 2 colonnes" in preview
    lines = preview.splitlines()
    assert any("1" in line and "A" in line for line in lines)
    assert any("2" in line and "B" in line for line in lines)
    assert "3" in preview


def test_preview_sql_table_reports_empty_table_schema(tmp_path):
    from tools.sql_workspace import preview_sql_table

    db_path = tmp_path / "source.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE empty_casts (id INTEGER PRIMARY KEY, station TEXT)")
    conn.commit()
    conn.close()

    preview = preview_sql_table(
        database_url=f"sqlite:///{db_path}",
        table_name="empty_casts",
        limit=2,
    )

    assert "Row count: 0" in preview
    assert "Aucune ligne trouvée." in preview


def test_preview_sql_table_accepts_sqlite_views(tmp_path):
    from tools.sql_workspace import preview_sql_table

    db_path = tmp_path / "source.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE casts (id INTEGER PRIMARY KEY, station TEXT, depth_m REAL)")
    conn.executemany(
        "INSERT INTO casts (id, station, depth_m) VALUES (?, ?, ?)",
        [(1, "A", 10.0), (2, "B", 25.0)],
    )
    conn.execute(
        """
        CREATE VIEW deep_casts AS
        SELECT id, station, depth_m
        FROM casts
        WHERE depth_m >= 20
        """
    )
    conn.commit()
    conn.close()

    preview = preview_sql_table(
        database_url=f"sqlite:///{db_path}",
        table_name="deep_casts",
        limit=5,
    )

    assert "View `deep_casts`" in preview
    assert "Row count: ?" in preview
    assert "| column | type | nullable | pk |" in preview
    assert "depth_m" in preview
    preview_lines = preview.split("## Preview", 1)[1].splitlines()
    assert any("B" in line and "25" in line for line in preview_lines)
    assert not any(" A " in line and "10" in line for line in preview_lines)


def test_preview_sql_table_supports_where_and_order_by(tmp_path):
    from tools.sql_workspace import preview_sql_table

    db_path = tmp_path / "source.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE observations (id INTEGER PRIMARY KEY, depth_m REAL, copepod_count INTEGER)")
    conn.executemany(
        "INSERT INTO observations (id, depth_m, copepod_count) VALUES (?, ?, ?)",
        [(1, 5.0, 42), (2, 50.0, 35), (3, 150.0, 12), (4, 10.0, 58)],
    )
    conn.commit()
    conn.close()

    preview = preview_sql_table(
        database_url=f"sqlite:///{db_path}",
        table_name="observations",
        limit=2,
        where="depth_m >= 10",
        order_by="copepod_count DESC",
    )

    assert "Filter: depth_m >= 10" in preview
    assert "Order by: copepod_count DESC" in preview
    assert "4" in preview
    assert "58" in preview
    assert "2" in preview
    assert "35" in preview
    preview_lines = preview.split("## Preview", 1)[1].splitlines()
    assert not any("150" in line and "12" in line for line in preview_lines)


def test_make_sql_tools_expose_list_and_copy(tmp_path, monkeypatch):
    from tools.sql_workspace import make_sql_tools
    from tools.session_store import default_store

    db_path = tmp_path / "source.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE casts (id INTEGER PRIMARY KEY, station TEXT)")
    conn.executemany(
        "INSERT INTO casts (id, station) VALUES (?, ?)",
        [(1, "A"), (2, "B")],
    )
    conn.commit()
    conn.close()

    workspace_dir = tmp_path / "workspace"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("SQL_WORKSPACE_DIR", str(workspace_dir))
    default_store._store.clear()

    tools = make_sql_tools("thread-sql")
    tool_names = {tool.name for tool in tools}
    assert "list_sql_tables" in tool_names
    assert "preview_sql_table" in tool_names
    assert "copy_sql_query_to_workspace" in tool_names

    list_tool = next(tool for tool in tools if tool.name == "list_sql_tables")
    preview_tool = next(tool for tool in tools if tool.name == "preview_sql_table")
    copy_tool = next(tool for tool in tools if tool.name == "copy_sql_query_to_workspace")

    listed = list_tool.invoke({})
    previewed = preview_tool.invoke({"table_name": "casts", "limit": 1})
    copied = copy_tool.invoke({
        "query": "SELECT id, station FROM casts ORDER BY id LIMIT 10",
        "output_stem": "station_summary",
    })

    assert "casts" in listed
    assert "1 lignes × 2 colonnes" in previewed
    assert "Télécharger" in copied
    assert default_store.has("thread-sql")
    session = default_store.get("thread-sql")
    assert session["df"].shape == (2, 2)
    stable = default_store.get("thread-sql:dataset:df_sql_station_summary")
    assert stable["df"].shape == (2, 2)
    assert "df_sql_station_summary" in copied


def test_list_sql_tables_tool_returns_database_overview(tmp_path, monkeypatch):
    from tools.sql_workspace import make_sql_tools
    from tools.session_store import default_store

    db_path = tmp_path / "source.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("CREATE TABLE stations (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    conn.execute(
        """
        CREATE TABLE casts (
            id INTEGER PRIMARY KEY,
            station_id INTEGER NOT NULL,
            depth_m REAL,
            FOREIGN KEY(station_id) REFERENCES stations(id)
        )
        """
    )
    conn.execute(
        """
        CREATE VIEW cast_depths AS
        SELECT casts.id, stations.name, casts.depth_m
        FROM casts
        JOIN stations ON stations.id = casts.station_id
        """
    )
    conn.executemany("INSERT INTO stations (id, name) VALUES (?, ?)", [(1, "A"), (2, "B")])
    conn.executemany(
        "INSERT INTO casts (id, station_id, depth_m) VALUES (?, ?, ?)",
        [(10, 1, 5.0), (11, 2, 15.0)],
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    default_store._store.clear()

    tools = make_sql_tools("thread-sql-overview")
    list_tool = next(tool for tool in tools if tool.name == "list_sql_tables")

    overview = list_tool.invoke({})

    assert "| schema | name | type | columns | rows | primary key | foreign keys |" in overview
    assert "| main | casts | table | 3 | 2 | id | station_id -> stations.id |" in overview
    assert "| main | stations | table | 2 | 2 | id | - |" in overview
    assert "| main | cast_depths | view | 3 | ? | - | - |" in overview
