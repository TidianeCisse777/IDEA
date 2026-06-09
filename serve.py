"""OpenAI-compatible API — expose l'agent copépodes pour Open WebUI."""
import base64
import hashlib
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

load_dotenv()

from agent import make_agent
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

app = FastAPI(title="Copepod Agent API")

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
        b64 = match.group(1)
        graph_id = uuid.uuid4().hex[:12]
        path = GRAPHS_DIR / f"{graph_id}.png"
        path.write_bytes(base64.b64decode(b64))
        url = f"{_BASE_URL}/graphs/{graph_id}.png"
        return (
            f"![graphe]({url})\n\n"
            f"[⬇ Télécharger le graphe]({url})"
        )
    return re.sub(r"!\[.*?\]\(data:image/png;base64,([A-Za-z0-9+/=]+)\)", replace, text)

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


@app.post("/v1/chat/completions")
def chat_completions(req: ChatRequest):
    tid = _thread_id(req.messages)

    if tid not in _known_threads:
        _known_threads.add(tid)
        default_store.clear(tid)

    agent = make_agent(tid)
    config = {"configurable": {"thread_id": tid}}

    last_user = next(
        (m.text() for m in reversed(req.messages) if m.role == "user"), ""
    )

    result = agent.invoke(
        {"messages": [{"role": "user", "content": last_user}]},
        config=config,
    )

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
