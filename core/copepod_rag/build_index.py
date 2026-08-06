"""
Load chunks.json, embed with ChromaDB's built-in ONNX embedding function
(all-MiniLM-L6-v2 via onnxruntime — no PyTorch required), persist to ChromaDB.

Run: python build_index.py
Idempotent — deletes and rebuilds the collection each time.
"""
import json
from pathlib import Path

CHUNKS_FILE = Path(__file__).parent / "chunks.json"
DOCS_DIR = Path(__file__).parent / "docs"
CHROMA_DIR = Path(__file__).parent / "chroma_db"
COLLECTION_NAME = "copepod_rag"


def _visualisation_chunks() -> list[dict]:
    """Build visualization chunks from their source Markdown at index time.

    The visualization reference is deliberately expanded as the agent gains
    scientific plotting capability.  Generating these chunks here prevents the
    hand-maintained ``chunks.json`` copy from silently lagging behind the RAG
    document that scientists actually edit.
    """
    document = (DOCS_DIR / "visualisation_graphes.md").read_text(encoding="utf-8")
    chunks: list[dict] = []
    for index, section in enumerate(document.split("\n---\n")):
        content = section.strip()
        if not content:
            continue
        title = next(
            (
                line.removeprefix("# ").strip()
                for line in content.splitlines()
                if line.startswith("# ")
            ),
            "Visualisation scientifique",
        )
        chunks.append(
            {
                "doc": "visualisation_graphes.md",
                "chunk_id": f"visualisation_graphes_{index:03d}",
                "title": title,
                "content": content,
                "char_count": len(content),
            }
        )
    return chunks


def _load_chunks() -> list[dict]:
    """Load static knowledge and freshly derive visualization guidance."""
    chunks = json.loads(CHUNKS_FILE.read_text(encoding="utf-8"))
    static_chunks = [
        chunk for chunk in chunks if chunk.get("doc") != "visualisation_graphes.md"
    ]
    return [*static_chunks, *_visualisation_chunks()]


def main():
    chunks = _load_chunks()
    print(f"Loaded {len(chunks)} chunks from knowledge documents")

    import chromadb
    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

    embed_fn = DefaultEmbeddingFunction()  # all-MiniLM-L6-v2 via ONNX, no torch

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    if COLLECTION_NAME in [c.name for c in client.list_collections()]:
        client.delete_collection(COLLECTION_NAME)

    collection = client.create_collection(
        name=COLLECTION_NAME,
        embedding_function=embed_fn,
        metadata={"hnsw:space": "cosine"},
    )

    texts = [c["content"] for c in chunks]
    print(f"Embedding {len(chunks)} chunks with all-MiniLM-L6-v2 (ONNX)...")
    collection.add(
        ids=[c["chunk_id"] for c in chunks],
        documents=texts,
        metadatas=[
            {"doc": c["doc"], "title": c["title"], "char_count": c["char_count"]}
            for c in chunks
        ],
    )

    print(f"ChromaDB collection '{COLLECTION_NAME}' built — {len(chunks)} vectors → {CHROMA_DIR}")


if __name__ == "__main__":
    main()
