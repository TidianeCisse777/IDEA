# Skill: sql_workspace_query

You are working with the read-only SQL workspace.
The agent can now read a SQL server, copy results to local tabular files, and analyse those copies like regular files.

---

## Routing rule

- When the user wants to list tables on a SQL server, call `list_sql_tables`.
- When the user wants to inspect a table quickly before exporting, call `preview_sql_table`.
- When the user wants to copy a read-only SQL query into the local workspace, call `copy_sql_query_to_workspace`.
- Never modify the SQL source.
- Always use local copies for subsequent analyses.

---

## Connection contract

- The connection comes from `DATABASE_URL` in the `.env` file.
- The source database remains read-only.
- The conversation workspace is local, timestamped, and tied to the current conversation.

---

## After copying

1. Load the generated file with the standard tabular pipeline.
2. Use `run_pandas` for calculations and tables.
3. Use `run_graph` for visualisations.
4. If another SQL query is needed, copy a new timestamped version rather than overwriting the previous one.

---

## Limits

- Do not run `INSERT`, `UPDATE`, `DELETE` or `DROP`.
- Only copy the tables or subsets requested by the user.
- Do not confuse the local copy with the remote source.
