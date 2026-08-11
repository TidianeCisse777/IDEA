"""Build bounded, autonomous chunks from every copepod RAG document."""

import json
import re
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter

DOCS_DIR = Path(__file__).parent / "docs"
OUT_FILE = Path(__file__).parent / "chunks.json"

_SEPARATOR = re.compile(r"^\s*---\s*$", re.MULTILINE)
MAX_CHUNK_CHARS = 2_800
CHUNK_OVERLAP_CHARS = 250


def _extract_title(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    first = text.strip().splitlines()[0] if text.strip() else ""
    return first[:80] or "untitled"


def _is_document_preamble(content: str) -> bool:
    """Skip filename/format-only headers that add no retrievable knowledge."""
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    return bool(lines) and all(
        line.startswith("#") or line.lower().startswith("format rag") for line in lines
    )


def _split_oversized_section(content: str) -> list[str]:
    """Split long sections while repeating their semantic section title.

    Bare ``---`` delimiters remain the primary author-controlled boundaries.
    This second pass only protects retrieval from very large tables or sections
    that would otherwise dominate an embedding and flood the model context.
    """
    if len(content) <= MAX_CHUNK_CHARS:
        return [content]

    title = _extract_title(content)
    prefix = f"# Section source : {title}\n\n"
    available = MAX_CHUNK_CHARS - len(prefix)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=available,
        chunk_overlap=min(CHUNK_OVERLAP_CHARS, available // 5),
        separators=["\n## ", "\n### ", "\n\n", "\n", " ", ""],
        length_function=len,
    )
    parts = splitter.split_text(content)
    bounded: list[str] = []
    for index, part in enumerate(parts):
        candidate = part if index == 0 else prefix + part
        bounded.append(candidate[:MAX_CHUNK_CHARS])
    return bounded


def chunk_doc(path: Path) -> list[dict]:
    raw = path.read_text(encoding="utf-8")
    segments = _SEPARATOR.split(raw)

    chunks = []
    chunk_idx = 0
    for seg in segments:
        content = seg.strip()
        if not content:
            continue
        if _is_document_preamble(content):
            continue
        title = _extract_title(content)
        for bounded_content in _split_oversized_section(content):
            chunks.append(
                {
                    "doc": path.name,
                    "chunk_id": f"{path.stem}_{chunk_idx:03d}",
                    "title": title,
                    "content": bounded_content,
                    "char_count": len(bounded_content),
                }
            )
            chunk_idx += 1
    return chunks


def build_chunks() -> list[dict]:
    """Return chunks generated from the current Markdown sources."""
    all_chunks: list[dict] = []
    for doc in sorted(DOCS_DIR.glob("*.md")):
        all_chunks.extend(chunk_doc(doc))
    return all_chunks


def write_chunks(chunks: list[dict]) -> None:
    """Persist the reproducible JSON representation consumed by tooling."""
    OUT_FILE.write_text(
        json.dumps(chunks, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main():
    all_chunks = build_chunks()
    for doc in sorted(DOCS_DIR.glob("*.md")):
        count = sum(chunk["doc"] == doc.name for chunk in all_chunks)
        print(f"  {doc.name}: {count} chunks")

    write_chunks(all_chunks)
    print(f"\n{len(all_chunks)} chunks total → {OUT_FILE}")


if __name__ == "__main__":
    main()
