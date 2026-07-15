"""Tool export_deliverable — compile un livrable scientifique en PDF."""
from __future__ import annotations

import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any

from langchain_core.tools import tool
from core.runtime_paths import graphs_dir
from tools.source_renderer import render_sources, source_urls

def _downloads_dir() -> Path:
    return Path(os.getenv("DOWNLOADS_DIR", "/tmp/copepod_downloads"))

_GRAPHS_DIR = graphs_dir()

_CSS = """
@import url('https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,600;1,400&display=swap');

body {
    font-family: 'EB Garamond', Georgia, serif;
    font-size: 11pt;
    line-height: 1.6;
    color: #111;
    margin: 0;
    padding: 0;
}
@page {
    size: A4;
    margin: 2.5cm 2.5cm 2.5cm 2.5cm;
    @top-center {
        content: string(doc-title);
        font-family: Georgia, serif;
        font-size: 9pt;
        color: #555;
    }
    @bottom-right {
        content: counter(page) " / " counter(pages);
        font-size: 9pt;
        color: #555;
    }
}
h1 {
    string-set: doc-title content();
    font-size: 18pt;
    font-weight: 600;
    border-bottom: 2px solid #222;
    padding-bottom: 6pt;
    margin-top: 0;
}
h2 { font-size: 13pt; font-weight: 600; margin-top: 1.8em; border-bottom: 1px solid #ccc; padding-bottom: 3pt; }
h3 { font-size: 11pt; font-weight: 600; margin-top: 1.2em; }
p { margin: 0.5em 0 0.8em 0; text-align: justify; }
figure { margin: 1.5em 0; text-align: center; page-break-inside: avoid; }
figure img { max-width: 90%; border: 1px solid #ddd; }
figcaption { font-size: 9.5pt; color: #444; margin-top: 6pt; font-style: italic; }
table { border-collapse: collapse; width: 100%; font-size: 10pt; margin: 1em 0; }
th { background: #f0f0f0; border: 1px solid #bbb; padding: 5pt 8pt; text-align: left; font-weight: 600; }
td { border: 1px solid #bbb; padding: 4pt 8pt; }
blockquote { border-left: 3px solid #999; margin: 1em 0; padding: 0 1em; color: #555; font-style: italic; }
code { font-family: monospace; font-size: 9.5pt; background: #f5f5f5; padding: 1pt 3pt; }
ul, ol { margin: 0.5em 0; padding-left: 1.5em; }
li { margin-bottom: 0.3em; }
.metadata { color: #555; font-size: 10pt; margin-bottom: 2em; }
"""


def _homebrew_library_dirs() -> list[Path]:
    """Return common Homebrew library directories containing WeasyPrint deps."""
    return [Path("/opt/homebrew/lib"), Path("/usr/local/lib")]


def _configure_weasyprint_library_path() -> None:
    """Make Homebrew native libraries visible before importing WeasyPrint."""
    if sys.platform != "darwin":
        return
    available = [str(path) for path in _homebrew_library_dirs() if path.is_dir()]
    if not available:
        return
    existing = [
        path
        for path in os.getenv("DYLD_FALLBACK_LIBRARY_PATH", "").split(os.pathsep)
        if path
    ]
    os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = os.pathsep.join(
        dict.fromkeys([*available, *existing])
    )


def _write_html_fallback(downloads: Path, safe: str, html: str) -> str:
    html_path = downloads / f"{safe}.html"
    html_path.write_text(html, encoding="utf-8")
    base = os.getenv("SERVE_BASE_URL", "http://localhost:8000")
    return f"WeasyPrint non disponible — HTML disponible : {base}/downloads/{safe}.html"


def _replace_graph_urls(markdown: str) -> str:
    """Remplace les URLs http://…/graphs/{id}.png par des chemins file://."""
    def sub(m):
        filename = m.group(1)
        local = _GRAPHS_DIR / filename
        if local.exists():
            return f"file://{local}"
        return m.group(0)
    return re.sub(r"http[^\s\"')]+/graphs/([^)\s\"']+\.png)", sub, markdown)


def _reference_urls(markdown: str) -> set[str]:
    """Return URLs written in the report references section only."""
    match = re.search(
        r"^##\s+(?:\d+\.\s*)?Références\s*$([\s\S]*?)(?=^##\s|\Z)",
        markdown,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if not match:
        return set()
    return {
        url.rstrip(".,;)")
        for url in re.findall(r"https?://[^\s<>\]]+", match.group(1))
    }


def _normalize_doi(value: str) -> set[str]:
    """Return the accepted forms of a declared DOI (bare id + doi.org URL)."""
    raw = value.strip().rstrip("/")
    if not raw:
        return set()
    bare = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", raw, flags=re.IGNORECASE)
    forms = {raw}
    if bare:
        forms.add(bare)
        forms.add(f"https://doi.org/{bare}")
    return forms


def _manifest_source_urls(manifest: dict[str, Any]) -> set[str]:
    """URLs a report may legitimately cite: only those a declared source carries.

    Covers `url`, `urls`, a declared `doi`/`dois`, and any http(s) URL embedded in
    the free-text `citation`/`name` of a declared source. Anything not declared as
    a used source stays out — irrelevant links are still rejected downstream.
    """
    urls: set[str] = set()
    for source in manifest.get("sources", []):
        if not isinstance(source, dict):
            continue
        urls.update(source_urls(source))
        dois = [source.get("doi"), *source.get("dois", [])]
        for doi in dois:
            if isinstance(doi, str) and doi.strip():
                urls.update(form.rstrip("/") for form in _normalize_doi(doi))
        for field in ("citation", "name"):
            text = source.get(field)
            if isinstance(text, str):
                for embedded in re.findall(r"https?://[^\s<>\]]+", text):
                    urls.add(embedded.rstrip(".,;)").rstrip("/"))
    return urls


def _validate_reference_sources(
    content: str,
    manifest: dict[str, Any],
) -> list[str]:
    allowed = _manifest_source_urls(manifest)
    return sorted(
        url for url in _reference_urls(content) if url.rstrip("/") not in allowed
    )


_REQUIRED_CONTEXT_FIELDS = (
    "objective",
    "geographic_scope",
    "temporal_scope",
    "taxonomic_scope",
    "selection_criteria",
)


def _missing_study_context_fields(manifest: dict[str, Any]) -> list[str]:
    context = manifest.get("study_context")
    if not isinstance(context, dict):
        return list(_REQUIRED_CONTEXT_FIELDS)
    return [
        field
        for field in _REQUIRED_CONTEXT_FIELDS
        if not isinstance(context.get(field), str) or not context[field].strip()
    ]


def _render_study_context(manifest: dict[str, Any]) -> str:
    context = manifest.get("study_context", {})
    projects = ", ".join(str(item) for item in context.get("projects", [])) or "Aucun"
    samples = ", ".join(str(item) for item in context.get("samples", [])) or "Aucun"
    return "\n".join(
        [
            "## Cadre de l'étude",
            "",
            f"- **Objectif :** {context.get('objective', '')}",
            f"- **Zone géographique :** {context.get('geographic_scope', '')}",
            f"- **Période :** {context.get('temporal_scope', '')}",
            f"- **Périmètre taxonomique :** {context.get('taxonomic_scope', '')}",
            f"- **Projets :** {projects}",
            f"- **Samples :** {samples}",
            f"- **Critères de sélection :** {context.get('selection_criteria', '')}",
        ]
    )


def _inject_study_context(content: str, manifest: dict[str, Any]) -> str:
    summary = _render_study_context(manifest)
    first_section = re.search(r"^##\s", content, flags=re.MULTILINE)
    if first_section:
        return (
            content[: first_section.start()].rstrip()
            + "\n\n"
            + summary
            + "\n\n"
            + content[first_section.start() :].lstrip()
        )
    return content.rstrip() + "\n\n" + summary


def _render_traceability_journal(manifest: dict[str, Any]) -> str:
    """Render every declared operation, including partial and failed attempts."""
    operations = manifest.get("operations", [])
    if not operations:
        return ""
    labels = (
        ("input", "Entrée"),
        ("parameters", "Paramètres"),
        ("result", "Résultat"),
        ("coverage", "Couverture"),
        ("limitations", "Limites"),
    )
    lines = ["## Journal détaillé des opérations", ""]
    for index, operation in enumerate(operations, start=1):
        if not isinstance(operation, dict):
            continue
        title = str(operation.get("title") or f"Opération {index}")
        category = str(operation.get("category") or "non classée")
        status = str(operation.get("status") or "non renseigné")
        lines.extend(
            [
                f"### {index}. {title}",
                "",
                f"- **Catégorie :** {category}",
                f"- **Statut :** {status}",
            ]
        )
        source = operation.get("source")
        if source:
            lines.append(f"- **Source :** {source}")
        for key, label in labels:
            value = operation.get(key)
            if value not in (None, "", [], {}):
                lines.append(f"- **{label} :** {value}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _append_traceability_journal(content: str, manifest: dict[str, Any]) -> str:
    journal = _render_traceability_journal(manifest)
    if not journal:
        return content
    references = re.search(
        r"^##\s+(?:\d+\.\s*)?Références\s*$",
        content,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if references:
        return (
            content[: references.start()].rstrip()
            + "\n\n"
            + journal
            + "\n\n"
            + content[references.start() :].lstrip()
        )
    return content.rstrip() + "\n\n" + journal


def _render_manifest_references(manifest: dict[str, Any]) -> str:
    entries: list[str] = []
    for source in manifest.get("sources", []):
        if not isinstance(source, dict):
            continue
        entries.append(f"- {render_sources(source)}")
    if not entries:
        return "## 6. Références\n\nAucune source externe utilisée."
    return "## 6. Références\n\n" + "\n".join(entries)


def _replace_reference_section(content: str, manifest: dict[str, Any]) -> str:
    """Build the bibliography exclusively from sources declared as used."""
    rendered = _render_manifest_references(manifest)
    match = re.search(
        r"^##\s+(?:\d+\.\s*)?Références\s*$[\s\S]*\Z",
        content,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if match:
        return content[: match.start()].rstrip() + "\n\n" + rendered
    return content.rstrip() + "\n\n" + rendered


def _markdown_to_html(md: str, title: str) -> str:
    """Convertit le markdown en HTML complet avec CSS académique."""
    try:
        import markdown as md_lib
        body = md_lib.markdown(
            md,
            extensions=["tables", "fenced_code", "attr_list"],
        )
    except ImportError:
        # Fallback minimaliste si markdown non installé
        body = f"<pre>{md}</pre>"

    def _format_figcaption(text: str) -> str:
        # Line break before section labels (Source/Méthode/Interprétation) after a sentence
        text = re.sub(r'\.\s+(\*\*)', r'.<br>\1', text)
        # Convert **text** to <strong>text</strong>
        text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
        return text

    # Remplace ![alt](url) par <figure><img><figcaption>
    body = re.sub(
        r'<p><img alt="([^"]*)" src="([^"]+)"[^>]*/></p>',
        lambda m: (
            f'<figure><img src="{m.group(2)}" alt="{m.group(1)}">'
            f'<figcaption>{_format_figcaption(m.group(1))}</figcaption></figure>'
        ),
        body,
    )

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>{_CSS}</style>
</head>
<body>
{body}
</body>
</html>"""


@tool
def export_deliverable(
    content: str,
    filename: str = "rapport",
    traceability_manifest: dict[str, Any] | None = None,
) -> str:
    """Génère un PDF scientifique à partir du contenu markdown fourni.

    Le markdown peut contenir des images via les URLs /graphs/{id}.png —
    elles seront automatiquement embarquées dans le PDF.

    Args:
        content: Contenu markdown du livrable (sections, figures, citations…).
        filename: Nom du fichier sans extension (ex: 'rapport_ecotaxa_2026').
        traceability_manifest: Sources réellement utilisées et journal structuré
            des opérations de la conversation. Le bloc ``study_context`` doit
            préciser l'objectif, la zone, la période, le périmètre taxonomique
            et les critères de sélection. Toute URL de la section Références doit
            être déclarée dans ``sources``.

    Returns:
        URL de téléchargement du PDF généré.
    """
    manifest = traceability_manifest or {"sources": [], "operations": []}
    missing_context = _missing_study_context_fields(manifest)
    if missing_context:
        return (
            "Livrable refusé — contexte d'étude incomplet : "
            + ", ".join(missing_context)
        )
    undeclared_urls = _validate_reference_sources(content, manifest)
    if undeclared_urls:
        return (
            "Livrable refusé — source(s) absente(s) du manifeste de traçabilité : "
            + ", ".join(undeclared_urls)
        )

    content = _inject_study_context(content, manifest)
    content = _append_traceability_journal(content, manifest)
    content = _replace_reference_section(content, manifest)

    downloads = _downloads_dir()
    downloads.mkdir(parents=True, exist_ok=True)

    # Sanitize filename
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", filename.strip()) or f"rapport_{uuid.uuid4().hex[:8]}"
    safe = safe.removesuffix(".pdf").removesuffix(".md")
    pdf_path = downloads / f"{safe}.pdf"

    # Remplace URLs graphiques par chemins locaux
    content_local = _replace_graph_urls(content)

    # Titre = première ligne h1 ou filename
    title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    title = title_match.group(1) if title_match else safe.replace("_", " ")

    html = _markdown_to_html(content_local, title)

    try:
        _configure_weasyprint_library_path()
        from weasyprint import HTML
        HTML(string=html, base_url=str(downloads)).write_pdf(str(pdf_path))
    except (ImportError, OSError):
        return _write_html_fallback(downloads, safe, html)

    base = os.getenv("SERVE_BASE_URL", "http://localhost:8000")
    return f"PDF généré : {base}/downloads/{safe}.pdf"
