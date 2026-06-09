"""TDD — artefact Open WebUI pour configurer DATABASE_URL."""

from pathlib import Path


def test_openwebui_sql_workspace_setup_prompt_contains_database_url_variable():
    prompt_path = Path("docs/openwebui/sql_workspace_setup_prompt.md")
    assert prompt_path.exists()

    content = prompt_path.read_text(encoding="utf-8")
    assert "{{database_url" in content
    assert "DATABASE_URL" in content
    assert "Open WebUI" in content
