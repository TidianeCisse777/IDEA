# Local file upload testing

## NeoLab local policy: Open WebUI RAG disabled globally

The macOS ARM64 development image now stores every upload with
`process=false`. This is enforced in both the browser upload client and the
server handler, so a stale browser that still requests `process=true` cannot
start extraction or embeddings. IDEA receives the stored original and copies
it into its sandbox as before.

This local policy also disables native Open WebUI indexing for uploads made in
Workspace > Knowledge. Do not rely on a newly uploaded Knowledge collection
while the policy is active; validate literature ingestion separately before
re-enabling PaperQA collection workflows. Existing vector data is not deleted
by this change.

Regression evidence: upload a small file while explicitly requesting
`process=true`. The response must contain an empty `data` object, the server log
must report `file.content_type: ... False`, and no processing-status or
`generating embeddings for file-...` line may follow.

Local testing passed on 2026-09-11 after building with the 4 GB heap. The local
Dockerfile builds public Open WebUI `v0.11.3`, patches its upload client, and
adds the same storage-only guard to the server handler. IDEA advertises
`raw_file_access` on its official assistants and base model.

Direct literature attachments can still be downloaded and indexed by PaperQA
inside LangGraph when `query_knowledge_base` is invoked. This is independent
of Open WebUI's native RAG. New Workspace > Knowledge ingestion is unavailable
under the global policy and must not be used as a validation path.

## Build and start locally

Run these commands from the IDEA directory. The normal development override
uses `openwebui/Dockerfile.local` and preserves the existing Open WebUI data
volume.

Use a 4 GB Node heap for the local frontend build; this succeeded on the user's
8 GB environment. The release workflow uses 8 GB, which left too little memory
for other processes locally. The heap limit is not a total process-memory cap.

```bash
# Build Open WebUI v0.11.3 with the frontend and backend no-RAG guards.
docker compose build openwebui

# Start the agent and its dependencies, including the normal local dev override.
docker compose up -d langgraph

# Replace only the UI after the build.
docker compose up -d --no-deps openwebui

# Wait until this succeeds before deploying assistant settings.
curl --fail http://localhost:3001/health

# Reconcile official assistant and IDEA Agent capabilities using the existing setup.
./assistants/deploy_assistants_openwebui.py --reconcile
```

`--no-deps` above replaces only Open WebUI; it does not start LangGraph. Check
`docker compose ps` if chat reports that the `langgraph` hostname cannot be
resolved. `docker compose up -d langgraph` starts its declared dependencies
without replacing the running customized Open WebUI image. On a fresh stack,
complete the normal database/service setup described in the README as well.

Reload the browser after deployment. For a separately maintained custom IDEA
assistant such as CIndRA, enable **Raw File Access** under its model capabilities.
The deployment script intentionally preserves custom assistants' settings.
Enable this capability only on integrations that can download original files.

`--reconcile` is required for existing official assistants: without it the
script skips their settings and they will not receive `raw_file_access`.
Reconciliation restores repository-managed fields, including prompts, on those
assistants. Afterward, reload the browser and upload a fresh file; it does not
cancel processing already started by an earlier upload.

## Short manual check

1. Select an official IDEA assistant. Drag in a multi-megabyte CSV and one MAT
   or NetCDF file. Repeat one upload through the file picker. The attachment
   should become ready when the upload POST finishes. In browser Network tools,
   confirm `POST /api/v1/files/?process=false` and no processing-status request.
2. Ask IDEA to list the uploaded files, report their sizes and SHA-256 hashes,
   and read a few values with the appropriate library. Compare one hash with
   local `sha256sum`. Check Open WebUI logs for unexpected extraction or
   sentence embedding during upload.
3. Attach a PDF and a Word document directly and ask questions using
   `query_knowledge_base`. Supported documents should return PaperQA
   answers/citations; unsupported or failed documents should appear as explicit
   warnings. Do not use a newly uploaded Knowledge collection for this test.
4. Check an image and an upload failure (for example, a file above the configured
   size limit). A failed upload should show an error and remove its pending card.
5. If generic models are available, confirm their uploads also remain
   storage-only. The server rejects RAG processing globally regardless of the
   selected model or a stale client's `process=true` query.

Temporary IDEA chats also need server-stored originals for sandbox access;
their raw attachments use the normal authenticated file storage path. This
change does not add a new file-retention policy. Existing upload size and
authorization checks remain in force. Open WebUI's RAG extension allowlist is
processing-specific and, as with its existing raw-upload API, does not apply
to `process=false` uploads.

## Current local integration

The active macOS ARM64 fallback is public Open WebUI `v0.11.3` plus the
repository-owned `openwebui/disable_rag_uploads.py` patch. The production
Dockerfile still targets the Hawaii image separately. Revalidate both patch
insertion points whenever the public Open WebUI version changes; the build
fails deliberately if either upstream source location no longer matches.
