"""Tool export_deliverable — compile un livrable scientifique en PDF."""
from __future__ import annotations

import os
import re
import sys
import uuid
from pathlib import Path

from langchain_core.tools import tool

def _downloads_dir() -> Path:
    return Path(os.getenv("DOWNLOADS_DIR", "/tmp/copepod_downloads"))

_GRAPHS_DIR = Path("/tmp/copepod_graphs")

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
def export_deliverable(content: str, filename: str = "rapport") -> str:
    """Génère un PDF scientifique à partir du contenu markdown fourni.

    Le markdown peut contenir des images via les URLs /graphs/{id}.png —
    elles seront automatiquement embarquées dans le PDF.

    Args:
        content: Contenu markdown du livrable (sections, figures, citations…).
        filename: Nom du fichier sans extension (ex: 'rapport_ecotaxa_2026').

    Returns:
        URL de téléchargement du PDF généré.
    """
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
