"""
IDEA FastAPI application — wiring only.

All business logic lives in routers/ and core/.
"""
import asyncio
import logging
import os

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware

import litellm

# ── Bootstrap: import generic profile so the registry is populated on startup ──
import agents.generic_profile  # noqa: F401

from core.mcp_manager import mcp_manager
from routers.knowledge_base_routes import router as knowledge_base_router, MAX_PAPER_SIZE
from routers.conversation_routes import router as conversation_router
from routers.mcp_routes import router as mcp_router

from routers.auth_routes import router as auth_router
from routers.user_routes import router as user_router
from routers.prompt_routes import router as prompt_router
from routers.chat_routes import (
    router as chat_router,
    STATIC_DIR,
    UPLOAD_DIR,
    periodic_cleanup,
)
from routers.file_routes import router as file_router, MAX_FILE_SIZE

from core.prompt_store import init_prompt_manager

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LiteLLM global settings
# ---------------------------------------------------------------------------
litellm.request_timeout = 600  # 10 minutes

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------
CHAT_RATE_LIMIT = "10/minute"
UPLOAD_RATE_LIMIT = "25/minute"

limiter = Limiter(key_func=get_remote_address)

# ---------------------------------------------------------------------------
# App creation
# ---------------------------------------------------------------------------
root_path = "/idea-api"
app = FastAPI(root_path=root_path)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Static files
app.mount("/" + str(STATIC_DIR), StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/assets", StaticFiles(directory="frontend"), name="assets")

# Prompt manager (DB-backed)
init_prompt_manager()

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
cors_origins_env = os.getenv("CORS_ORIGINS", "")
if cors_origins_env:
    origins = [o.strip() for o in cors_origins_env.split(",") if o.strip()]
else:
    origins = [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:8001",
        "http://127.0.0.1:8001",
        "http://localhost",
        "*",
        "http://172.18.46.161",
        "http://172.18.46.161:8001",
        "https://uhslc.soest.hawaii.edu/research/IDEA",
    ]

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "POST":
            path = request.url.path
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    request_size = int(content_length)
                except ValueError:
                    request_size = None

                if request_size is not None:
                    if path.endswith("/knowledge-base/papers/upload"):
                        max_size = MAX_PAPER_SIZE
                    elif path.endswith("/upload"):
                        max_size = MAX_FILE_SIZE
                    else:
                        max_size = None

                    if max_size and request_size > max_size:
                        return JSONResponse(
                            status_code=413,
                            content={"detail": "Request too large"},
                        )
        return await call_next(request)


app.add_middleware(RequestSizeLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    retry_after = getattr(exc, "retry_after", None)
    message = (
        f"Too many requests. Please try again in {retry_after} seconds."
        if retry_after
        else "Too many requests. Please try again later."
    )
    return JSONResponse(status_code=429, content={"detail": message})


@app.exception_handler(Exception)
async def http_exception_handler(request: Request, exc: Exception):
    from fastapi import HTTPException
    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    raise exc


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(knowledge_base_router)
app.include_router(conversation_router, prefix="/conversations", tags=["conversations"])
app.include_router(mcp_router)

app.include_router(auth_router)
app.include_router(user_router)
app.include_router(prompt_router)
app.include_router(chat_router)
app.include_router(file_router)

# ---------------------------------------------------------------------------
# Lifecycle events
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def start_periodic_cleanup():
    """Start the periodic cleanup task when the app starts."""
    asyncio.create_task(periodic_cleanup())


@app.on_event("shutdown")
async def shutdown_resources():
    """Cleanup long-lived resources as the application stops."""
    await mcp_manager.close_all()
