"""OpenAI-compatible API — expose l'agent copépodes pour Open WebUI."""
import base64
import hashlib
import json
import logging
import os
import re
import subprocess
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator

import uvicorn
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

load_dotenv()

from agent import make_agent, _CHECKPOINTS_DB
from tools.session_store import default_store
from core.copepod_rag.query import _get_cross_encoder

# Pré-charge le cross-encoder au démarrage — évite 10-15s de latence au 1er appel RAG
_get_cross_encoder()

LOGS_DIR = Path(os.getenv("CONV_LOGS_DIR", "logs/conversations"))
LOGS_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("copepod.serve")


def _log_turn(thread_id: str, user_msg: str, assistant_msg: str, usage: dict) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "thread_id": thread_id,
        "user": user_msg,
        "assistant": assistant_msg,
        "usage": usage,
    }
    log_path = LOGS_DIR / f"{thread_id}.jsonl"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    logger.info("thread=%s prompt=%s completion=%s cached=%s",
        thread_id,
        usage.get("prompt_tokens", 0),
        usage.get("completion_tokens", 0),
        usage.get("prompt_tokens_details", {}).get("cached_tokens", 0),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize async SQLite checkpointer — persists agent state across restarts."""
    import agent as _agent_module
    try:
        import aiosqlite
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        async with AsyncSqliteSaver.from_conn_string(str(_CHECKPOINTS_DB)) as cp:
            _agent_module._checkpointer = cp
            logger.info("SQLite checkpointer ready: %s", _CHECKPOINTS_DB)
            yield
    except Exception as e:
        logger.warning("AsyncSqliteSaver unavailable (%s) — using MemorySaver", e)
        yield


app = FastAPI(title="Copepod Agent API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

GRAPHS_DIR = Path("/tmp/copepod_graphs")
GRAPHS_DIR.mkdir(exist_ok=True)

_BASE_URL = os.getenv("SERVE_BASE_URL", "http://localhost:8000")


def _extract_and_host_images(text: str) -> str:
    """Remplace les data URIs base64 par des URLs hébergées sur /graphs/."""
    def replace(match):
        b64 = match.group(1).replace("\n", "").replace(" ", "")
        # Rétablit le padding si manquant
        b64 += "=" * (-len(b64) % 4)
        graph_id = uuid.uuid4().hex[:12]
        path = GRAPHS_DIR / f"{graph_id}.png"
        path.write_bytes(base64.b64decode(b64))
        url = f"{_BASE_URL}/graphs/{graph_id}.png"
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

_WEBUI_UPLOADS_DIR = Path("/tmp/webui_uploads")
_WEBUI_UPLOADS_DIR.mkdir(exist_ok=True)

_WEBUI_CONTAINER = os.getenv("WEBUI_CONTAINER", "open-webui")
_WEBUI_UPLOADS_PATH = os.getenv("WEBUI_UPLOADS_PATH", "/app/backend/data/uploads")


def _resolve_attached_files(text: str) -> str:
    """Remplace <attached_files> XML par un chemin local accessible par load_file.

    Open WebUI injecte :
      <attached_files>
        <file type="file" url="<UUID>" content_type="..." name="<filename>"/>
      </attached_files>

    On copie le fichier depuis le container Docker vers /tmp/webui_uploads/<filename>
    et on réécrit le message pour que l'agent puisse appeler load_file.
    """
    pattern = r"<attached_files>.*?</attached_files>"
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        return text

    xml_block = match.group(0)
    resolved_paths = []

    try:
        root = ET.fromstring(xml_block)
        for file_el in root.findall("file"):
            file_id = file_el.get("url", "").strip()
            name = file_el.get("name", "").strip()
            if not file_id or not name:
                continue

            local_path = _WEBUI_UPLOADS_DIR / name
            # Pattern Docker : <UUID>_<filename>
            container_path = f"{_WEBUI_UPLOADS_PATH}/{file_id}_{name}"

            try:
                with open(local_path, "wb") as out_f:
                    subprocess.run(
                        ["docker", "exec", _WEBUI_CONTAINER, "cat", container_path],
                        stdout=out_f,
                        stderr=subprocess.DEVNULL,
                        check=True,
                        timeout=10,
                    )
                resolved_paths.append(str(local_path))
                logger.info("file_resolved name=%s → %s", name, local_path)
            except Exception as exc:
                logger.warning("file_resolve_failed name=%s container=%s err=%s", name, container_path, exc)

    except ET.ParseError as exc:
        logger.warning("attached_files_parse_error: %s", exc)

    if not resolved_paths:
        # On ne peut pas résoudre — on nettoie juste le XML pour ne pas polluer le LLM
        return re.sub(pattern, "", text, flags=re.DOTALL).strip()

    paths_str = "\n".join(f"- {p}" for p in resolved_paths)
    instruction = (
        f"Fichier(s) chargé(s) depuis Open WebUI :\n{paths_str}\n"
        "Charge le fichier avec l'outil load_file avant de répondre."
    )
    return re.sub(pattern, instruction, text, flags=re.DOTALL).strip()


_known_threads: set[str] = set()


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


class ChatRequest(BaseModel):
    model: str = "copepod-agent"
    messages: list[Message]
    stream: bool = False


def _thread_id(messages: list[Message]) -> str:
    """Thread stable basé sur le premier message utilisateur."""
    first = next((m.text() for m in messages if m.role == "user"), str(uuid.uuid4()))
    return hashlib.md5(first[:200].encode()).hexdigest()[:16]


@app.get("/")
def root():
    return {"status": "ok", "agent": "copepod-agent"}


@app.get("/v1/models")
def list_models():
    return {
        "object": "list",
        "data": [{"id": "copepod-agent", "object": "model", "owned_by": "neolab"}],
    }


_INTERNAL_PREFIXES = ("### Task:", "### Guidelines:", "### Input:", "### Output:")


def _is_internal_prompt(text: str) -> bool:
    return any(text.strip().startswith(p) for p in _INTERNAL_PREFIXES)


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

    - run_graph / run_pandas : bloc <details> collapsible avec le code Python
    - load_file : affiche le nom du fichier
    - skill_tool : affiche le nom du skill
    - autres : juste 🔧 nom
    """
    args = args or {}

    if name in ("run_graph", "run_pandas") and "code" in args:
        code = args["code"]
        if name == "run_graph":
            return f"\n🔧 `{name}`\n```python\n{code}\n```\n📊 *Génération du graphique...*\n"
        return f"\n🔧 `{name}`\n```python\n{code}\n```\n"

    if name == "load_file" and "path" in args:
        filename = Path(args["path"]).name
        return f"\n🔧 `{name}` → `{filename}`\n"

    if name == "load_skill" and "skill_name" in args:
        skill = args["skill_name"]
        return f"\n🔧 `{name}` → `{skill}`\n"

    return f"\n🔧 `{name}`\n"


async def _stream_agent_sse(
    agent,
    messages: dict,
    config: dict,
    thread_id: str,
) -> AsyncGenerator[str, None]:
    """Génère les chunks SSE depuis l'agent LangGraph (stream_mode='updates')."""
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
    last_ai_msg = None

    try:
        async for update in agent.astream(messages, config, stream_mode="updates"):
            for node, state in update.items():
                msgs = state.get("messages", [])
                if not msgs:
                    continue
                last_msg = msgs[-1]

                if node == "agent":
                    last_ai_msg = last_msg
                    content = getattr(last_msg, "content", "") or ""
                    tool_calls = getattr(last_msg, "tool_calls", []) or []

                    if content:
                        content = _extract_and_host_images(content)
                        yield _make_sse_chunk(completion_id, content)

                    for tc in tool_calls:
                        name = tc["name"] if isinstance(tc, dict) else tc.name
                        tc_args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                        yield _make_sse_chunk(completion_id, _format_tool_line(name, tc_args))

                elif node == "tools":
                    for tool_msg in msgs:
                        tool_content = getattr(tool_msg, "content", "") or ""
                        if "data:image/png;base64," in tool_content:
                            hosted = _extract_and_host_images(tool_content)
                            img_match = re.search(r"!\[.*?\]\(http[^\)]+\)", hosted)
                            if img_match:
                                yield _make_sse_chunk(completion_id, f"\n{img_match.group(0)}\n")

    except Exception as exc:
        logger.error("stream_error thread=%s err=%s", thread_id, exc)
        yield _make_sse_chunk(completion_id, f"\n\n[Erreur : {exc}]")

    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
             "prompt_tokens_details": {"cached_tokens": 0}}

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
        last_user_text = (messages.get("messages") or [{}])[-1].get("content", "")
        final_text = getattr(last_ai_msg, "content", "") or ""
        _log_turn(thread_id, last_user_text, final_text, usage)
        if cached_tokens > 0:
            logger.info("CACHE HIT thread=%s cached=%s (%.0f%% of prompt)",
                thread_id, cached_tokens, 100 * cached_tokens / prompt_tokens if prompt_tokens else 0)

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
async def chat_completions(req: ChatRequest):
    tid = _thread_id(req.messages)

    last_user = next(
        (m.text() for m in reversed(req.messages) if m.role == "user"), ""
    )
    last_user = _resolve_attached_files(last_user)

    if _is_internal_prompt(last_user):
        logger.info("thread=%s SKIPPED internal prompt", tid)
        if req.stream:
            return StreamingResponse(_quick_sse_response(""), media_type="text/event-stream")
        return _quick_response("")

    if tid not in _known_threads:
        _known_threads.add(tid)
        default_store.clear(tid)

    agent = make_agent(tid)
    config = {"configurable": {"thread_id": tid}}
    messages = {"messages": [{"role": "user", "content": last_user}]}

    logger.info("thread=%s stream=%s", tid, req.stream)
    if req.stream:
        logger.info("thread=%s STREAM start", tid)
        return StreamingResponse(
            _stream_agent_sse(agent, messages, config, tid),
            media_type="text/event-stream",
        )

    result = agent.invoke(messages, config=config)

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

    _log_turn(tid, last_user, text, usage)

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


if __name__ == "__main__":
    port = int(os.getenv("SERVE_PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
