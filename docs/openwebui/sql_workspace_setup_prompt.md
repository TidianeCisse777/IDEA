# Open WebUI prompt: SQL workspace setup

Use this prompt in Open WebUI when you want an explicit form to capture the SQL server you will analyse.

Important:
- This prompt does not mutate the backend configuration by itself.
- The backend still reads `DATABASE_URL` from the user's local `.env`.
- Use the value entered here as the copy/paste source for that local `.env`.

Custom input variables for Open WebUI:

```text
{{database_url | text:placeholder="postgresql+psycopg://user:pass@host:5432/dbname":required}}
{{connection_label | text:placeholder="optional label for this server"}}
{{notes | textarea:placeholder="optional context about the dataset or schema"}}
```

Prompt body:

```text
SQL workspace setup

You are helping the user prepare a read-only SQL workspace for analysis.

Use the database URL they provide to confirm:
- the server type (SQLite or PostgreSQL)
- that the connection must stay read-only
- that the next step is to list tables, preview a table, or copy a SELECT result into a local workspace

Keep the response short and practical.
If the user has not yet copied the value into their `.env`, remind them to set `DATABASE_URL` locally before asking the agent to query SQL data.
```
