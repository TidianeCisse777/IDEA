from pathlib import Path


def test_share_start_script_uses_project_env_only():
    script = Path("share_start.sh").read_text()

    assert "docker compose --env-file .env up -d --build" in script
    assert 'env -i PATH="$PATH" HOME="$HOME"' in script
    assert "Copy share.env.example to .env" in script


def test_share_env_example_is_placeholder_only():
    content = Path("share.env.example").read_text()

    assert "replace-me" in content
    assert "OPENAI_API_KEY=replace-me" in content
    assert "/Users/tidianecisse" not in content
