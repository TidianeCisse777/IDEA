"""
Load chunks.json, embed with ChromaDB's built-in ONNX embedding function
(all-MiniLM-L6-v2 via onnxruntime — no PyTorch required), persist to ChromaDB.

Run: python build_index.py
Idempotent — deletes and rebuilds the collection each time.
"""
import json
from pathlib import Path

CHUNKS_FILE = Path(__file__).parent / "chunks.json"
CHROMA_DIR = Path(__file__).parent / "chroma_db"
COLLECTION_NAME = "copepod_rag"


def main():
    chunks = json.loads(CHUNKS_FILE.read_text(encoding="utf-8"))
    print(f"Loaded {len(chunks)} chunks from {CHUNKS_FILE.name}")

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
