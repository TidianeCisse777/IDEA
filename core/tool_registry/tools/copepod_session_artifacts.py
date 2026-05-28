from core.tool_registry.registry import Tool, registry

_code = '''
def _is_presummarized(entry):
    """Return True if a file entry is already a summarize_understanding output (has column_catalogue)."""
    return isinstance(entry, dict) and bool(entry.get("column_catalogue"))


def _normalize_data_understanding_payload(session_key, artifact):
    """Ensure a DU draft keeps the summary fields the UI/tests rely on.

    Handles three input shapes:
    1. synthesize_file_understanding output: payload has file_summaries[] + global{}
    2. Pre-summarized files: payload has files[] where each entry has column_catalogue
    3. Raw file entries: payload has files[] with file_path/original_filename only
       (fallback — re-runs inspect_file; legacy single-file path)
    """
    from copy import deepcopy
    from pathlib import Path
    from routers.file_routes import STATIC_DIR, UPLOAD_DIR

    payload = deepcopy(artifact or {})

    user_id, session_id, *_ = (session_key or "::").split(":")
    upload_root = STATIC_DIR / user_id / session_id / UPLOAD_DIR

    # Shape 1 — synthesize_file_understanding output
    # Normalize file_summaries → files, keep global block as-is
    if payload.get("file_summaries"):
        payload.setdefault("files", payload.pop("file_summaries"))
        payload.setdefault("global", {})

    # Shape 1b — LLM passed a reconstructed artifact instead of synthesize output verbatim.
    # Recover file_summaries from the cached file_synthesis artifact if available.
    if not payload.get("files"):
        try:
            from core import session_store as _ss_mod
            synth_versions = _ss_mod.session_store.get_artifact_versions(session_key, "file_synthesis")
            if synth_versions:
                cached = (synth_versions[-1].get("payload") or {})
                if cached.get("file_summaries"):
                    payload["files"] = list(cached["file_summaries"])
                    payload.setdefault("global", cached.get("global") or {})
        except Exception:
            pass

    file_entries = payload.get("files") or []

    # Shape 2 — pre-summarized files (summarize_understanding output per file)
    if file_entries and all(_is_presummarized(e) for e in file_entries):
        merged = []
        seen: set = set()
        for entry in file_entries:
            for col in (entry.get("column_catalogue") or []):
                col_name = col.get("column") if isinstance(col, dict) else None
                if col_name and col_name not in seen:
                    merged.append(col)
                    seen.add(col_name)
        if merged:
            payload["column_catalogue"] = merged

        # Global coverage: most pessimistic across files
        if not payload.get("coverage_assessment"):
            statuses = [
                (e.get("coverage_assessment") or {}).get("status", "partial")
                for e in file_entries
            ]
            global_status = (
                "insufficient" if "insufficient" in statuses
                else ("partial" if "partial" in statuses else "sufficient")
            )
            payload["coverage_assessment"] = {"status": global_status, "structural_signals": [], "semantic_signals": [], "gaps": []}

        # Per-file metadata: store on each entry rather than clobbering the root
        for entry in file_entries:
            entry.setdefault("metadata_detected", entry.get("metadata_detected") or {})

    else:
        # Shape 3 — raw file entries or empty files list: legacy rebuild path
        def _load_data_tools():
            from core.tool_registry import registry
            from core.tool_registry.tools import copepod_data  # noqa: F401
            ns = {}
            exec(registry.render({"copepod_data"}), ns)
            return ns

        def _rebuild_from_file_entries(entries):
            tools = _load_data_tools()
            columns = []
            candidate_entries = list(entries or [])
            if not candidate_entries and upload_root.exists():
                candidate_entries = [
                    {"file_path": str(path), "original_filename": path.name}
                    for path in sorted(upload_root.iterdir())
                    if path.is_file()
                ]
            last_inspect = None
            last_summary = None
            for entry in candidate_entries:
                file_path = entry.get("file_path")
                original_filename = entry.get("original_filename")
                candidate_paths = []
                if file_path:
                    candidate_paths.append(Path(file_path))
                if original_filename:
                    candidate_paths.append(upload_root / original_filename)
                file_path_obj = next((p for p in candidate_paths if p and p.exists()), None)
                if file_path_obj is None:
                    continue
                inspect_report = tools["inspect_file"](str(file_path_obj))
                role_report = tools["infer_column_roles"](
                    inspect_report.get("columns") or [],
                    inspect_report.get("metadata") or {},
                )
                summary = tools["summarize_understanding"](inspect_report, role_report)
                columns.extend(summary.get("column_catalogue") or [])
                # Store metadata on the entry itself, not only on the last one
                entry["metadata_detected"] = inspect_report.get("metadata") or {}
                last_inspect = inspect_report
                last_summary = summary
            return last_inspect, columns, last_summary

        column_catalogue = payload.get("column_catalogue") or []
        if not column_catalogue:
            derived = []
            seen: set = set()
            for file_entry in file_entries:
                raw_cols = file_entry.get("columns") or []
                roles = {
                    r.get("column"): r
                    for r in (file_entry.get("roles") or [])
                    if isinstance(r, dict) and r.get("column")
                }
                for col in raw_cols:
                    if isinstance(col, dict):
                        col_name = col.get("name")
                        semantic_guess = col.get("semantic_guess")
                        unit_guess = col.get("unit_guess")
                        confidence = col.get("confidence")
                    else:
                        col_name = str(col)
                        semantic_guess = unit_guess = confidence = None
                    if not col_name or col_name in seen:
                        continue
                    col_entry = {"column": col_name}
                    role = roles.get(col_name)
                    if role:
                        col_entry["role"] = role.get("role")
                        col_entry["role_confidence"] = role.get("confidence")
                    elif semantic_guess:
                        col_entry["role"] = semantic_guess
                        col_entry["role_confidence"] = confidence or "low"
                    if unit_guess:
                        col_entry["unit"] = unit_guess
                    derived.append(col_entry)
                    seen.add(col_name)
            if derived:
                payload["column_catalogue"] = derived

        if not payload.get("column_catalogue") or not payload.get("coverage_assessment"):
            inspect_report, rebuilt_catalogue, summary = _rebuild_from_file_entries(file_entries)
            if rebuilt_catalogue:
                payload["column_catalogue"] = rebuilt_catalogue
            if summary:
                payload["coverage_assessment"] = summary.get("coverage_assessment") or payload.get("coverage_assessment")
                payload.setdefault("global", {})
                payload["global"].setdefault("possible_joins_or_couplings", summary.get("possible_joins_or_couplings") or [])
                payload["global"].setdefault("missing_or_ambiguous_data", summary.get("missing_or_ambiguous_data") or [])

    # Last-resort recovery: if column_catalogue is still empty, pull it from
    # the cached file_synthesis artifact (synthesize_file_understanding result).
    # Handles the case where the LLM reconstructed the artifact instead of
    # passing synthesize output verbatim, so file entries lack column_catalogue.
    if not payload.get("column_catalogue"):
        try:
            from core import session_store as _ss_mod
            synth_versions = _ss_mod.session_store.get_artifact_versions(session_key, "file_synthesis")
            if synth_versions:
                cached_summaries = (synth_versions[-1].get("payload") or {}).get("file_summaries") or []
                merged = []
                seen_cols: set = set()
                for summary in cached_summaries:
                    for col in (summary.get("column_catalogue") or []):
                        col_name = col.get("column") if isinstance(col, dict) else None
                        if col_name and col_name not in seen_cols:
                            merged.append(col)
                            seen_cols.add(col_name)
                if merged:
                    payload["column_catalogue"] = merged
        except Exception:
            pass

    coverage = payload.get("coverage_assessment")
    if not isinstance(coverage, dict) or not coverage:
        payload["coverage_assessment"] = {
            "status": "sufficient" if payload.get("column_catalogue") and file_entries else "partial",
            "format": None,
            "structural_signals": [],
            "semantic_signals": [],
            "gaps": [],
        }

    return payload


def synthesize_file_understanding(
    file_summaries,
    possible_joins,
    complementarity,
    temporal_coverage,
    spatial_coverage,
    coverage_assessment=None,
    session_key=None,
):
    """Synthesize the global Data Understanding block for a multi-file session.

    Passthrough structuré — the LLM provides the semantic synthesis (joins,
    coverage, complementarity). This tool validates the structure and returns
    a ready-to-use payload for create_data_understanding_draft.

    Args:
        file_summaries: list of summarize_understanding outputs, one per file.
        possible_joins: list of join descriptions; [] if none detected.
        complementarity: how the files complement each other scientifically.
        temporal_coverage: shared temporal extent, or "non applicable".
        spatial_coverage: shared spatial extent, or "non applicable".
        coverage_assessment: optional global coverage dict; computed from
            per-file statuses if omitted.
        session_key: optional — used for Langfuse tracing only.
    """
    from core.copepod_observability import trace_copepod_event

    global_block = {
        "possible_joins": list(possible_joins or []),
        "complementarity": str(complementarity or ""),
        "temporal_coverage": str(temporal_coverage or "non applicable"),
        "spatial_coverage": str(spatial_coverage or "non applicable"),
    }
    if coverage_assessment and isinstance(coverage_assessment, dict):
        global_block["coverage_assessment"] = coverage_assessment

    result = {
        "file_summaries": list(file_summaries or []),
        "global": global_block,
    }
    # Cache so _normalize can recover if LLM passes a reconstructed artifact
    if session_key:
        try:
            from core import session_store as _ss_mod
            _ss_mod.session_store.create_artifact_version(session_key, "file_synthesis", result)
        except Exception:
            pass
    trace_copepod_event(
        "multi_file_synthesis_created",
        session_key=session_key or "",
        output={
            "file_count": len(file_summaries or []),
            "joins_detected": len(possible_joins or []),
        },
    )
    return result


def create_data_understanding_draft(session_key, artifact):
    """Create a draft Data Understanding artifact version for a copepod session."""
    from copy import deepcopy
    from core.copepod_observability import trace_copepod_event
    from core.copepod_plan_workflow import (
        DATA_UNDERSTANDING_CONFIRMATION_REQUIRED,
        DATA_UNDERSTANDING_DRAFT_REQUIRED,
        PLAN_READY,
    )
    from core import session_store as session_store_module

    store = session_store_module.session_store
    phase = store.get_copepod_plan_phase(session_key)
    if phase not in {DATA_UNDERSTANDING_DRAFT_REQUIRED, DATA_UNDERSTANDING_CONFIRMATION_REQUIRED, PLAN_READY}:
        result = {
            "created": False,
            "blocking_reason": (
                "create_data_understanding_draft requires phase "
                f"'{DATA_UNDERSTANDING_DRAFT_REQUIRED}', current phase is '{phase}'."
            ),
        }
        trace_copepod_event(
            "data_understanding_draft_blocked",
            session_key=session_key,
            output=result,
        )
        return result

    normalized_artifact = _normalize_data_understanding_payload(session_key, artifact)

    draft = session_store_module.session_store.create_artifact_version(
        session_key,
        "data_understanding",
        normalized_artifact,
    )
    if phase == DATA_UNDERSTANDING_DRAFT_REQUIRED:
        store.set_copepod_plan_phase(
            session_key,
            DATA_UNDERSTANDING_CONFIRMATION_REQUIRED,
        )
    trace_copepod_event(
        "data_understanding_draft_created",
        session_key=session_key,
        output={
            "version_id": draft["version_id"],
            "status": draft["status"],
            "next_phase": store.get_copepod_plan_phase(session_key),
        },
    )
    return deepcopy(draft)


def activate_data_understanding(session_key, version_id):
    """Activate a Data Understanding version after user validation."""
    from core.copepod_observability import trace_copepod_event
    from core.copepod_plan_workflow import (
        DATA_UNDERSTANDING_CONFIRMATION_REQUIRED,
        GRAPH_CONTEXT_DRAFT_REQUIRED,
    )
    from core import session_store as session_store_module

    try:
        store = session_store_module.session_store
        phase = store.get_copepod_plan_phase(session_key)
        if phase != DATA_UNDERSTANDING_CONFIRMATION_REQUIRED:
            raise ValueError(
                "activate_data_understanding requires phase "
                f"'{DATA_UNDERSTANDING_CONFIRMATION_REQUIRED}', current phase is '{phase}'."
            )
        active = store.activate_artifact_version(
            session_key,
            "data_understanding",
            version_id,
        )
        store.set_copepod_plan_phase(session_key, GRAPH_CONTEXT_DRAFT_REQUIRED)
        trace_copepod_event(
            "data_understanding_activated",
            session_key=session_key,
            output={
                "version_id": active["version_id"],
                "status": active["status"],
                "next_phase": store.get_copepod_plan_phase(session_key),
            },
        )
        return active
    except (KeyError, ValueError) as exc:
        result = {"activated": False, "blocking_reason": str(exc)}
        trace_copepod_event(
            "data_understanding_activation_blocked",
            session_key=session_key,
            output=result,
        )
        return result


def create_graph_context_draft(session_key, artifact):
    """Create a draft Graph Context artifact version for a copepod session."""
    from core.copepod_observability import trace_copepod_event
    from core.copepod_plan_workflow import (
        GRAPH_CONTEXT_CONFIRMATION_REQUIRED,
        GRAPH_CONTEXT_DRAFT_REQUIRED,
        PLAN_READY,
    )

    du_version_id = artifact.get("data_understanding_version_id")
    if not du_version_id:
        result = {
            "created": False,
            "blocking_reason": "Graph Context requires data_understanding_version_id.",
        }
        trace_copepod_event(
            "graph_context_draft_blocked",
            session_key=session_key,
            output={"blocking_reason": result["blocking_reason"]},
        )
        return result

    from core import session_store as session_store_module

    store = session_store_module.session_store
    phase = store.get_copepod_plan_phase(session_key)
    if phase not in {GRAPH_CONTEXT_DRAFT_REQUIRED, GRAPH_CONTEXT_CONFIRMATION_REQUIRED, PLAN_READY}:
        blocking = (
            "create_graph_context_draft requires phase "
            f"'{GRAPH_CONTEXT_DRAFT_REQUIRED}', current phase is '{phase}'."
        )
        result = {"created": False, "blocking_reason": blocking}
        trace_copepod_event(
            "graph_context_draft_blocked",
            session_key=session_key,
            output={"blocking_reason": blocking},
        )
        return result

    active_du = session_store_module.session_store.get_active_artifact(
        session_key, "data_understanding"
    )
    # When retracting at PLAN_READY or re-drafting at CONFIRMATION_REQUIRED, the active DU is
    # already validated — use its version_id regardless of what the LLM provided.
    if phase in {GRAPH_CONTEXT_CONFIRMATION_REQUIRED, PLAN_READY}:
        if active_du is None:
            blocking = "No active Data Understanding found. Cannot create Graph Context draft."
            result = {"created": False, "blocking_reason": blocking}
            trace_copepod_event("graph_context_draft_blocked", session_key=session_key, output={"blocking_reason": blocking})
            return result
        du_version_id = active_du["version_id"]
        artifact = {**artifact, "data_understanding_version_id": du_version_id}
    elif active_du is None or active_du.get("version_id") != du_version_id:
        active_id = active_du.get("version_id") if active_du else None
        blocking = (
            f"data_understanding_version_id '{du_version_id}' does not match the active "
            f"Data Understanding version ('{active_id}'). "
            "Call get_active_data_understanding(session_key) to get the correct version_id."
        )
        result = {"created": False, "blocking_reason": blocking}
        trace_copepod_event(
            "graph_context_draft_blocked",
            session_key=session_key,
            output={"blocking_reason": blocking},
        )
        return result

    from copy import deepcopy

    draft = session_store_module.session_store.create_artifact_version(
        session_key,
        "graph_context",
        artifact,
    )
    if phase == GRAPH_CONTEXT_DRAFT_REQUIRED:
        store.set_copepod_plan_phase(session_key, GRAPH_CONTEXT_CONFIRMATION_REQUIRED)
    trace_copepod_event(
        "graph_context_draft_created",
        session_key=session_key,
        output={
            "version_id": draft["version_id"],
            "status": draft["status"],
            "data_understanding_version_id": du_version_id,
            "next_phase": store.get_copepod_plan_phase(session_key),
        },
    )
    return deepcopy(draft)


def activate_graph_context(session_key, version_id):
    """Activate a Graph Context version after user validation."""
    from core.copepod_observability import trace_copepod_event
    from core.copepod_plan_workflow import GRAPH_CONTEXT_CONFIRMATION_REQUIRED, PLAN_READY
    from core import session_store as session_store_module

    try:
        store = session_store_module.session_store
        phase = store.get_copepod_plan_phase(session_key)
        if phase != GRAPH_CONTEXT_CONFIRMATION_REQUIRED:
            raise ValueError(
                "activate_graph_context requires phase "
                f"'{GRAPH_CONTEXT_CONFIRMATION_REQUIRED}', current phase is '{phase}'."
            )
        active = store.activate_artifact_version(
            session_key,
            "graph_context",
            version_id,
        )
        store.set_copepod_plan_phase(session_key, PLAN_READY)
        trace_copepod_event(
            "graph_context_activated",
            session_key=session_key,
            output={
                "version_id": active["version_id"],
                "status": active["status"],
                "next_phase": store.get_copepod_plan_phase(session_key),
            },
        )
        return active
    except (KeyError, ValueError) as exc:
        result = {"activated": False, "blocking_reason": str(exc)}
        trace_copepod_event(
            "graph_context_activation_blocked",
            session_key=session_key,
            output=result,
        )
        return result


def get_active_data_understanding(session_key):
    """Return the active Data Understanding artifact for a copepod session."""
    from core import session_store as session_store_module
    return session_store_module.session_store.get_active_artifact(
        session_key,
        "data_understanding",
    )


def get_active_graph_context(session_key):
    """Return the active Graph Context artifact for a copepod session."""
    from core import session_store as session_store_module
    return session_store_module.session_store.get_active_artifact(
        session_key,
        "graph_context",
    )
'''

registry.register(Tool(
    name="copepod_session_artifacts",
    tags=frozenset({"copepod_artifacts"}),
    code=_code,
))
