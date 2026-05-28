from __future__ import annotations

import importlib
import json
import os
import sys
import traceback as _traceback
import uuid
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

from fastapi import FastAPI
from fastapi.testclient import TestClient

import agents.copepod_profile  # noqa: F401
from core.auth import get_auth_token
from core.config import settings
from core.copepod_observability import should_enable_langfuse
from core.copepod_plan_workflow import PLAN_READY
from core.langfuse_guard import validate_langfuse_configuration
from core.session_store import InMemorySessionStore
from routers.file_routes import router as file_router
from routers.session_routes import router as session_router

DATASET_NAME = "copepod-plan-mode-v1"
LIVE_OPENAI_TIMEOUT_SECONDS = float(os.getenv("COPEPOD_LIVE_OPENAI_TIMEOUT_SECONDS", "120"))


def _load_tools() -> dict[str, Any]:
    from core.tool_registry import registry
    from core.tool_registry.tools import copepod_columns  # noqa: F401
    from core.tool_registry.tools import copepod_data  # noqa: F401
    from core.tool_registry.tools import copepod_session_artifacts  # noqa: F401

    ns: dict[str, Any] = {}
    exec(registry.render({"copepod_data", "copepod_columns", "copepod_artifacts"}), ns)
    return ns


def _make_test_client(store: InMemorySessionStore) -> tuple[TestClient, ExitStack]:
    import agents.copepod_profile
    import agents.generic_profile

    importlib.reload(agents.generic_profile)
    importlib.reload(agents.copepod_profile)

    app = FastAPI()
    app.include_router(file_router)
    app.include_router(session_router)
    app.dependency_overrides[get_auth_token] = lambda: "eval-token"

    fake_user = SimpleNamespace(id="eval-user")
    stack = ExitStack()
    stack.enter_context(patch("routers.file_routes.get_current_user", return_value=fake_user))
    stack.enter_context(patch("routers.session_routes.get_current_user", return_value=fake_user))
    stack.enter_context(patch("routers.session_routes.session_store", store))
    stack.enter_context(patch("core.session_store.session_store", store))
    return TestClient(app), stack


def _result(name: str, passed: bool, detail: str, metadata: dict | None = None) -> dict:
    return {"name": name, "passed": bool(passed), "detail": detail, "metadata": metadata or {}}


def _browser_trace_url(url: str | None) -> str | None:
    if not url:
        return url
    fallback = os.getenv("LANGFUSE_HOST_LOCAL")
    if fallback and "://langfuse:3000" in url:
        return url.replace("http://langfuse:3000", fallback.rstrip("/"))
    return url


def _configure_local_langfuse_host() -> None:
    from urllib.request import Request, urlopen

    host = os.getenv("LANGFUSE_HOST") or os.getenv("LANGFUSE_BASE_URL") or ""
    if "://langfuse:3000" not in host:
        return
    fallback = os.getenv("LANGFUSE_HOST_LOCAL")
    if not fallback:
        return
    try:
        req = Request(f"{fallback}/api/public/projects", method="GET")
        urlopen(req, timeout=2)
    except Exception as exc:
        if getattr(exc, "code", None) not in {200, 401}:
            return
    os.environ["LANGFUSE_HOST"] = fallback
    os.environ["LANGFUSE_BASE_URL"] = fallback


def _json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _cleanup_old_logs(log_dir: Path, prefix: str, keep: int = 3) -> None:
    logs = sorted(
        log_dir.glob(f"{prefix}*.log"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    for old in logs[keep:]:
        old.unlink(missing_ok=True)


def _make_eval_trace(
    session_key: str,
    session_id: str,
    model_name: str,
    tags: list[str],
    *,
    file_name: str = "",
):
    if not should_enable_langfuse():
        return None, None
    try:
        validate_langfuse_configuration()
        from langfuse import Langfuse

        _configure_local_langfuse_host()
        lf = Langfuse()
        trace = lf.trace(
            name="copepod-eval/live",
            user_id="eval-user",
            session_id=session_key,
            tags=tags,
            input={"model": model_name, "file": file_name, "session_id": session_id},
        )
        os.environ["COPEPOD_EVAL_LF_TRACE_ID"] = trace.id
        return lf, trace
    except Exception:
        return None, None


def _close_eval_trace(lf, trace, results: list[dict], push_scores: bool = False) -> str | None:
    if trace is None or not should_enable_langfuse():
        return None
    try:
        passed = sum(1 for r in results if r["passed"])
        trace.update(
            output={"passed": passed, "total": len(results)},
            metadata={"dataset": DATASET_NAME},
        )
        if push_scores:
            for result in results:
                trace.score(
                    name=result["name"],
                    value=1.0 if result["passed"] else 0.0,
                    data_type="BOOLEAN",
                    comment=result["detail"],
                )
        lf.flush()
        os.environ.pop("COPEPOD_EVAL_LF_TRACE_ID", None)
        return _browser_trace_url(trace.get_trace_url())
    except Exception:
        return None


def _push_scores_to_langfuse(session_key: str, results: list[dict]) -> str | None:
    if not should_enable_langfuse():
        return None
    try:
        validate_langfuse_configuration()
        from langfuse import Langfuse

        _configure_local_langfuse_host()
        lf = Langfuse()
        trace = lf.trace(
            name="copepod-plan-mode-eval-scores",
            user_id="eval-user",
            session_id=session_key,
            input={"dataset": DATASET_NAME},
            output={
                "passed_count": sum(1 for r in results if r["passed"]),
                "total_count": len(results),
            },
            metadata={"created_at": datetime.now(timezone.utc).isoformat()},
            tags=["eval", "copepod", "scores"],
        )
        for result in results:
            trace.score(
                name=result["name"],
                value=1.0 if result["passed"] else 0.0,
                data_type="BOOLEAN",
                comment=result["detail"],
            )
        lf.flush()
        return _browser_trace_url(trace.get_trace_url())
    except Exception:
        return None


def _post_analyse(client: TestClient, session_id: str):
    return client.post(
        "/session/mode",
        json={"mode": "analyse"},
        headers={"x-session-id": session_id, "x-agent-type": "copepod"},
    )


def _plan_ready_allowed(store: InMemorySessionStore, session_key: str) -> bool:
    return (
        store.get_copepod_plan_phase(session_key) == PLAN_READY
        and store.has_active_copepod_plan_artifacts(session_key)
    )


class EvalHarness:
    """Context manager providing shared eval infrastructure.

    Owns: InMemorySessionStore, tool registry, TestClient + patches,
    log file, Langfuse trace lifecycle, and result aggregation.

    Usage::

        with EvalHarness(suite="mock", log_prefix="mock_eval_", ...) as ctx:
            ctx.result("test_name", passed=True, detail="ok")
            ctx.log("--- phase header ---")
            # ctx.store, ctx.tools, ctx.client, ctx.trace available
        return ctx.report
    """

    def __init__(
        self,
        *,
        suite: str,
        log_prefix: str,
        tags: list[str],
        mode: str,
        push_langfuse: bool = False,
        lf_file_hint: str = "",
    ):
        self.suite = suite
        self.log_prefix = log_prefix
        self.tags = tags
        self.mode = mode
        self.push_langfuse = push_langfuse
        self._lf_file_hint = lf_file_hint

        self._results: list[dict] = []
        self._lf: Any = None
        self._trace_url: str | None = None
        self._patch_stack: ExitStack | None = None

    def __enter__(self) -> "EvalHarness":
        self.session_id = f"{self.suite}-{uuid.uuid4().hex[:10]}"
        self.session_key = f"eval-user:{self.session_id}:copepod"
        self.model_name = settings.LLM_MODEL

        self.store = InMemorySessionStore()
        self.tools = _load_tools()

        self.client, self._patch_stack = _make_test_client(self.store)
        self._patch_stack.__enter__()

        log_dir = ROOT / "logs" / "evals"
        log_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = log_dir / f"{self.log_prefix}{self.session_id}.log"
        self._log_fh = open(self._log_path, "w", encoding="utf-8")
        self._log_fh.write(
            f"=== {self.suite.upper()} EVAL {self.session_id} model={self.model_name} ===\n"
        )
        self._log_fh.flush()

        self._lf, self.trace = _make_eval_trace(
            self.session_key,
            self.session_id,
            self.model_name,
            self.tags,
            file_name=self._lf_file_hint,
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self._log_fh.write(f"\n[CRASH] {exc_type.__name__}: {exc_val}\n")
            self._log_fh.write(_traceback.format_exc())
            self._log_fh.flush()

        passed_count = sum(1 for r in self._results if r["passed"])
        self._log_fh.write(f"\n=== SCORES {passed_count}/{len(self._results)} ===\n")
        for r in self._results:
            self._log_fh.write(f"  {'PASS' if r['passed'] else 'FAIL'} {r['name']}\n")
            if not r["passed"]:
                self._log_fh.write(f"       {r['detail']}\n")
        self._log_fh.write(f"\nlog: {self._log_path}\n")
        self._log_fh.flush()
        self._log_fh.close()

        if self._patch_stack is not None:
            self._patch_stack.__exit__(exc_type, exc_val, exc_tb)

        self._trace_url = _close_eval_trace(
            self._lf, self.trace, self._results, push_scores=self.push_langfuse
        )

        _cleanup_old_logs(ROOT / "logs" / "evals", self.log_prefix)
        print(f"eval log → {self._log_path}")
        return False

    def result(self, name: str, passed: bool, detail: str, metadata: dict | None = None) -> dict:
        r = _result(name, passed, detail, metadata)
        self._results.append(r)
        return r

    def log(self, msg: str) -> None:
        self._log_fh.write(msg + "\n")
        self._log_fh.flush()

    @property
    def report(self) -> dict:
        passed_count = sum(1 for r in self._results if r["passed"])
        return {
            "dataset": DATASET_NAME,
            "mode": self.mode,
            "model": self.model_name,
            "session_id": self.session_id,
            "session_key": self.session_key,
            "passed": passed_count == len(self._results),
            "passed_count": passed_count,
            "total_count": len(self._results),
            "results": list(self._results),
            "langfuse_trace_url": self._trace_url,
        }
