from core.tool_registry.registry import Tool, registry

_code = '''
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
    if phase not in {DATA_UNDERSTANDING_DRAFT_REQUIRED, PLAN_READY}:
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

    draft = session_store_module.session_store.create_artifact_version(
        session_key,
        "data_understanding",
        artifact,
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
    if phase != GRAPH_CONTEXT_DRAFT_REQUIRED:
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
    if active_du is None or active_du.get("version_id") != du_version_id:
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
