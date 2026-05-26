from core.tool_registry.registry import Tool, registry

_code = '''
def create_data_understanding_draft(session_key, artifact):
    """Create a draft Data Understanding artifact version for a copepod session."""
    from copy import deepcopy
    from core.copepod_observability import trace_copepod_event
    from core import session_store as session_store_module

    draft = session_store_module.session_store.create_artifact_version(
        session_key,
        "data_understanding",
        artifact,
    )
    trace_copepod_event(
        "data_understanding_draft_created",
        session_key=session_key,
        output={"version_id": draft["version_id"], "status": draft["status"]},
    )
    return deepcopy(draft)


def activate_data_understanding(session_key, version_id):
    """Activate a Data Understanding version after user validation."""
    from core.copepod_observability import trace_copepod_event
    from core import session_store as session_store_module

    try:
        active = session_store_module.session_store.activate_artifact_version(
            session_key,
            "data_understanding",
            version_id,
        )
        trace_copepod_event(
            "data_understanding_activated",
            session_key=session_key,
            output={"version_id": active["version_id"], "status": active["status"]},
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

    if not artifact.get("data_understanding_version_id"):
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

    from copy import deepcopy
    from core import session_store as session_store_module

    draft = session_store_module.session_store.create_artifact_version(
        session_key,
        "graph_context",
        artifact,
    )
    trace_copepod_event(
        "graph_context_draft_created",
        session_key=session_key,
        output={
            "version_id": draft["version_id"],
            "status": draft["status"],
            "data_understanding_version_id": artifact["data_understanding_version_id"],
        },
    )
    return deepcopy(draft)


def activate_graph_context(session_key, version_id):
    """Activate a Graph Context version after user validation."""
    from core.copepod_observability import trace_copepod_event
    from core import session_store as session_store_module

    try:
        active = session_store_module.session_store.activate_artifact_version(
            session_key,
            "graph_context",
            version_id,
        )
        trace_copepod_event(
            "graph_context_activated",
            session_key=session_key,
            output={"version_id": active["version_id"], "status": active["status"]},
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
