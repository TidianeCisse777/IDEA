"""TDD — user_id dans les logs de conversation locaux."""

import json


def test_log_turn_includes_user_id(tmp_path, monkeypatch):
    import serve as serve_module
    import agent as agent_module

    monkeypatch.setattr(serve_module, "LOGS_DIR", tmp_path)
    agent_module.clear_context_audit()

    serve_module._log_turn(
        "thread-abc",
        "question ?",
        "réponse.",
        {"input_tokens": 10, "output_tokens": 5},
        user_id="user-alice",
    )

    log_file = tmp_path / "thread-abc.jsonl"
    assert log_file.exists()
    entry = json.loads(log_file.read_text())
    assert entry["user_id"] == "user-alice"
    assert entry["context_audit"] == {}


def test_log_turn_defaults_user_id_to_anonymous(tmp_path, monkeypatch):
    import serve as serve_module

    monkeypatch.setattr(serve_module, "LOGS_DIR", tmp_path)

    serve_module._log_turn(
        "thread-xyz",
        "question ?",
        "réponse.",
        {"input_tokens": 10, "output_tokens": 5},
    )

    log_file = tmp_path / "thread-xyz.jsonl"
    entry = json.loads(log_file.read_text())
    assert entry["user_id"] == "anonymous"


def test_log_turn_includes_context_audit_metrics(tmp_path, monkeypatch):
    import agent as agent_module
    import serve as serve_module

    monkeypatch.setattr(serve_module, "LOGS_DIR", tmp_path)
    agent_module.clear_context_audit()
    agent_module._context_audit_by_thread["thread-audit"] = {
        "approx_tokens_before": 120,
        "approx_tokens_after_trim": 80,
        "messages_trimmed": 2,
        "tool_messages_truncated": 1,
    }

    serve_module._log_turn(
        "thread-audit",
        "question ?",
        "réponse.",
        {"prompt_tokens": 10, "completion_tokens": 5},
        user_id="user-audit",
    )

    entry = json.loads((tmp_path / "thread-audit.jsonl").read_text())
    assert entry["context_audit"]["approx_tokens_before"] == 120
    assert entry["context_audit"]["approx_tokens_after_trim"] == 80
    assert entry["context_audit"]["tool_messages_truncated"] == 1


def test_debug_context_audit_endpoint_returns_latest_metrics():
    import agent as agent_module
    import serve as serve_module

    agent_module.clear_context_audit()
    agent_module._context_audit_by_thread["thread-debug"] = {
        "approx_tokens_before": 42,
        "approx_tokens_after_trim": 21,
    }

    response = serve_module.debug_context_audit("thread-debug")

    assert response["thread_id"] == "thread-debug"
    assert response["audit"]["approx_tokens_before"] == 42
