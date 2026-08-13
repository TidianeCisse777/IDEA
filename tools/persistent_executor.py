"""Persistent, least-privilege Python execution per agent thread.

``run_pandas`` and ``run_graph`` share one worker process for a conversation.
The durable source of truth remains ``SessionStore``; the worker is only a hot
cache for DataFrames, imports and user-created intermediate variables.  A dead
or timed-out worker can therefore be recreated without losing provenance.

This is deliberately not an unrestricted notebook: the worker starts with an
empty environment and runs every snippet through ``code_sandbox``.  Process
isolation removes model code from the agent process (where provider and source
credentials live).  Container/network isolation is layered by deployment.
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import multiprocessing as mp
import os
import pickle
import re
import traceback
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Any, Literal


ExecutionMode = Literal["pandas", "graph"]
_THREAD_ID = re.compile(r"[^A-Za-z0-9_.-]+")


def _is_dataframe_payload(value: object) -> bool:
    """Identify pandas-compatible tabular inputs without importing pandas here."""

    module = type(value).__module__
    return (
        module.startswith(("pandas.", "geopandas."))
        and hasattr(value, "columns")
        and hasattr(value, "dtypes")
    )


@dataclass
class ExecutionResult:
    result: Any = None
    result_available: bool = False
    dataframes: dict[str, Any] | None = None
    stdout: str = ""
    error: str | None = None
    image_png: bytes | None = None
    graph_contract: dict[str, Any] | None = None
    produced_figure: bool = False
    dataframe_input_names: tuple[str, ...] = ()


def _assigned_names(code: str) -> set[str]:
    """Return top-level/simple names produced by a snippet."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return {"result", "plot_df"}
    names: set[str] = {"result", "plot_df"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def _uses_zone_geometry(code: str) -> bool:
    """Return whether a graph snippet explicitly needs trusted zone geometry.

    Loading the complete IHO/MEOW registry materialises many Shapely objects.
    Most station maps need only Cartopy's base layers, so keep that registry out
    of the worker unless the generated code actually refers to it.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False
    names = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    return bool({"zone_polygons", "zone_sources"} & names)


def _referenced_zone_names(code: str) -> set[str]:
    """Extract literal zone keys so a contour map need not load every polygon."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id in {"zone_polygons", "zone_sources"}
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            names.add(node.slice.value)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in {"zone_polygons", "zone_sources"}
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            names.add(node.args[0].value)
    return names


def _apply_worker_memory_limit() -> None:
    """Cap worker address space where the host supports POSIX resource limits."""
    try:
        # The worker receives DataFrames through a process pipe.  During
        # unpickling, a large object-level export briefly exists both in the
        # transport buffer and in pandas; 2 GiB therefore fails before user
        # code runs. Keep a real cap, but leave enough headroom for that copy.
        memory_mb = int(os.getenv("PERSISTENT_EXECUTOR_MEMORY_MB", "4096"))
        if memory_mb <= 0:
            return
        import resource

        limit = memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    except (ImportError, OSError, ValueError):
        # The parent deadline remains effective on platforms without this
        # POSIX facility. Deployment may still apply a stronger cgroup limit.
        return


def _worker_main(connection) -> None:
    # Do not inherit provider/source credentials into model-authored code.
    os.environ.clear()
    # NumPy/Matplotlib import OpenBLAS in the isolated worker.  Its default
    # thread pool can reserve enough stack memory to trip the worker's memory
    # cap before a tiny Cartopy map executes.  Analysis code here is a single
    # user request at a time, so one numeric thread is both sufficient and
    # materially more reliable.
    os.environ.update({
        "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
        "VECLIB_MAXIMUM_THREADS": "1",
    })
    _apply_worker_memory_limit()
    # This import must happen *after* the thread caps above.  With the spawn
    # start method, a module-level pandas import initializes OpenBLAS before
    # `_worker_main` runs, making those caps ineffective.
    import pandas as pd

    namespace: dict[str, Any] = {}

    while True:
        try:
            request = connection.recv()
        except EOFError:
            return
        if request.get("op") == "close":
            return

        try:
            mode: ExecutionMode = request["mode"]
            code = request["code"]
            allowed_dataframe_names = request.get("allowed_dataframe_names")
            if allowed_dataframe_names is not None:
                allowed = set(allowed_dataframe_names)
                for name, value in tuple(namespace.items()):
                    if isinstance(value, pd.DataFrame) and name not in allowed:
                        namespace.pop(name, None)
            namespace.update(request.get("inputs") or {})
            # These are per-call outputs.  Keep genuine user intermediates
            # warm, but never let an omitted assignment reuse a prior result
            # or graph contract.
            if mode == "pandas":
                namespace.pop("result", None)
            else:
                namespace.pop("graph_contract", None)

            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            plt.close("all")
            namespace["pd"] = pd
            namespace["plt"] = plt
            if mode == "graph":
                # Import lazily: these helpers are trusted server code, not
                # reachable through the generated snippet's import surface.
                from core.cartography import configure_offline_cartopy
                from tools.data_tools import (
                    _apply_neolab_report_theme,
                    _cartopy_safe_tight_layout,
                    _finalize_neolab_report_figures,
                    _graph_savefig_kwargs,
                    _patch_cartopy_gridliner_polygon,
                    _zone_geometry_vars,
                )

                configure_offline_cartopy()
                _patch_cartopy_gridliner_polygon()
                _apply_neolab_report_theme(plt)
                zone_geometry_loaded = _uses_zone_geometry(code)
                if zone_geometry_loaded:
                    namespace.update(
                        _zone_geometry_vars(_referenced_zone_names(code) or None)
                    )
            else:
                _finalize_neolab_report_figures = None
                _cartopy_safe_tight_layout = contextlib.nullcontext
                _graph_savefig_kwargs = None
                zone_geometry_loaded = False

            from tools.code_sandbox import apply_restricted_builtins

            apply_restricted_builtins(namespace)
            stdout = io.StringIO()
            try:
                with contextlib.redirect_stdout(stdout):
                    if mode == "graph":
                        with _cartopy_safe_tight_layout(plt):
                            exec(code, namespace)  # noqa: S102
                    else:
                        exec(code, namespace)  # noqa: S102
            finally:
                # Geometries are trusted per-call inputs, not user
                # intermediates.  Do not retain the full registry in a
                # persistent worker after a contour was rendered or failed.
                if zone_geometry_loaded:
                    namespace.pop("zone_polygons", None)
                    namespace.pop("zone_sources", None)

            names = _assigned_names(code)
            frames = {
                name: value
                for name, value in namespace.items()
                if name in names and isinstance(value, pd.DataFrame)
            }
            result = namespace.get("result")
            if isinstance(result, pd.DataFrame):
                frames["result"] = result

            image_png = None
            contract = namespace.get("graph_contract")
            if not isinstance(contract, dict):
                contract = None
            if mode == "graph" and plt.get_fignums():
                _finalize_neolab_report_figures(plt)
                buffer = io.BytesIO()
                plt.savefig(buffer, **_graph_savefig_kwargs(plt))
                image_png = buffer.getvalue()
                plt.close("all")
            produced_figure = image_png is not None
            if mode == "pandas" and plt.get_fignums():
                plt.close("all")
                produced_figure = True

            try:
                # A Matplotlib Figure, especially a Cartopy GeoAxes figure,
                # cannot reliably cross the multiprocessing pipe: pickling its
                # CRS can fail *after* the PNG has rendered successfully.
                # Graph callers only consume `image_png`; retain the Figure in
                # the warm worker namespace but never serialize it.
                transport_result = result
                transport_result_available = "result" in namespace
                if mode == "graph" and image_png is not None:
                    transport_result = None
                    transport_result_available = False
                connection.send(
                    {
                        "ok": True,
                        "result": transport_result,
                        "result_available": transport_result_available,
                        "dataframes": frames,
                        "stdout": stdout.getvalue().strip(),
                        "image_png": image_png,
                        "graph_contract": contract,
                        "produced_figure": produced_figure,
                    }
                )
            except Exception:
                # Some user result types are not transportable; the existing
                # tool contract only needs a faithful textual value in that case.
                connection.send(
                    {
                        "ok": True,
                        "result": repr(result),
                        "result_available": "result" in namespace,
                        "dataframes": frames,
                        "stdout": stdout.getvalue().strip(),
                        "image_png": image_png,
                        "graph_contract": contract,
                        "produced_figure": produced_figure,
                    }
                )
        except Exception:
            connection.send({"ok": False, "error": traceback.format_exc()})


@dataclass
class _Worker:
    process: Any
    connection: Any
    input_versions: dict[str, object]
    lock: Lock
    last_used: float


class PersistentExecutor:
    """Own and reuse one restricted worker process per conversation thread."""

    def __init__(self, timeout_seconds: float | None = None) -> None:
        self._workers: dict[str, _Worker] = {}
        self._lock = Lock()
        self._timeout = float(
            timeout_seconds or os.getenv("PERSISTENT_EXECUTOR_TIMEOUT_SECONDS", "45")
        )

    def _new_worker(self) -> _Worker:
        parent, child = mp.Pipe()
        process = mp.get_context("spawn").Process(
            target=_worker_main,
            args=(child,),
            daemon=True,
        )
        process.start()
        child.close()
        return _Worker(process, parent, {}, Lock(), monotonic())

    def _worker(self, thread_id: str) -> _Worker:
        with self._lock:
            idle_limit = float(os.getenv("PERSISTENT_EXECUTOR_IDLE_SECONDS", "1800"))
            now = monotonic()
            stale = [
                key for key, item in self._workers.items()
                if now - item.last_used > idle_limit
            ]
            for key in stale:
                item = self._workers.pop(key)
                with contextlib.suppress(Exception):
                    item.connection.send({"op": "close"})
                item.process.join(timeout=0.2)
                if item.process.is_alive():
                    item.process.terminate()
                with contextlib.suppress(Exception):
                    item.connection.close()
            worker = self._workers.get(thread_id)
            if worker is None or not worker.process.is_alive():
                if worker is not None:
                    with contextlib.suppress(Exception):
                        worker.connection.close()
                worker = self._new_worker()
                self._workers[thread_id] = worker
            return worker

    def execute(
        self,
        thread_id: str,
        mode: ExecutionMode,
        code: str,
        inputs: dict[str, Any],
        *,
        allowed_dataframe_names: set[str] | None = None,
    ) -> ExecutionResult:
        worker = self._worker(thread_id)
        with worker.lock:
            transportable_inputs: dict[str, Any] = {}
            input_versions: dict[str, object] = {}
            for name, value in inputs.items():
                try:
                    serialized = pickle.dumps(
                        value,
                        protocol=pickle.HIGHEST_PROTOCOL,
                    )
                except Exception:
                    # ``pd``/``plt`` and other trusted runtime helpers are
                    # recreated by the worker; only data and scalar context
                    # belong on the process boundary.
                    continue
                transportable_inputs[name] = value
                input_versions[name] = (
                    hashlib.blake2b(serialized, digest_size=16).digest()
                    if _is_dataframe_payload(value)
                    else id(value)
                )
            if allowed_dataframe_names is not None:
                worker.input_versions = {
                    name: version
                    for name, version in worker.input_versions.items()
                    if name in allowed_dataframe_names
                }
            # A SessionStore entry may retain the same Python DataFrame object
            # while its schema or values change. Content identity prevents the
            # hot worker from serving that stale pre-mutation payload; ``id``
            # alone cannot detect it and may also be reused by Python.
            fresh_inputs = {
                name: value
                for name, value in transportable_inputs.items()
                if worker.input_versions.get(name) != input_versions[name]
            }
            worker.input_versions.update(input_versions)
            try:
                worker.connection.send(
                    {
                        "op": "execute",
                        "mode": mode,
                        "code": code,
                        "inputs": fresh_inputs,
                        "allowed_dataframe_names": (
                            sorted(allowed_dataframe_names)
                            if allowed_dataframe_names is not None
                            else None
                        ),
                    }
                )
                if not worker.connection.poll(self._timeout):
                    raise TimeoutError(f"controlled execution exceeded {self._timeout:g} seconds")
                payload = worker.connection.recv()
            except Exception as exc:
                self.close(thread_id)
                return ExecutionResult(error=f"{type(exc).__name__}: {exc}")
            worker.last_used = monotonic()

        if not payload.get("ok"):
            return ExecutionResult(error=str(payload.get("error") or "controlled execution failed"))
        return ExecutionResult(
            result=payload.get("result"),
            result_available=bool(payload.get("result_available")),
            dataframes=dict(payload.get("dataframes") or {}),
            stdout=str(payload.get("stdout") or ""),
            image_png=payload.get("image_png"),
            graph_contract=payload.get("graph_contract"),
            produced_figure=bool(payload.get("produced_figure")),
            dataframe_input_names=tuple(sorted(
                name
                for name, value in inputs.items()
                if _is_dataframe_payload(value)
            )),
        )

    def close(self, thread_id: str) -> None:
        with self._lock:
            worker = self._workers.pop(thread_id, None)
        if worker is None:
            return
        with contextlib.suppress(Exception):
            worker.connection.send({"op": "close"})
        worker.process.join(timeout=0.5)
        if worker.process.is_alive():
            worker.process.terminate()
        with contextlib.suppress(Exception):
            worker.connection.close()


default_executor = PersistentExecutor()
