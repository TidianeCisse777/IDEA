"""TDD — runner de conversations E2E avec artefacts locaux."""
from pathlib import Path


def test_parse_sse_collects_content_and_usage():
    from scripts.run_baffin_e2e import parse_sse

    raw = "\n".join([
        'data: {"choices":[{"delta":{"content":"Bonjour "}}]}',
        'data: {"choices":[{"delta":{"content":"monde"}}]}',
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":10,"completion_tokens":2}}',
        "data: [DONE]",
    ])

    parsed = parse_sse(raw)

    assert parsed.content == "Bonjour monde"
    assert parsed.usage == {"prompt_tokens": 10, "completion_tokens": 2}


def test_classify_turn_rejects_stream_and_tool_errors():
    from scripts.run_baffin_e2e import classify_turn, is_retryable_turn

    assert classify_turn("Résultat normal") == "passed"
    assert classify_turn("[Erreur : API indisponible]") == "failed"
    assert classify_turn("Erreur EcoPart : tâche refusée") == "failed"
    assert is_retryable_turn("[Erreur : Error code: 429 - rate_limit_exceeded]")
    assert not is_retryable_turn("[Erreur : 404 projet absent]")


def test_extract_assets_finds_graphs_and_pdf_without_duplicates():
    from scripts.run_baffin_e2e import extract_asset_urls

    text = """
    ![Graphe](http://localhost:8000/graphs/a.png)
    encore http://localhost:8000/graphs/a.png
    PDF généré : http://localhost:8000/downloads/rapport.pdf
    """

    assets = extract_asset_urls(text)

    assert assets == [
        "http://localhost:8000/graphs/a.png",
        "http://localhost:8000/downloads/rapport.pdf",
    ]


def test_write_artifacts_records_user_and_assistant_turns(tmp_path):
    from scripts.run_baffin_e2e import TurnRecord, write_artifacts

    records = [
        TurnRecord(1, "exploration", "Question", "Réponse", "passed", {}),
        TurnRecord(2, "export", "Confirme", "[Erreur : test]", "failed", {}),
    ]

    write_artifacts(tmp_path, "chat-123", records)

    transcript = (tmp_path / "conversation.md").read_text()
    assert "## Tour 1 — exploration" in transcript
    assert "### Utilisateur\n\nQuestion" in transcript
    assert "### Assistant\n\nRéponse" in transcript
    assert (tmp_path / "transcript.json").exists()
    assert '"status": "failed"' in (tmp_path / "validation.json").read_text()


def test_scenario_has_full_e2e_sequence_and_final_deliverable():
    from scripts.run_baffin_e2e import SCENARIO_TURNS

    names = [turn.name for turn in SCENARIO_TURNS]
    assert names == [
        "exploration",
        "selection",
        "export_plan",
        "export_confirm",
        "ecopart_plan",
        "ecopart_confirm",
        "amundsen_enrichment",
        "analysis",
        "graph",
        "deliverable",
    ]
    assert "livrable PDF" in SCENARIO_TURNS[-1].prompt


def test_load_existing_records_allows_same_chat_resume(tmp_path):
    from scripts.run_baffin_e2e import TurnRecord, load_existing_records, write_artifacts

    records = [TurnRecord(1, "exploration", "Q", "R", "passed", {})]
    write_artifacts(tmp_path, "chat-resume", records)

    chat_id, loaded = load_existing_records(tmp_path)

    assert chat_id == "chat-resume"
    assert loaded == records
