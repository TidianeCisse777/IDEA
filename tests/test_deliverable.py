"""Tests TDD — export_deliverable tool + deliverable_writer skill."""
import builtins
import os

import pytest
from pathlib import Path
from unittest.mock import patch


def _manifest():
    return {
        "study_context": {
            "objective": "Analyser les copépodes sélectionnés",
            "geographic_scope": "Baie de Baffin",
            "temporal_scope": "2014–2020",
            "taxonomic_scope": "Copepoda",
            "projects": ["17498"],
            "samples": ["17498000001", "17498000002"],
            "selection_criteria": "Samples situés dans la zone et la période demandées",
        },
        "sources": [
            {
                "name": "EcoTaxa — projet 17498",
                "source": "ecotaxa:17498",
                "project_id": 17498,
                "url": "https://ecotaxa.obs-vlfr.fr/prj/17498",
                "citation": "Picheral, M., Colin, S., & Irisson, J.-O. (2017). EcoTaxa.",
            }
        ],
        "operations": [],
    }


# --- Comportement 1 : export_deliverable retourne une URL téléchargeable ---

def test_export_deliverable_returns_download_url(tmp_path, monkeypatch):
    monkeypatch.setenv("DOWNLOADS_DIR", str(tmp_path))
    from tools.deliverable_tool import export_deliverable
    result = export_deliverable.invoke({
        "content": "# Rapport\n\nTexte.",
        "filename": "rapport_test",
        "traceability_manifest": _manifest(),
    })
    assert "http" in result or "/downloads/" in result


# --- Comportement 2 : le fichier est bien écrit sur disque ---

def test_export_deliverable_writes_file(tmp_path, monkeypatch):
    monkeypatch.setenv("DOWNLOADS_DIR", str(tmp_path))
    from tools.deliverable_tool import export_deliverable
    export_deliverable.invoke({
        "content": "# Mon rapport",
        "filename": "rapport_test",
        "traceability_manifest": _manifest(),
    })
    files = list(tmp_path.glob("rapport_test.*"))
    assert len(files) == 1
    raw = files[0].read_bytes()
    # PDF: starts with %PDF; HTML fallback: contains the title text
    assert raw.startswith(b"%PDF") or b"Mon rapport" in raw


# --- Comportement 3 : filename stem présent dans l'URL retournée ---

def test_export_deliverable_adds_extension(tmp_path, monkeypatch):
    monkeypatch.setenv("DOWNLOADS_DIR", str(tmp_path))
    from tools.deliverable_tool import export_deliverable
    result = export_deliverable.invoke({
        "content": "# Test",
        "filename": "mon_rapport",
        "traceability_manifest": _manifest(),
    })
    assert "mon_rapport" in result


def test_export_deliverable_configures_homebrew_library_path(tmp_path, monkeypatch):
    monkeypatch.setenv("DOWNLOADS_DIR", str(tmp_path))
    monkeypatch.delenv("DYLD_FALLBACK_LIBRARY_PATH", raising=False)
    monkeypatch.setattr("tools.deliverable_tool.sys.platform", "darwin")
    monkeypatch.setattr(
        "tools.deliverable_tool._homebrew_library_dirs",
        lambda: [Path("/opt/homebrew/lib")],
    )

    from tools.deliverable_tool import export_deliverable

    export_deliverable.invoke({
        "content": "# Rapport",
        "filename": "homebrew_path",
        "traceability_manifest": _manifest(),
    })

    assert os.environ["DYLD_FALLBACK_LIBRARY_PATH"].split(os.pathsep)[0] == "/opt/homebrew/lib"


def test_export_deliverable_falls_back_to_html_when_native_library_is_missing(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("DOWNLOADS_DIR", str(tmp_path))
    from tools.deliverable_tool import export_deliverable

    real_import = builtins.__import__

    def fail_weasyprint_import(name, *args, **kwargs):
        if name == "weasyprint":
            raise OSError("cannot load library 'libgobject-2.0-0'")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=fail_weasyprint_import):
        result = export_deliverable.invoke({
            "content": "# Rapport de secours",
            "filename": "rapport_fallback",
            "traceability_manifest": _manifest(),
        })

    assert "HTML disponible" in result
    assert (tmp_path / "rapport_fallback.html").exists()


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


def test_deliverable_instructions_require_manifest_and_all_operation_statuses():
    skill = Path("agents/skills/deliverable_writer.md").read_text().lower()
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    assert "traceability_manifest" in skill
    assert "réussie" in skill
    assert "partielle" in skill
    assert "échouée" in skill
    assert "non confirmée" in skill
    assert "geographic_scope" in skill
    assert "temporal_scope" in skill
    assert "selection_criteria" in skill
    assert "traceability_manifest" in COPEPOD_SYSTEM_PROMPT
    assert "study_context" in COPEPOD_SYSTEM_PROMPT


def test_export_deliverable_rejects_reference_url_absent_from_manifest(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("DOWNLOADS_DIR", str(tmp_path))
    from tools.deliverable_tool import export_deliverable

    result = export_deliverable.invoke({
        "content": (
            "# Rapport\n\n"
            "## 6. Références\n\n"
            "Source inventée. https://example.org/not-used"
        ),
        "filename": "rapport_invalide",
        "traceability_manifest": _manifest(),
    })

    assert "Livrable refusé" in result
    assert "https://example.org/not-used" in result
    assert not list(tmp_path.iterdir())


def test_export_deliverable_accepts_reference_url_declared_in_manifest(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("DOWNLOADS_DIR", str(tmp_path))
    from tools.deliverable_tool import export_deliverable

    result = export_deliverable.invoke({
        "content": (
            "# Rapport\n\n"
            "## 6. Références\n\n"
            "EcoTaxa. https://ecotaxa.obs-vlfr.fr/prj/17498"
        ),
        "filename": "rapport_valide",
        "traceability_manifest": _manifest(),
    })

    assert "Livrable refusé" not in result
    assert list(tmp_path.glob("rapport_valide.*"))


def test_export_deliverable_renders_detailed_failed_enrichment_in_audit_journal(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("DOWNLOADS_DIR", str(tmp_path))
    from tools.deliverable_tool import _render_traceability_journal

    manifest = _manifest()
    manifest["operations"] = [
        {
            "category": "enrichissement",
            "title": "Jointure EcoTaxa–EcoPart",
            "status": "échouée",
            "input": "Export EcoTaxa du projet 17498",
            "parameters": "Clés sample_id et depth_bin",
            "result": "Aucune correspondance",
            "coverage": "0 ligne correspondante sur 50",
            "limitations": "Les fichiers proviennent de campagnes différentes.",
        }
    ]

    journal = _render_traceability_journal(manifest)

    assert "Jointure EcoTaxa–EcoPart" in journal
    assert "Aucune correspondance" in journal
    assert "0 ligne correspondante sur 50" in journal
    assert "échouée" in journal


def test_reference_section_is_rebuilt_only_from_manifest_sources():
    from tools.deliverable_tool import _replace_reference_section

    content = (
        "# Rapport\n\n"
        "## 6. Références\n\n"
        "Bio-ORACLE, citation ajoutée par erreur sans avoir utilisé cette source."
    )

    rebuilt = _replace_reference_section(content, _manifest())

    assert "Bio-ORACLE" not in rebuilt
    assert "Picheral, M., Colin, S., & Irisson, J.-O. (2017). EcoTaxa." in rebuilt
    assert "https://ecotaxa.obs-vlfr.fr/prj/17498" in rebuilt


def test_reference_section_drops_unproven_project_url():
    from tools.deliverable_tool import _replace_reference_section

    manifest = _manifest()
    manifest["sources"] = [{
        "name": "Fichier Hawke",
        "source": "file:/app/hawke.tsv",
        "url": "https://ecopart.obs-vlfr.fr/prj/42",
    }]

    rebuilt = _replace_reference_section("# Rapport", manifest)

    assert "/app/hawke.tsv" in rebuilt
    assert "/prj/42" not in rebuilt


def test_manifest_source_urls_include_declared_doi():
    from tools.deliverable_tool import _manifest_source_urls

    manifest = _manifest()
    manifest["sources"][0]["doi"] = "10.1234/ecotaxa.17498"

    urls = _manifest_source_urls(manifest)

    # Le DOI est autorisé sous ses deux formes usuelles.
    assert "https://doi.org/10.1234/ecotaxa.17498" in urls
    assert "10.1234/ecotaxa.17498" in urls


def test_manifest_source_urls_harvest_urls_embedded_in_citation():
    from tools.deliverable_tool import _manifest_source_urls

    manifest = _manifest()
    manifest["sources"][0]["citation"] = (
        "Picheral et al. (2017). EcoTaxa. https://doi.org/10.5555/ecopart"
    )

    urls = _manifest_source_urls(manifest)

    assert "https://doi.org/10.5555/ecopart" in urls


def test_export_deliverable_accepts_reference_doi_declared_in_manifest(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("DOWNLOADS_DIR", str(tmp_path))
    from tools.deliverable_tool import export_deliverable

    manifest = _manifest()
    manifest["sources"][0]["doi"] = "10.1234/ecotaxa.17498"

    result = export_deliverable.invoke({
        "content": (
            "# Rapport\n\n"
            "## 6. Références\n\n"
            "EcoTaxa. https://ecotaxa.obs-vlfr.fr/prj/17498 "
            "https://doi.org/10.1234/ecotaxa.17498"
        ),
        "filename": "rapport_doi_ok",
        "traceability_manifest": manifest,
    })

    assert "Livrable refusé" not in result
    assert list(tmp_path.glob("rapport_doi_ok.*"))


def test_export_deliverable_still_rejects_undeclared_doi(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("DOWNLOADS_DIR", str(tmp_path))
    from tools.deliverable_tool import export_deliverable

    result = export_deliverable.invoke({
        "content": (
            "# Rapport\n\n"
            "## 6. Références\n\n"
            "EcoTaxa. https://ecotaxa.obs-vlfr.fr/prj/17498 "
            "https://doi.org/10.9999/non-declare"
        ),
        "filename": "rapport_doi_ko",
        "traceability_manifest": _manifest(),
    })

    assert "Livrable refusé" in result
    assert "https://doi.org/10.9999/non-declare" in result
    assert not list(tmp_path.iterdir())


def test_export_deliverable_rejects_missing_required_study_context(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("DOWNLOADS_DIR", str(tmp_path))
    from tools.deliverable_tool import export_deliverable

    manifest = _manifest()
    del manifest["study_context"]["geographic_scope"]

    result = export_deliverable.invoke({
        "content": "# Rapport",
        "filename": "sans_zone",
        "traceability_manifest": manifest,
    })

    assert "Livrable refusé" in result
    assert "geographic_scope" in result
    assert not list(tmp_path.iterdir())


def test_study_context_summary_renders_scope_projects_samples_and_criteria():
    from tools.deliverable_tool import _render_study_context

    summary = _render_study_context(_manifest())

    assert "Baie de Baffin" in summary
    assert "2014–2020" in summary
    assert "Copepoda" in summary
    assert "17498" in summary
    assert "17498000001" in summary
    assert "Samples situés dans la zone" in summary
