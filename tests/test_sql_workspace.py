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
        query="SELECT id, station FROM casts ORDER BY id",
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
        "query": "SELECT id, station FROM casts ORDER BY id",
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
