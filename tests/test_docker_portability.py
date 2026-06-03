from __future__ import annotations

from pathlib import Path


def test_local_docker_stack_has_no_personal_absolute_path_mounts():
    override = Path(__file__).resolve().parents[1] / "docker-compose.override.yml"
    text = override.read_text(encoding="utf-8")

    assert "/Users/tidianecisse/PROJET_INFO/assistant-copepodes-specs" not in text
