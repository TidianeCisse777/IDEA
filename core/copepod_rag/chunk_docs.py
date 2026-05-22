"""
Parse the 5 RAG docs, split on bare '---' lines, produce chunks.json.

Each chunk is autonomous and maps to one thematic section.
Run: python chunk_docs.py  (from anywhere — uses absolute path relative to this file)
"""
import json
import re
from pathlib import Path

DOCS_DIR = Path(__file__).parent / "docs"
OUT_FILE = Path(__file__).parent / "chunks.json"

_SEPARATOR = re.compile(r"^\s*---\s*$", re.MULTILINE)


def _extract_title(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    first = text.strip().splitlines()[0] if text.strip() else ""
    return first[:80] or "untitled"


def chunk_doc(path: Path) -> list[dict]:
    raw = path.read_text(encoding="utf-8")
    segments = _SEPARATOR.split(raw)

    chunks = []
    chunk_idx = 0
    for seg in segments:
        content = seg.strip()
        if not content:
            continue
        chunks.append({
            "doc": path.name,
            "chunk_id": f"{path.stem}_{chunk_idx:03d}",
            "title": _extract_title(content),
            "content": content,
            "char_count": len(content),
        })
        chunk_idx += 1
    return chunks


def main():
    all_chunks = []
    for doc in sorted(DOCS_DIR.glob("*.md")):
        doc_chunks = chunk_doc(doc)
        all_chunks.extend(doc_chunks)
        print(f"  {doc.name}: {len(doc_chunks)} chunks")

    OUT_FILE.write_text(json.dumps(all_chunks, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{len(all_chunks)} chunks total → {OUT_FILE}")


if __name__ == "__main__":
    main()
