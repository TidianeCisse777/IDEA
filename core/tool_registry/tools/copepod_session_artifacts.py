from core.tool_registry.registry import Tool, registry

_code = '''
def _normalize_data_understanding_payload(session_key, artifact):
    """Ensure a DU draft keeps the summary fields the UI/tests rely on."""
    from copy import deepcopy
    from pathlib import Path
    from routers.file_routes import STATIC_DIR, UPLOAD_DIR

    payload = deepcopy(artifact or {})

    user_id, session_id, *_ = (session_key or "::").split(":")
    upload_root = STATIC_DIR / user_id / session_id / UPLOAD_DIR

    def _load_data_tools():
        from core.tool_registry import registry
        from core.tool_registry.tools import copepod_data  # noqa: F401

        ns = {}
        exec(registry.render({"copepod_data"}), ns)
        return ns

    def _rebuild_from_file_entries(file_entries):
        tools = _load_data_tools()
        columns = []
        roles = []
        inspect_report = None
        candidate_entries = list(file_entries or [])
        if not candidate_entries and upload_root.exists():
            candidate_entries = [
                {"file_path": str(path), "original_filename": path.name}
                for path in sorted(upload_root.iterdir())
                if path.is_file()
            ]
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
            roles.extend(role_report.get("roles") or [])
        return inspect_report, columns, roles, summary if "summary" in locals() else None

    column_catalogue = payload.get("column_catalogue") or []
    if not column_catalogue:
        derived = []
        seen = set()
        for file_entry in payload.get("files") or []:
            columns = file_entry.get("columns") or []
            roles = {
                r.get("column"): r
                for r in (file_entry.get("roles") or [])
                if isinstance(r, dict) and r.get("column")
            }
            for col in columns:
                if isinstance(col, dict):
                    col_name = col.get("name")
                    semantic_guess = col.get("semantic_guess")
                    unit_guess = col.get("unit_guess")
                    confidence = col.get("confidence")
                else:
                    col_name = str(col)
                    semantic_guess = None
                    unit_guess = None
                    confidence = None
                if not col_name or col_name in seen:
                    continue
                entry = {"column": col_name}
                role = roles.get(col_name)
                if role:
                    entry["role"] = role.get("role")
                    entry["role_confidence"] = role.get("confidence")
                elif semantic_guess:
                    entry["role"] = semantic_guess
                    entry["role_confidence"] = confidence or "low"
                if unit_guess:
                    entry["unit"] = unit_guess
                derived.append(entry)
                seen.add(col_name)
        if derived:
            payload["column_catalogue"] = derived

    # If the model sent only a shell of the DU draft, rebuild from the file(s).
    if not payload.get("column_catalogue") or not payload.get("coverage_assessment"):
        inspect_report, rebuilt_catalogue, _, summary = _rebuild_from_file_entries(payload.get("files") or [])
        if rebuilt_catalogue:
            payload["column_catalogue"] = rebuilt_catalogue
        if summary:
            payload["coverage_assessment"] = summary.get("coverage_assessment") or payload.get("coverage_assessment")
            payload.setdefault("global", {})
            payload["global"].setdefault("possible_joins_or_couplings", summary.get("possible_joins_or_couplings") or [])
            payload["global"].setdefault("missing_or_ambiguous_data", summary.get("missing_or_ambiguous_data") or [])
            payload["metadata_detected"] = inspect_report.get("metadata") if inspect_report else payload.get("metadata_detected")

    coverage = payload.get("coverage_assessment")
    if not isinstance(coverage, dict) or not coverage:
        payload["coverage_assessment"] = {
            "status": "sufficient" if payload.get("column_catalogue") and payload.get("files") else "partial",
            "format": payload.get("coverage_assessment", {}).get("format") if isinstance(coverage, dict) else None,
            "structural_signals": [],
            "semantic_signals": [],
            "gaps": [],
        }

    return payload


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
