"""OpenAI-compatible API — expose l'agent copépodes pour Open WebUI."""
import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator

import uvicorn
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Header, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from openai import RateLimitError
from langchain_core.callbacks import BaseCallbackHandler
from pydantic import BaseModel

load_dotenv()

from agent import (
    make_agent,
    _CHECKPOINTS_DB,
    repair_invalid_tool_history,
    arepair_invalid_tool_history,
    get_context_audit,
)
from tools.openwebui_uploads import resolve_attached_files, resolve_request_files, resolve_chat_files
from tools.public_url import graph_url, serve_base_url
from tools.sql_workspace import extract_sql_workspace_database_url, set_sql_workspace_database_url
from tools.session_store import default_store
from tools.run_store import default_run_store
from tools.feedback import submit_feedback
from openwebui.feedback_pipeline import (
    fetch_openwebui_feedback_export as _owui_fetch,
    sync_openwebui_feedback_export as _owui_sync,
)
LOGS_DIR = Path(os.getenv("CONV_LOGS_DIR", "logs/conversations"))
LOGS_DIR.mkdir(parents=True, exist_ok=True)
FEEDBACK_LOGS_DIR = Path(os.getenv("FEEDBACK_LOGS_DIR", "logs/feedback"))
FEEDBACK_LOGS_DIR.mkdir(parents=True, exist_ok=True)
_OWUI_POLL_STATE = FEEDBACK_LOGS_DIR / "owui_seen_ids.json"
_OWUI_POLL_INTERVAL = int(os.getenv("OWUI_FEEDBACK_POLL_INTERVAL", "60"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("copepod.serve")


def _retry_after_seconds(exc: RateLimitError) -> int:
    raw = exc.response.headers.get("retry-after") if exc.response is not None else None
    try:
        return max(1, min(int(float(raw)), 60))
    except (TypeError, ValueError):
        return 1


def _provider_rate_limit_payload(exc: RateLimitError) -> dict:
    return {
        "error": {"code": "provider_rate_limit", "retryable": True},
        "retry_after": _retry_after_seconds(exc),
    }


def _provider_rate_limit_response(exc: RateLimitError) -> JSONResponse:
    retry_after = _retry_after_seconds(exc)
    return JSONResponse(
        status_code=429,
        headers={"Retry-After": str(retry_after)},
        content={"error": {"code": "provider_rate_limit", "retryable": True}},
    )


def _normalize_postgres_dsn_for_langgraph(dsn: str) -> str:
    """Convert SQLAlchemy PostgreSQL URLs to psycopg/libpq-compatible URLs."""
    return re.sub(r"^postgresql\+[^:]+://", "postgresql://", dsn.strip())


def _log_feedback_event(event: str, thread_id: str | None = None, **fields) -> None:
    """Écrit un audit JSONL dédié pour le chemin feedback → LangSmith."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "thread_id": thread_id,
        **fields,
    }
    path = FEEDBACK_LOGS_DIR / "feedback_events.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    logger.info(
        "[feedback] event=%s thread=%s chat_id=%s run_id=%s score=%s reason=%s",
        event,
        thread_id,
        fields.get("chat_id"),
        fields.get("run_id"),
        fields.get("score"),
        fields.get("reason"),
    )


class _RunIdCaptureCallback(BaseCallbackHandler):
    """Capture le run racine LangSmith d'un thread pour relier le feedback."""

    def __init__(self, thread_id: str, message_id: str | None = None, chat_id: str | None = None) -> None:
        self._thread_id = thread_id
        self._message_id = message_id
        self._chat_id = chat_id

    def on_chain_start(
        self,
        serialized: dict,
        inputs: dict,
        *,
        run_id,
        parent_run_id=None,
        **kwargs,
    ) -> None:
        if parent_run_id is None:
            default_run_store.set(self._thread_id, str(run_id), chat_id=self._chat_id)
            if self._message_id:
                default_run_store.set_for_message(self._message_id, str(run_id))
            _log_feedback_event(
                "capture_run_id",
                self._thread_id,
                run_id=str(run_id),
                message_id=self._message_id,
                chat_id=self._chat_id,
                parent_run_id=str(parent_run_id) if parent_run_id is not None else None,
            )


def _request_callbacks(thread_id: str, message_id: str | None = None, chat_id: str | None = None, config: dict | None = None) -> list:
    callbacks = list((config or {}).get("callbacks") or [])
    callbacks.append(_RunIdCaptureCallback(thread_id, message_id=message_id, chat_id=chat_id))
    return callbacks


def _log_turn(thread_id: str, user_msg: str, assistant_msg: str, usage: dict, user_id: str = "anonymous") -> None:
    context_audit = get_context_audit(thread_id)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "thread_id": thread_id,
        "user_id": user_id,
        "user": user_msg,
        "assistant": assistant_msg,
        "usage": usage,
        "context_audit": context_audit,
    }
    log_path = LOGS_DIR / f"{thread_id}.jsonl"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    logger.info(
        "thread=%s prompt=%s completion=%s cached=%s ctx_before=%s ctx_after=%s ctx_trimmed=%s tool_truncated=%s",
        thread_id,
        usage.get("prompt_tokens", 0),
        usage.get("completion_tokens", 0),
        usage.get("prompt_tokens_details", {}).get("cached_tokens", 0),
        context_audit.get("approx_tokens_before", 0),
        context_audit.get("approx_tokens_after_trim", 0),
        context_audit.get("messages_trimmed", 0),
        context_audit.get("tool_messages_truncated", 0),
    )


async def _poll_openwebui_feedbacks_once(
    *,
    state_path: Path | None = None,
    backend_url: str = "http://localhost:8000",
) -> dict:
    owui_url = os.getenv("OPENWEBUI_URL", "").rstrip("/")
    if not owui_url:
        return {"skipped": "OPENWEBUI_URL not set"}

    auth_token = os.getenv("OPENWEBUI_ADMIN_TOKEN") or os.getenv("OPENWEBUI_TOKEN")
    sp = state_path or _OWUI_POLL_STATE
    try:
        records = _owui_fetch(owui_url, auth_token=auth_token)
        result = _owui_sync(records, backend_url, state_path=sp)
        if result["forwarded"] > 0:
            logger.info("owui_feedback_poll forwarded=%s skipped=%s", result["forwarded"], result["skipped"])
        return result
    except Exception as exc:
        logger.warning("owui_feedback_poll error: %s", exc)
        return {"error": str(exc)}


async def _feedback_polling_loop() -> None:
    await asyncio.sleep(10)  # attendre que le serveur soit prêt
    while True:
        await _poll_openwebui_feedbacks_once()
        await asyncio.sleep(_OWUI_POLL_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize checkpointer + long-term memory store + feedback polling."""
    import agent as _agent_module

    async def _start_polling():
        task = asyncio.create_task(_feedback_polling_loop())
        try:
            yield
        finally:
            task.cancel()

    # ── PostgreSQL long-term memory store ──────────────────────────────────────
    pg_dsn_raw = os.getenv("SESSION_STORE_DATABASE_URL", "")
    pg_dsn = _normalize_postgres_dsn_for_langgraph(pg_dsn_raw)
    if pg_dsn:
        try:
            from langgraph.store.postgres import AsyncPostgresStore
            from langmem import create_memory_store_manager
            async with AsyncPostgresStore.from_conn_string(pg_dsn) as pg_store:
                await pg_store.setup()
                _agent_module._store = pg_store
                from langchain_openai import ChatOpenAI as _ChatOpenAI
                _mem_llm = _ChatOpenAI(model=os.getenv("LLM_MODEL", "gpt-4o-mini"), max_retries=1)
                _agent_module._memory_manager = create_memory_store_manager(
                    _mem_llm,
                    store=pg_store,
                    namespace=("memories", "{langgraph_user_id}"),
                    enable_inserts=True,
                    enable_deletes=False,
                )
                logger.info("AsyncPostgresStore ready (long-term memory)")
                # ── SQLite short-term checkpointer ──────────────────────────────
                try:
                    import aiosqlite
                    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
                    async with AsyncSqliteSaver.from_conn_string(str(_CHECKPOINTS_DB)) as cp:
                        _agent_module._checkpointer = cp
                        logger.info("SQLite checkpointer ready: %s", _CHECKPOINTS_DB)
                        poll_task = asyncio.create_task(_feedback_polling_loop())
                        try:
                            yield
                        finally:
                            poll_task.cancel()
                except Exception as e:
                    logger.warning("AsyncSqliteSaver unavailable (%s) — using MemorySaver", e)
                    poll_task = asyncio.create_task(_feedback_polling_loop())
                    try:
                        yield
                    finally:
                        poll_task.cancel()
        except Exception as e:
            logger.warning("AsyncPostgresStore unavailable (%s) — memory disabled", e)
            # Fall through to SQLite-only path
            pg_dsn = ""

    if not pg_dsn:
        try:
            import aiosqlite
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
            async with AsyncSqliteSaver.from_conn_string(str(_CHECKPOINTS_DB)) as cp:
                _agent_module._checkpointer = cp
                logger.info("SQLite checkpointer ready: %s", _CHECKPOINTS_DB)
                poll_task = asyncio.create_task(_feedback_polling_loop())
                try:
                    yield
                finally:
                    poll_task.cancel()
        except Exception as e:
            logger.warning("AsyncSqliteSaver unavailable (%s) — using MemorySaver", e)
            poll_task = asyncio.create_task(_feedback_polling_loop())
            try:
                yield
            finally:
                poll_task.cancel()


app = FastAPI(title="Copepod Agent API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

GRAPHS_DIR = Path("/tmp/copepod_graphs")
GRAPHS_DIR.mkdir(exist_ok=True)

def _extract_and_host_images(text: str) -> str:
    """Remplace les data URIs base64 par des URLs hébergées sur /graphs/."""
    def replace(match):
        b64 = match.group(1).replace("\n", "").replace(" ", "")
        # Rétablit le padding si manquant
        b64 += "=" * (-len(b64) % 4)
        graph_id = uuid.uuid4().hex[:12]
        path = GRAPHS_DIR / f"{graph_id}.png"
        path.write_bytes(base64.b64decode(b64))
        url = graph_url(f"{graph_id}.png")
        return (
            f"![graphe]({url})\n\n"
            f"[⬇ Télécharger le graphe]({url})"
        )
    # re.DOTALL pour capturer les base64 multi-lignes
    return re.sub(
        r"!\[.*?\]\(data:image/png;base64,([A-Za-z0-9+/=\n\s]+?)\)",
        replace,
        text,
        flags=re.DOTALL,
    )

class Message(BaseModel):
    role: str
    content: str | list  # list = format multimodal OpenAI (Open WebUI file upload)

    def text(self) -> str:
        """Extrait le texte pur, quel que soit le format content."""
        if isinstance(self.content, str):
            return self.content
        # Format liste : [{"type": "text", "text": "..."}, {"type": "image_url", ...}]
        parts = [p.get("text", "") for p in self.content if isinstance(p, dict) and p.get("type") == "text"]
        return " ".join(parts).strip()


def _prepare_user_content(message: Message | None) -> str | list:
    """Prépare le contenu utilisateur sans perdre les images Open WebUI."""
    if message is None:
        return ""
    if isinstance(message.content, str):
        return resolve_attached_files(message.content)

    prepared: list = []
    for part in message.content:
        if isinstance(part, dict) and part.get("type") == "text":
            updated = dict(part)
            updated["text"] = resolve_attached_files(str(updated.get("text", "")))
            prepared.append(updated)
        else:
            prepared.append(part)
    return prepared


class ChatRequest(BaseModel):
    model: str = "copepod-agent"
    messages: list[Message]
    stream: bool = False
    chat_id: str | None = None
    session_id: str | None = None
    metadata: dict | None = None
    files: list | None = None


def _conversation_key(
    messages: list[Message] | list[str],
    *,
    chat_id: str | None = None,
    session_id: str | None = None,
    metadata: dict | None = None,
    user_id: str = "anonymous",
) -> str:
    """Retourne la clé stable de conversation, puis le fallback sur le premier message."""
    if chat_id:
        return f"{user_id}:{chat_id}"
    if session_id:
        return f"{user_id}:{session_id}"
    if isinstance(metadata, dict):
        for key in ("chat_id", "conversation_id", "session_id"):
            value = metadata.get(key)
            if value:
                return f"{user_id}:{value}"

    # No stable identifier — generate a UUID rather than using message content.
    # Using message content as a key causes thread collisions when multiple
    # conversations start with the same text (e.g. "yo").
    logger.warning("No chat_id/session_id in request — generating ephemeral thread UUID")
    return str(uuid.uuid4())


def _thread_id(
    messages: list[Message],
    *,
    chat_id: str | None = None,
    session_id: str | None = None,
    metadata: dict | None = None,
    user_id: str = "anonymous",
) -> str:
    """Thread stable basé sur l'identité de conversation ou le premier message."""
    key = _conversation_key(
        messages,
        chat_id=chat_id,
        session_id=session_id,
        metadata=metadata,
        user_id=user_id,
    )
    return hashlib.md5(key[:200].encode()).hexdigest()[:16]


@app.get("/")
def root():
    return {"status": "ok", "agent": "copepod-agent"}


@app.get("/version")
def version():
    return {"agent": "copepod-agent", "sha": os.getenv("GIT_SHA", "unknown")}


@app.get("/debug/context-audit")
def debug_context_audit(thread_id: str | None = None):
    """Expose latest context-management audit metrics."""
    return {
        "thread_id": thread_id,
        "audit": get_context_audit(thread_id),
    }


@app.get("/v1/models")
def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": "copepod-agent",
                "object": "model",
                "owned_by": "neolab",
                "name": "Assistant Copépodes — NeoLab",
                "description": (
                    "Assistant scientifique spécialisé en zooplancton marin (copépodes). "
                    "Explore et analyse les données EcoTaxa (LOKI, UVP5), EcoPart et CTD Amundsen. "
                    "Répond en français à des questions scientifiques sans écrire de code."
                ),
            }
        ],
    }


@app.post("/v1/embeddings")
async def embeddings(request: Request):
    """Dummy embeddings endpoint — returns zero vectors instantly.

    OpenWebUI calls this when RAG_EMBEDDING_ENGINE=openai. Since we use
    resolve_attached_files + load_file to handle uploads, we never need
    real embeddings. Returning zeros in <1ms eliminates the multi-minute
    sentence-transformers processing that blocks the upload UI.
    """
    body = await request.json()
    inputs = body.get("input", [])
    if isinstance(inputs, str):
        inputs = [inputs]
    DIM = 384  # matches all-MiniLM-L6-v2 so ChromaDB stays consistent
    return {
        "object": "list",
        "model": body.get("model", "copepod-embeddings"),
        "data": [
            {"object": "embedding", "index": i, "embedding": [0.0] * DIM}
            for i in range(len(inputs))
        ],
        "usage": {"prompt_tokens": 0, "total_tokens": 0},
    }


_INTERNAL_PREFIXES = ("### Task:", "### Guidelines:", "### Input:", "### Output:")


def _is_internal_prompt(text: str) -> bool:
    return any(text.strip().startswith(p) for p in _INTERNAL_PREFIXES)


def _is_sql_workspace_config_message(text: str, database_url: str) -> bool:
    stripped = (text or "").strip()
    if not stripped or not database_url:
        return False
    return stripped in {database_url, f"DATABASE_URL={database_url}", f"sql_database_url={database_url}"}


def _quick_response(text: str) -> dict:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "model": "copepod-agent",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


# ── SSE streaming helpers ──────────────────────────────────────────────────────

def _make_sse_chunk(completion_id: str, content: str, finish_reason=None) -> str:
    """Formate un chunk SSE OpenAI-compatible."""
    delta = {"content": content} if content else {}
    chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "model": "copepod-agent",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"


async def _quick_sse_response(content: str) -> AsyncGenerator[str, None]:
    """SSE minimal pour les réponses rapides (prompts internes, erreurs)."""
    cid = f"chatcmpl-{uuid.uuid4().hex[:8]}"
    if content:
        yield _make_sse_chunk(cid, content)
    yield _make_sse_chunk(cid, "", finish_reason="stop")
    yield "data: [DONE]\n\n"


def _format_tool_line(name: str, args: dict | None = None) -> str:
    """Formate une étape outil pour le stream SSE.

    - run_graph / run_pandas : bloc replié avec le code Python
    - load_file : affiche le nom du fichier
    - skill_tool : affiche le nom du skill
    - autres : bloc replié avec paramètres utiles
    """
    args = args or {}

    if name in ("run_graph", "run_pandas") and "code" in args:
        code = args["code"]
        body = f"```python\n{code}\n```"
        if name == "run_graph":
            body = f"{body}\n\n*Génération du graphique...*"
        return _format_tool_call_details(name, body)

    if name == "load_file" and "path" in args:
        filename = Path(args["path"]).name
        return _format_tool_call_details(name, f"Paramètres : path=`{filename}`")

    if name == "load_skill" and "skill_name" in args:
        skill = args["skill_name"]
        return _format_tool_call_details(name, f"Paramètres : skill_name=`{skill}`")

    if name in _ENRICHMENT_PROGRESS_LABELS:
        return _format_enrichment_progress_panel(name, args)

    if name in ("query_ecotaxa", "query_ecotaxa_sample", "query_ecopart"):
        params = _format_tool_call_params(args)
        body = f"Paramètres : {params}" if params else ""
        if name == "query_ecotaxa":
            status = "Export EcoTaxa en cours — cela peut prendre 1–2 minutes..."
        elif name == "query_ecotaxa_sample":
            status = "Export EcoTaxa sample en cours — cela peut prendre 1–2 minutes..."
        else:
            status = "Téléchargement EcoPart en cours — cela peut prendre 1–2 minutes..."
        body = f"{body}\n\n*{status}*".strip()
        return (
            _format_tool_call_details(
                name,
                body,
                summary_note="export EcoTaxa en cours",
            )
        )

    if name == "export_ecotaxa_samples":
        params = _format_tool_call_params(args)
        body = f"Paramètres : {params}" if params else ""
        # Only the real export (confirmed=true) is slow; the confirmed=false
        # dry-run returns instantly and must not advertise a running export.
        if args and args.get("confirmed"):
            body = f"{body}\n\n*Export EcoTaxa (sélection) en cours — cela peut prendre 1–2 minutes...*".strip()
            return _format_tool_call_details(name, body, summary_note="export EcoTaxa en cours")
        return _format_tool_call_details(name, body)

    if name in ("query_bio_oracle", "couple_zooplankton_bio_oracle"):
        params = _format_tool_call_params(args)
        body = f"Paramètres : {params}" if params else ""
        body = f"{body}\n\n*Export Bio-ORACLE en cours — cela peut prendre 1–2 minutes...*".strip()
        return (
            _format_tool_call_details(name, body, summary_note="export Bio-ORACLE en cours")
        )

    if name == "query_amundsen_ctd":
        params = _format_tool_call_params(args)
        body = f"Paramètres : {params}" if params else ""
        body = f"{body}\n\n*Export Amundsen CTD en cours — cela peut prendre 1–2 minutes...*".strip()
        return (
            _format_tool_call_details(name, body, summary_note="export Amundsen CTD en cours")
        )

    params = _format_tool_call_params(args)
    body = f"Paramètres : {params}" if params else "Paramètres : —"
    return _format_tool_call_details(name, body)


def _format_tool_call_details(name: str, body: str, *, summary_note: str = "") -> str:
    return (
        "\n<details>\n"
        f"<summary>{name}</summary>\n\n"
        f"{body}\n\n"
        "</details>\n"
    )


_ENRICHMENT_PROGRESS_LABELS = {
    "enrich_loaded_table_with_amundsen_ctd": "Préparation de l'enrichissement CTD",
    "enrich_with_amundsen_ctd": "Préparation de l'enrichissement CTD",
    "enrich_with_bio_oracle": "Préparation de l'enrichissement Bio-ORACLE",
    "enrich_ecotaxa_with_ecopart_remote": "Préparation du jumelage EcoTaxa/EcoPart",
    "enrich_with_ogsl": "Préparation de l'enrichissement OGSL",
}

def _format_enrichment_progress_panel(name: str, args: dict | None = None) -> str:
    args = args or {}
    label = _ENRICHMENT_PROGRESS_LABELS.get(name, "Préparation de l'enrichissement")
    params = _format_tool_call_params(args)
    body = f"*{label}…*"
    if params:
        body = f"Paramètres : {params}\n\n{body}"
    body = (
        f"{body}\n\n"
        "Le cache de données sera vérifié automatiquement avant le calcul."
    )
    return _format_tool_call_details(name, body)


_TOOL_LINE_OMITTED_ARGS = {
    "code",
    "polygon_wkt",
    "content",
    "data",
}
_TOOL_LINE_SECRET_PARTS = (
    "key",
    "token",
    "secret",
    "password",
    "credential",
)


def _format_tool_call_params(args: dict | None, *, max_len: int = 220) -> str:
    """Compact, user-visible argument summary for streamed tool calls."""
    if not args:
        return ""

    visible: dict[str, object] = {}
    for key, value in args.items():
        lowered = str(key).lower()
        if lowered in _TOOL_LINE_OMITTED_ARGS:
            continue
        if any(part in lowered for part in _TOOL_LINE_SECRET_PARTS):
            visible[key] = "[secret]"
            continue
        visible[key] = _compact_tool_arg_value(value)

    if not visible:
        return ""
    text = ", ".join(
        f"{key}={_format_tool_arg_literal(value)}"
        for key, value in visible.items()
    )
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def _compact_tool_arg_value(value):
    if isinstance(value, str):
        compact = " ".join(value.split())
        return compact if len(compact) <= 80 else compact[:79] + "…"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        if len(value) <= 8:
            return [_compact_tool_arg_value(v) for v in value]
        return [_compact_tool_arg_value(v) for v in value[:8]] + [f"... +{len(value) - 8}"]
    if isinstance(value, dict):
        return {
            str(k): _compact_tool_arg_value(v)
            for k, v in value.items()
            if str(k).lower() not in _TOOL_LINE_OMITTED_ARGS
        }
    return str(value)


def _format_tool_arg_literal(value) -> str:
    if isinstance(value, str):
        return f"`{value}`"
    return f"`{json.dumps(value, ensure_ascii=False, default=str)}`"


_SLOW_TOOLS = frozenset({
    "query_ecotaxa", "query_ecotaxa_sample", "export_ecotaxa_samples",
    "query_ecopart", "query_amundsen_ctd",
    "query_bio_oracle", "couple_zooplankton_bio_oracle", "query_ogsl",
    "enrich_loaded_table_with_amundsen_ctd",
    "enrich_with_amundsen_ctd",
    "enrich_with_bio_oracle",
    "enrich_ecotaxa_with_ecopart_remote",
    "enrich_with_ogsl",
    "load_file", "export_deliverable",
})
_HEARTBEAT_INTERVAL = 8.0  # seconds between SSE keepalive pings during slow tools

# Tools whose textual result is shown inline in the SSE stream inside a
# collapsible <details> block, so the user can inspect what the source actually
# returned (tables, project lists, schema, download links). The agent already
# paraphrases this in its final answer — the block is for transparency.
_DATA_SOURCE_TOOL_PREFIXES = (
    "list_ecotaxa", "preview_ecotaxa", "query_ecotaxa", "find_ecotaxa",
    "inspect_ecotaxa", "count_ecotaxa", "compare_ecotaxa", "get_ecotaxa",
    "summarize_ecotaxa", "export_ecotaxa",
    "list_ecopart", "preview_ecopart", "query_ecopart", "join_ecotaxa_ecopart",
    "list_amundsen", "preview_amundsen", "query_amundsen",
    "enrich_loaded_table_with_amundsen",
    "list_bio_oracle", "preview_bio_oracle", "query_bio_oracle",
    "couple_zooplankton_bio_oracle",
    "query_ogsl",
    "list_sql", "preview_sql", "copy_sql",
)


def _is_data_source_tool(name: str) -> bool:
    return any(name == p or name.startswith(p) for p in _DATA_SOURCE_TOOL_PREFIXES)


# Libellés FR pour le <summary> du bloc collapsible — pas de nom interne
# (cf. CLAUDE.md « pas de nom de tool exposé »).
_ECOTAXA_BASE_URL = "https://ecotaxa.obs-vlfr.fr"

_ECOTAXA_TOOL_LABELS = {
    "find_ecotaxa_projects":           "EcoTaxa · recherche de projets",
    "list_ecotaxa_projects":           "EcoTaxa · projets accessibles",
    "preview_ecotaxa_project":         "EcoTaxa · aperçu de projet",
    "query_ecotaxa":                   "EcoTaxa · export de projet",
    "query_ecotaxa_sample":            "EcoTaxa · export de sample",
    "inspect_ecotaxa_project_schema":  "EcoTaxa · schéma de projet",
    "count_ecotaxa_taxa":              "EcoTaxa · comptage par taxon",
    "inspect_ecotaxa_column":          "EcoTaxa · inspection de colonne",
    "compare_ecotaxa_projects":        "EcoTaxa · comparaison de projets",
    "find_ecotaxa_samples_in_region":  "EcoTaxa · samples par zone / période",
    "find_ecotaxa_projects_in_region": "EcoTaxa · projets par zone / période",
    "rank_ecotaxa_samples_by_region":  "EcoTaxa · classement samples par zone",
    "find_ecotaxa_observations":       "EcoTaxa · observations par taxon",
    "get_ecotaxa_sample":              "EcoTaxa · métadonnées de sample",
    "summarize_ecotaxa_sample_deployment": "EcoTaxa · déploiement de sample",
    "summarize_ecotaxa_samples":        "EcoTaxa · résumé de samples",
    "summarize_ecotaxa_sample":         "EcoTaxa · résumé de sample",
    "summarize_ecotaxa_projects":       "EcoTaxa · résumé de projets",
    "summarize_ecotaxa_project":        "EcoTaxa · résumé de projet",
    "export_ecotaxa_samples":           "EcoTaxa · export de samples",
}


def _format_args_summary(name: str, args: dict | None) -> str:
    """Résume les arguments saillants d'un tool pour le titre du bloc."""
    if not args:
        return ""
    parts: list[str] = []
    if (project_id := args.get("project_id")) is not None:
        parts.append(f"projet {project_id}")
    if (sample_id := args.get("sample_id")) is not None:
        parts.append(f"sample {sample_id}")
    if zone := args.get("zone_name"):
        parts.append(str(zone))
    if instrument := args.get("instrument"):
        parts.append(str(instrument))
    if taxon := args.get("taxon"):
        parts.append(str(taxon))
    if (dr := args.get("date_range")) and isinstance(dr, dict):
        a, b = dr.get("from"), dr.get("to")
        if a and b:
            parts.append(f"{a} → {b}")
        elif a:
            parts.append(f"≥ {a}")
        elif b:
            parts.append(f"≤ {b}")
    if (bbox := args.get("bbox")) and isinstance(bbox, dict):
        try:
            parts.append(
                f"bbox {bbox['south']:.1f}/{bbox['west']:.1f}"
                f"→{bbox['north']:.1f}/{bbox['east']:.1f}"
            )
        except (KeyError, TypeError, ValueError):
            pass
    return " · ".join(parts)


def _linkify_ecotaxa(content: str) -> str:
    """Rend les `project_id` / `sample_id` cliquables vers EcoTaxa.

    URL canonique :
    - projet → ``/prj/{project_id}``
    - sample → ``/prj/{project_id}?samples={sample_id}`` (EcoTaxa n'a pas
      de page sample isolée ; on ouvre le projet filtré sur le sample).

    Si la ligne d'un sample n'a pas de colonne projet, le sample reste en
    texte brut (lien impossible à fabriquer correctement).
    """
    base = _ECOTAXA_BASE_URL
    lines = content.split("\n")

    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("|") and any(
            tok in ln for tok in ("sample_id", "project_id", "projet")
        ):
            cols = [c.strip().lower() for c in ln.strip("|").split("|")]
            sample_idx = next((k for k, c in enumerate(cols) if c == "sample_id"), None)
            project_idx = next(
                (k for k, c in enumerate(cols) if c in ("project_id", "projet")),
                None,
            )
            if sample_idx is None and project_idx is None:
                i += 1
                continue
            # Saute la ligne de séparation markdown (|---|---|...)
            j = i + 2
            while j < len(lines) and lines[j].startswith("|"):
                cells = [c.strip() for c in lines[j].strip("|").split("|")]
                if len(cells) < len(cols):
                    j += 1
                    continue
                project_id_value = (
                    cells[project_idx]
                    if project_idx is not None and cells[project_idx].isdigit()
                    else None
                )
                if (
                    sample_idx is not None
                    and cells[sample_idx].isdigit()
                    and project_id_value is not None
                ):
                    sid = cells[sample_idx]
                    cells[sample_idx] = (
                        f"[{sid}]({base}/prj/{project_id_value}?samples={sid})"
                    )
                if project_idx is not None and project_id_value is not None:
                    cells[project_idx] = (
                        f"[{project_id_value}]({base}/prj/{project_id_value})"
                    )
                lines[j] = "| " + " | ".join(cells) + " |"
                j += 1
            i = j
            continue
        i += 1

    return "\n".join(lines)


def _format_tool_result_details(name: str, content: str, args: dict | None = None) -> str:
    """Wrap a tool result in a collapsed <details> block for Open WebUI."""
    # Hide raw base64 image payloads (handled separately by image extraction).
    display = re.sub(
        r"data:image/[a-z]+;base64,[A-Za-z0-9+/=]+",
        "[image data]",
        content,
    )

    if "CACHE_EMPTY" in display:
        display = (
            "Cache EcoTaxa vide\n\n"
            "La synchronisation initiale n'a pas encore rempli le cache local.\n"
            "Relancer l'enrichissement une fois la synchro terminée."
        )
    elif "SYNC_IN_PROGRESS" in display:
        display = (
            "Synchronisation en cours\n\n"
            "La source est en train d'être synchronisée. "
            "L'enrichissement reprendra quand le cache sera prêt."
        )

    is_ecotaxa = name in _ECOTAXA_TOOL_LABELS
    if is_ecotaxa:
        display = _linkify_ecotaxa(display)
        label = _ECOTAXA_TOOL_LABELS[name]
        suffix = _format_args_summary(name, args)
        summary = f"{label}" + (f" — {suffix}" if suffix else "")
        source_line = f"\n\n*Source : EcoTaxa — [{_ECOTAXA_BASE_URL}]({_ECOTAXA_BASE_URL})*"
    else:
        summary = f"Résultat de {name}"
        source_line = ""

    return (
        f"\n<details>\n"
        f"<summary>{summary}</summary>\n\n"
        f"{display}{source_line}\n\n"
        f"</details>\n"
    )


def _has_graph_markdown_image(text: str) -> bool:
    return bool(re.search(r"!\[[^\]]*\]\([^\)]*/graphs/[^\)]*\.png\)", text))


def _graph_image_urls(text: str) -> set[str]:
    return set(re.findall(r"!\[[^\]]*\]\(([^\)]*/graphs/[^\)]*\.png)\)", text))


def _remove_graph_markdown_images(text: str, urls: set[str]) -> str:
    if not urls:
        return text

    def _replace(match: re.Match) -> str:
        return "" if match.group(1) in urls else match.group(0)

    deduped = re.sub(r"!\[[^\]]*\]\(([^\)]*/graphs/[^\)]*\.png)\)", _replace, text)
    return re.sub(r"\n{3,}", "\n\n", deduped).strip()


async def _stream_agent_sse(
    agent,
    messages: dict,
    config: dict,
    thread_id: str,
    last_user_text: str = "",
    user_id: str = "anonymous",
) -> AsyncGenerator[str, None]:
    """Génère les chunks SSE depuis l'agent LangGraph (stream_mode='updates').

    Utilise une queue + timeout pour émettre des battements pendant les tools lents,
    sans bloquer le générateur SSE.
    """
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
    chunk_queue: asyncio.Queue[str | None] = asyncio.Queue()
    shared: dict = {
        "last_ai_msg": None,
        # in_slow_tool only gates the SSE keepalive during long tool calls;
        # the "en cours…" notice lives once in the tool's <details> panel.
        "in_slow_tool": False,
        "pending_tool_args": {},
        "pending_tool_names": {},
        "streamed_graph_urls": set(),
    }

    async def _run_agent() -> None:
        try:
            async for update in agent.astream(messages, config, stream_mode="updates"):
                if "__run_id" in update:
                    default_run_store.set(thread_id, str(update["__run_id"]))
                for node, state in update.items():
                    msgs = state.get("messages", [])
                    if not msgs:
                        continue
                    last_msg = msgs[-1]

                    if node == "model":
                        shared["last_ai_msg"] = last_msg
                        content = getattr(last_msg, "content", "") or ""
                        tool_calls = getattr(last_msg, "tool_calls", []) or []

                        if content and not tool_calls:
                            content = _extract_and_host_images(content)
                            content = _remove_graph_markdown_images(
                                content,
                                shared["streamed_graph_urls"],
                            )
                            await chunk_queue.put(_make_sse_chunk(completion_id, content))

                        for tc in tool_calls:
                            name = tc["name"] if isinstance(tc, dict) else tc.name
                            tc_args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                            tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                            if tc_id:
                                shared["pending_tool_args"][tc_id] = tc_args
                                shared["pending_tool_names"][tc_id] = name
                            await chunk_queue.put(_make_sse_chunk(completion_id, _format_tool_line(name, tc_args)))
                            shared["in_slow_tool"] = name in _SLOW_TOOLS

                    elif node == "tools":
                        shared["in_slow_tool"] = False
                        for tool_msg in msgs:
                            tool_content = getattr(tool_msg, "content", "") or ""
                            tool_name = getattr(tool_msg, "name", "") or ""
                            tool_call_id = getattr(tool_msg, "tool_call_id", None)
                            tool_args = shared["pending_tool_args"].pop(tool_call_id, None) if tool_call_id else None
                            if not tool_name and tool_call_id:
                                tool_name = shared["pending_tool_names"].pop(tool_call_id, "")
                            elif tool_call_id:
                                shared["pending_tool_names"].pop(tool_call_id, None)
                            if tool_name == "run_graph" and tool_content:
                                hosted = _extract_and_host_images(tool_content)
                                if _has_graph_markdown_image(hosted):
                                    shared["streamed_graph_urls"].update(_graph_image_urls(hosted))
                                    await chunk_queue.put(_make_sse_chunk(completion_id, f"\n{hosted}\n"))
                            elif "data:image/png;base64," in tool_content:
                                hosted = _extract_and_host_images(tool_content)
                                img_match = re.search(r"!\[.*?\]\(http[^\)]+\)", hosted)
                                if img_match:
                                    shared["streamed_graph_urls"].update(_graph_image_urls(img_match.group(0)))
                                    await chunk_queue.put(_make_sse_chunk(completion_id, f"\n{img_match.group(0)}\n"))
                            if tool_name and tool_content and _is_data_source_tool(tool_name):
                                await chunk_queue.put(_make_sse_chunk(
                                    completion_id,
                                    _format_tool_result_details(tool_name, tool_content, tool_args),
                                ))
        except RateLimitError as exc:
            retry_after = _retry_after_seconds(exc)
            logger.warning(
                "provider_rate_limit thread=%s retry_after=%s",
                thread_id,
                retry_after,
            )
            await chunk_queue.put(
                "data: "
                + json.dumps(_provider_rate_limit_payload(exc), ensure_ascii=False)
                + "\n\n"
            )
        except Exception as exc:
            logger.error("stream_error thread=%s err=%s", thread_id, exc)
            await chunk_queue.put(_make_sse_chunk(completion_id, f"\n\n[Erreur : {exc}]"))
        finally:
            await chunk_queue.put(None)  # sentinel

    agent_task = asyncio.create_task(_run_agent())

    while True:
        try:
            chunk = await asyncio.wait_for(chunk_queue.get(), timeout=_HEARTBEAT_INTERVAL)
        except asyncio.TimeoutError:
            # Keep the SSE connection warm during long tool calls without
            # polluting the message: a comment line (":") is ignored by the
            # client and never appended to the assistant content.
            if shared["in_slow_tool"]:
                yield ": keepalive\n\n"
            continue
        if chunk is None:
            break
        yield chunk

    await agent_task

    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
             "prompt_tokens_details": {"cached_tokens": 0}}

    last_ai_msg = shared["last_ai_msg"]
    if last_ai_msg is not None:
        meta = getattr(last_ai_msg, "usage_metadata", None) or {}
        rmeta = getattr(last_ai_msg, "response_metadata", {}) or {}
        prompt_tokens     = meta.get("input_tokens", 0)
        completion_tokens = meta.get("output_tokens", 0)
        cached_tokens = (
            rmeta.get("token_usage", {}).get("prompt_tokens_details", {}).get("cached_tokens", 0)
            or meta.get("input_token_details", {}).get("cache_read", 0)
        )
        usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "prompt_tokens_details": {"cached_tokens": cached_tokens},
        }
        final_text = getattr(last_ai_msg, "content", "") or ""
        _log_turn(thread_id, last_user_text, final_text, usage, user_id=user_id)
        if cached_tokens > 0:
            logger.info("CACHE HIT thread=%s cached=%s (%.0f%% of prompt)",
                thread_id, cached_tokens, 100 * cached_tokens / prompt_tokens if prompt_tokens else 0)

        # ── long-term memory extraction (background, non-blocking) ────────────
        import agent as _agent_module
        mgr = getattr(_agent_module, "_memory_manager", None)
        if mgr and last_user_text and final_text:
            from langchain_core.messages import HumanMessage, AIMessage as _AI
            mem_messages = [HumanMessage(content=last_user_text), _AI(content=final_text)]
            mem_config = {"configurable": {"langgraph_user_id": user_id}}
            asyncio.create_task(mgr.ainvoke({"messages": mem_messages}, config=mem_config))

    # Chunk final avec usage — Open WebUI l'affiche en bas du message
    stop_chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "model": "copepod-agent",
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        "usage": usage,
    }
    yield f"data: {json.dumps(stop_chunk, ensure_ascii=False)}\n\n"
    logger.info("thread=%s STREAM done", thread_id)
    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def chat_completions(
    req: ChatRequest,
    request: Request,
    x_openwebui_chat_id: str | None = Header(default=None, alias="X-OpenWebUI-Chat-Id"),
    x_openwebui_message_id: str | None = Header(default=None, alias="X-OpenWebUI-Message-Id"),
    x_openwebui_user_id: str | None = Header(default=None, alias="X-OpenWebUI-User-Id"),
    x_openwebui_user_name: str | None = Header(default=None, alias="X-OpenWebUI-User-Name"),
    x_openwebui_user_email: str | None = Header(default=None, alias="X-OpenWebUI-User-Email"),
    x_openwebui_user_role: str | None = Header(default=None, alias="X-OpenWebUI-User-Role"),
):
    user_id = x_openwebui_user_id if isinstance(x_openwebui_user_id, str) else "anonymous"
    openwebui_message_id = _openwebui_message_id(req, x_openwebui_message_id)
    tid = _thread_id(
        req.messages,
        chat_id=x_openwebui_chat_id or req.chat_id,
        session_id=req.session_id,
        metadata=req.metadata,
        user_id=user_id,
    )
    conversation_key = _conversation_key(
        req.messages,
        chat_id=x_openwebui_chat_id or req.chat_id,
        session_id=req.session_id,
        metadata=req.metadata,
        user_id=user_id,
    )
    logger.info(
        "completions_request thread=%s stream=%s has_chat_id=%s "
        "has_session_id=%s message_count=%s",
        tid,
        req.stream,
        bool(x_openwebui_chat_id or req.chat_id),
        bool(req.session_id),
        len(req.messages),
    )

    last_user = next((m for m in reversed(req.messages) if m.role == "user"), None)

    # OpenWebUI injects a RAG template ("### Task: ...") into the last user message when
    # files are attached. Detect it and restore the original user query from metadata,
    # which OpenWebUI saves before injecting the template.
    raw_last_user_text = last_user.text() if last_user else ""
    if _is_internal_prompt(raw_last_user_text):
        original_query = (req.metadata or {}).get("user_prompt", "")
        logger.info(
            "thread=%s RAG template detected restored_prompt_chars=%s",
            tid,
            len(original_query),
        )
        if last_user and original_query:
            last_user = Message(role="user", content=original_query)
        elif not original_query:
            # No recoverable query — skip silently (e.g. empty initialisation ping)
            logger.info("thread=%s SKIPPED empty RAG template with no user_prompt", tid)
            if req.stream:
                return StreamingResponse(_quick_sse_response(""), media_type="text/event-stream")
            return _quick_response("")

    last_user_text = resolve_attached_files(last_user.text() if last_user else "")

    # OpenWebUI ne forward JAMAIS les fichiers dans le body (metadata est pop()é
    # avant l'envoi). On requête directement le SQLite d'OpenWebUI via chat_id.
    # Fallback : req.files pour les appelants directs de l'API (hors OpenWebUI).
    owui_chat_id = x_openwebui_chat_id or req.chat_id
    if owui_chat_id:
        request_files_text, request_image_parts = resolve_chat_files(owui_chat_id, thread_id=tid)
    else:
        owui_files = (req.metadata or {}).get("files") or req.files
        request_files_text, request_image_parts = resolve_request_files(owui_files)
    if request_files_text or request_image_parts:
        logger.info(
            "thread=%s request_files: text_len=%d images=%d",
            tid, len(request_files_text), len(request_image_parts),
        )
    if request_files_text:
        last_user_text = f"{last_user_text}\n\n{request_files_text}".strip()
    last_user_content = _prepare_user_content(last_user)
    if request_files_text or request_image_parts:
        if isinstance(last_user_content, str):
            parts: list = []
            merged_text = last_user_content
            if request_files_text:
                merged_text = f"{merged_text}\n\n{request_files_text}".strip()
            if merged_text:
                parts.append({"type": "text", "text": merged_text})
            parts.extend(request_image_parts)
            last_user_content = parts if request_image_parts else merged_text
        else:
            extra: list = []
            if request_files_text:
                extra.append({"type": "text", "text": request_files_text})
            extra.extend(request_image_parts)
            last_user_content = list(last_user_content) + extra

    sql_database_url = extract_sql_workspace_database_url(last_user_text) or ""
    if sql_database_url:
        set_sql_workspace_database_url(tid, sql_database_url)
        logger.info("thread=%s SQL workspace configured", tid)
        if _is_sql_workspace_config_message(last_user_text, sql_database_url):
            confirmation = (
                "Workspace SQL configuré pour cette conversation.\n"
                "Vous pouvez maintenant lister les tables, prévisualiser une table, ou copier une requête read-only."
            )
            if req.stream:
                return StreamingResponse(_quick_sse_response(confirmation), media_type="text/event-stream")
            return _quick_response(confirmation)

    if _is_internal_prompt(last_user_text):
        logger.info("thread=%s SKIPPED internal prompt", tid)
        if req.stream:
            return StreamingResponse(_quick_sse_response(""), media_type="text/event-stream")
        return _quick_response("")

    agent = make_agent(tid, user_id=user_id)
    config = {
        "configurable": {"thread_id": tid, "langgraph_user_id": user_id},
        "metadata": {
            "conversation_key": conversation_key,
            "conversation_id": x_openwebui_chat_id or req.chat_id,
            "session_id": req.session_id,
            "message_id": openwebui_message_id,
            "user_id": user_id,
            "user_name": x_openwebui_user_name,
            "user_email": x_openwebui_user_email,
            "user_role": x_openwebui_user_role,
        },
        "callbacks": _request_callbacks(tid, openwebui_message_id, chat_id=x_openwebui_chat_id or req.chat_id),
    }
    messages = {"messages": [{"role": "user", "content": last_user_content}]}

    logger.info("thread=%s stream=%s", tid, req.stream)
    await arepair_invalid_tool_history(agent, config)
    if req.stream:
        logger.info("thread=%s STREAM start", tid)
        return StreamingResponse(
            _stream_agent_sse(agent, messages, config, tid, last_user_text=last_user_text, user_id=user_id),
            media_type="text/event-stream",
        )

    try:
        result = await agent.ainvoke(messages, config=config)
    except RateLimitError as exc:
        logger.warning(
            "provider_rate_limit thread=%s retry_after=%s",
            tid,
            _retry_after_seconds(exc),
        )
        return _provider_rate_limit_response(exc)

    # Capture run_id for feedback
    run_id = result.get("__run_id") or default_run_store.get(tid)
    if run_id:
        default_run_store.set(tid, str(run_id))
        logger.info("thread=%s captured_run_id=%s", tid, run_id)
        _log_feedback_event("captured_run_id", tid, run_id=str(run_id))

    text = _extract_and_host_images(result["messages"][-1].content)

    # Usage du dernier AIMessage uniquement (pas l'historique entier)
    prompt_tokens = completion_tokens = cached_tokens = 0
    for msg in reversed(result.get("messages", [])):
        meta = getattr(msg, "usage_metadata", None)
        if meta:
            prompt_tokens     = meta.get("input_tokens", 0)
            completion_tokens = meta.get("output_tokens", 0)
            # cached_tokens : priorité response_metadata (OpenRouter) > usage_metadata
            rmeta = getattr(msg, "response_metadata", {})
            cached_tokens = (
                rmeta.get("token_usage", {})
                     .get("prompt_tokens_details", {})
                     .get("cached_tokens", 0)
                or meta.get("input_token_details", {}).get("cache_read", 0)
            )
            break

    usage = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "prompt_tokens_details": {"cached_tokens": cached_tokens},
    }

    _log_turn(tid, last_user_text, text, usage, user_id=user_id)

    if cached_tokens > 0:
        logger.info("CACHE HIT thread=%s cached_tokens=%s (%.0f%% of prompt)",
            tid, cached_tokens,
            100 * cached_tokens / prompt_tokens if prompt_tokens else 0,
        )

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "model": "copepod-agent",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": usage,
    }


@app.get("/graphs/{filename}")
def serve_graph(filename: str):
    path = GRAPHS_DIR / filename
    if not path.exists() or path.suffix != ".png":
        from fastapi import HTTPException
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type="image/png", headers={
        "Content-Disposition": f"inline; filename={filename}"
    })


@app.get("/downloads/{filename}")
def serve_download(filename: str):
    from pathlib import Path as _Path
    downloads_dir = _Path("/tmp/copepod_downloads")
    path = downloads_dir / filename
    if not path.exists() or path.suffix not in {".tsv", ".csv", ".pdf", ".md", ".html"}:
        from fastapi import HTTPException
        raise HTTPException(status_code=404)
    media_types = {".tsv": "text/tab-separated-values", ".csv": "text/csv",
                   ".pdf": "application/pdf", ".md": "text/markdown", ".html": "text/html"}
    return FileResponse(path, media_type=media_types.get(path.suffix, "application/octet-stream"), headers={
        "Content-Disposition": f"attachment; filename={filename}"
    })


class FeedbackRequest(BaseModel):
    thread_id: str | None = None
    chat_id: str | None = None
    message_id: str | None = None
    score: int | None = None  # 1 = thumbs up, -1 = thumbs down
    rating: int | None = None
    comment: str | None = None
    reason: str | None = None
    type: str | None = None
    created_at: int | float | None = None  # Unix timestamp from Open WebUI SQLite
    data: dict | None = None
    meta: dict | None = None


def _feedback_thread_id(req: FeedbackRequest) -> str | None:
    if req.thread_id:
        return req.thread_id

    chat_id = req.chat_id
    if not chat_id and isinstance(req.meta, dict):
        chat_id = req.meta.get("chat_id")
    if not chat_id and isinstance(req.data, dict):
        chat_id = req.data.get("chat_id")
    if not chat_id:
        return None

    return hashlib.md5(str(chat_id)[:200].encode()).hexdigest()[:16]


def _feedback_message_id(req: FeedbackRequest) -> str | None:
    if req.message_id:
        return req.message_id
    if isinstance(req.meta, dict):
        value = req.meta.get("message_id")
        if value:
            return str(value)
    if isinstance(req.data, dict):
        value = req.data.get("message_id")
        if value:
            return str(value)
    return None


def _feedback_chat_id(req: FeedbackRequest) -> str | None:
    chat_id = req.chat_id
    if not chat_id and isinstance(req.meta, dict):
        chat_id = req.meta.get("chat_id")
    if not chat_id and isinstance(req.data, dict):
        chat_id = req.data.get("chat_id")
    return str(chat_id) if chat_id else None


def _openwebui_message_id(req: ChatRequest, header_message_id: str | None) -> str | None:
    if header_message_id:
        return header_message_id
    if isinstance(req.metadata, dict):
        value = req.metadata.get("message_id")
        if value:
            return str(value)
    return None


def _feedback_score(req: FeedbackRequest) -> int | None:
    if req.score is not None:
        return req.score
    if req.rating is not None:
        return req.rating

    for payload in (req.data, req.meta):
        if isinstance(payload, dict):
            for key in ("score", "rating"):
                value = payload.get(key)
                if value is not None:
                    return int(value)
    return None


def _feedback_comment(req: FeedbackRequest) -> str | None:
    comment = req.comment
    reason = req.reason

    if isinstance(req.data, dict):
        comment = comment or req.data.get("comment")
        reason = reason or req.data.get("reason")

    if isinstance(req.meta, dict):
        comment = comment or req.meta.get("comment")
        reason = reason or req.meta.get("reason")

    parts = [part for part in (comment, f"Reason: {reason}" if reason else None) if part]
    if not parts:
        return None
    return "\n".join(parts)


@app.post("/feedback")
async def feedback(req: FeedbackRequest):
    message_id = _feedback_message_id(req)
    thread_id = _feedback_thread_id(req)
    raw_chat_id = _feedback_chat_id(req)

    score = _feedback_score(req)

    # Lookup priority: message_id → raw chat_id → hashed thread_id → most recent run
    run_id = default_run_store.get_for_message(message_id) if message_id else None
    source = "message_id" if run_id else None
    if not run_id and raw_chat_id:
        run_id = default_run_store.get_for_chat_id(raw_chat_id)
        source = "chat_id_direct" if run_id else None
    if not run_id and thread_id:
        run_id = default_run_store.get(thread_id)
        source = "thread_id" if run_id else None
    if not run_id:
        if req.created_at:
            run_id = default_run_store.get_nearest_before(float(req.created_at), max_age_seconds=3600)
            source = "nearest_before_ts" if run_id else None
        if not run_id:
            run_id = default_run_store.get_most_recent(max_age_seconds=3600)
            source = "most_recent" if run_id else None

    _log_feedback_event(
        "lookup",
        thread_id,
        chat_id=raw_chat_id,
        message_id=message_id,
        run_id=run_id,
        score=score,
        source=source,
    )
    logger.info(
        "feedback_lookup thread=%s chat_id=%s message_id=%s score=%s run_id=%s source=%s",
        thread_id,
        raw_chat_id,
        message_id,
        score,
        run_id,
        source,
    )
    if not run_id:
        _log_feedback_event(
            "skipped_no_run_id",
            thread_id,
            chat_id=raw_chat_id,
            message_id=message_id,
            score=score,
        )
        return {"status": "skipped", "reason": "no run_id found for this thread"}

    if score is None:
        return {"status": "skipped", "reason": "no score found in feedback payload"}

    comment = _feedback_comment(req)
    submit_feedback(run_id=run_id, score=score, comment=comment)
    logger.info("feedback thread=%s run_id=%s score=%s comment=%s source=%s", thread_id, run_id, score, comment, source)
    _log_feedback_event(
        "submitted",
        thread_id,
        chat_id=raw_chat_id,
        message_id=message_id,
        run_id=run_id,
        score=score,
        reason=comment,
        source=source,
    )
    return {"status": "ok", "run_id": run_id}


@app.post("/feedback/tap/ping")
async def feedback_tap_ping(payload: dict | None = None):
    _log_feedback_event("tap_ping", None, payload=payload)
    logger.info("feedback_tap_ping payload=%s", payload)
    return {"status": "ok"}


@app.get("/debug/openwebui-feedback-tap.js")
def debug_openwebui_feedback_tap():
    path = Path(__file__).resolve().parent / "openwebui" / "feedback_tap.js"
    return FileResponse(path, media_type="application/javascript")


if __name__ == "__main__":
    port = int(os.getenv("SERVE_PORT", "8000"))
    # Hot-reload : reload=True requiert un import string ("serve:app") plutôt
    # que l'objet app. Au reboot du worker, agent.py est ré-importé et le
    # system prompt LangSmith Hub + skills sont re-pull (sinon ils restent
    # figés jusqu'au prochain restart manuel).
    reload = os.getenv("SERVE_RELOAD", "1") not in ("0", "false", "False")
    if reload:
        uvicorn.run(
            "serve:app",
            host="0.0.0.0",
            port=port,
            reload=True,
            reload_excludes=["*.pyc", "*.tsv", "*.csv", "*.png", "*.pkl"],
        )
    else:
        uvicorn.run(app, host="0.0.0.0", port=port)
