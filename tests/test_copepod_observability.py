from core.copepod_observability import trace_copepod_event


def test_trace_copepod_event_never_raises_when_langfuse_unavailable(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "langfuse":
            raise ImportError("langfuse unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    trace_copepod_event(
        "data_understanding_draft_created",
        session_key="u1:s1:copepod",
        output={"version_id": "du-test"},
    )
