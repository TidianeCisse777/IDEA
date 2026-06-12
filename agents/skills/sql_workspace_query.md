# Skill: sql_workspace_query

You are working with the read-only SQL workspace.
The agent can now read a SQL server, copy results to local tabular files, and analyse those copies like regular files.

---

## Routing rule

- When the user wants to understand a SQL database, start with `list_sql_tables`; it returns a compact overview of visible tables, views, schemas, row counts when available, primary keys, and foreign keys.
- When the user wants to inspect a table or view quickly before exporting, call `preview_sql_table`. Use `where` and `order_by` for light filtering or sorting instead of copying a full query.
- When the user asks to join, merge, cross, combine, or relate SQL tables, use `list_sql_tables` first, read the foreign keys, build a read-only `SELECT ... JOIN ...` query with an explicit `LIMIT`, then call `copy_sql_query_to_workspace`.
- When the user wants to copy a read-only SQL query into the local workspace, call `copy_sql_query_to_workspace`.
- Never modify the SQL source.
- Always use local copies for subsequent analyses.
- SQL copies require an explicit `LIMIT` and are capped by `SQL_WORKSPACE_MAX_COPY_ROWS`.

---

## Connection contract

- The connection comes from `DATABASE_URL` in the `.env` file.
- The source database remains read-only.
- The conversation workspace is local, timestamped, and tied to the current conversation.
- Supported URLs are SQLite (`sqlite:////absolute/path/source.sqlite`), PostgreSQL (`postgresql+psycopg://user:password@host:5432/dbname`), MySQL (`mysql+pymysql://user:password@host:3306/dbname`), and MariaDB through the MySQL protocol (`mysql+pymysql://user:password@host:3306/dbname`).
- Unsupported SQLAlchemy dialects are rejected instead of being queried without a read-only strategy.

---

## After copying

1. Load the generated file with the standard tabular pipeline.
2. Use `run_pandas` for calculations and tables.
3. Use `run_graph` for visualisations.
4. If another SQL query is needed, copy a new timestamped version rather than overwriting the previous one.

---

## SQL joins

1. Start with `list_sql_tables` to discover schemas, tables, views, primary keys, and foreign keys.
2. Use row counts as table cardinality signals before choosing the join direction or deciding whether a copy may be large.
3. Prefer foreign-key paths shown in the overview, for example `observations.cast_id -> casts.id`.
4. If the needed column names or types are unclear, call `preview_sql_table` on the candidate tables or views before writing SQL.
5. Build a narrow `SELECT` with explicit column names, not `SELECT *`, when multiple tables are joined.
6. Always include an explicit `LIMIT` before calling `copy_sql_query_to_workspace`.
7. If `copy_sql_query_to_workspace` returns a schema, column, or join error, use the error plus `list_sql_tables` / `preview_sql_table` output to retry once with a corrected read-only query.
8. If no foreign-key path is visible after inspection, state the missing relation and ask which columns should be used.

---

## Limits

- Do not run `INSERT`, `UPDATE`, `DELETE` or `DROP`.
- Only copy the tables or subsets requested by the user.
- Do not call `copy_sql_query_to_workspace` without an explicit `LIMIT`; narrow the query with filters or a smaller `LIMIT` if the row cap is hit.
- Do not confuse the local copy with the remote source.
