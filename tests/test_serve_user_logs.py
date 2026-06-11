"""TDD — user_id dans les logs de conversation locaux."""

import json


def test_log_turn_includes_user_id(tmp_path, monkeypatch):
    import serve as serve_module

    monkeypatch.setattr(serve_module, "LOGS_DIR", tmp_path)

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
