"""Tests TDD — export_deliverable tool + deliverable_writer skill."""
import pytest
from pathlib import Path
from unittest.mock import patch


# --- Comportement 1 : export_deliverable retourne une URL téléchargeable ---

def test_export_deliverable_returns_download_url(tmp_path, monkeypatch):
    monkeypatch.setenv("DOWNLOADS_DIR", str(tmp_path))
    from tools.deliverable_tool import export_deliverable
    result = export_deliverable.invoke({"content": "# Rapport\n\nTexte.", "filename": "rapport_test"})
    assert "http" in result or "/downloads/" in result


# --- Comportement 2 : le fichier est bien écrit sur disque ---

def test_export_deliverable_writes_file(tmp_path, monkeypatch):
    monkeypatch.setenv("DOWNLOADS_DIR", str(tmp_path))
    from tools.deliverable_tool import export_deliverable
    export_deliverable.invoke({"content": "# Mon rapport", "filename": "rapport_test"})
    files = list(tmp_path.glob("rapport_test.*"))
    assert len(files) == 1
    raw = files[0].read_bytes()
    # PDF: starts with %PDF; HTML fallback: contains the title text
    assert raw.startswith(b"%PDF") or b"Mon rapport" in raw


# --- Comportement 3 : filename stem présent dans l'URL retournée ---

def test_export_deliverable_adds_extension(tmp_path, monkeypatch):
    monkeypatch.setenv("DOWNLOADS_DIR", str(tmp_path))
    from tools.deliverable_tool import export_deliverable
    result = export_deliverable.invoke({"content": "# Test", "filename": "mon_rapport"})
    assert "mon_rapport" in result


# --- Comportement 4 : skill deliverable_writer existe et est chargeable ---

def test_deliverable_writer_skill_exists():
    skill_path = Path("agents/skills/deliverable_writer.md")
    assert skill_path.exists()
    content = skill_path.read_text()
    assert "## Sections" in content or "## Structure" in content


# --- Comportement 5 : skill mentionne figures, sources, limites ---

def test_deliverable_writer_skill_covers_figures_sources_limitations():
    skill_path = Path("agents/skills/deliverable_writer.md")
    content = skill_path.read_text().lower()
    assert "figure" in content or "graphique" in content
    assert "source" in content
    assert "limit" in content


# --- Comportement 6 : system prompt route les demandes de livrable ---

def test_system_prompt_routes_deliverable_requests():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT
    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "deliverable_writer" in prompt
    assert "export_deliverable" in prompt
