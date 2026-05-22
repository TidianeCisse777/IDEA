"""
Load chunks.json, embed with sentence-transformers, persist to ChromaDB.

Run: python build_index.py
Idempotent — deletes and rebuilds the collection each time.
"""
import json
from pathlib import Path

CHUNKS_FILE = Path(__file__).parent / "chunks.json"
CHROMA_DIR = Path(__file__).parent / "chroma_db"
COLLECTION_NAME = "copepod_rag"
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def main():
    chunks = json.loads(CHUNKS_FILE.read_text(encoding="utf-8"))
    print(f"Loaded {len(chunks)} chunks from {CHUNKS_FILE.name}")

    from sentence_transformers import SentenceTransformer
    import chromadb

    print(f"Embedding with {EMBED_MODEL}...")
    model = SentenceTransformer(EMBED_MODEL)
    texts = [c["content"] for c in chunks]
    embeddings = model.encode(texts, show_progress_bar=True, convert_to_list=True)

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    if COLLECTION_NAME in [c.name for c in client.list_collections()]:
        client.delete_collection(COLLECTION_NAME)

    collection = client.create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    collection.add(
        ids=[c["chunk_id"] for c in chunks],
        embeddings=embeddings,
        documents=texts,
        metadatas=[
            {"doc": c["doc"], "title": c["title"], "char_count": c["char_count"]}
            for c in chunks
        ],
    )

    print(f"ChromaDB collection '{COLLECTION_NAME}' built — {len(chunks)} vectors → {CHROMA_DIR}")


if __name__ == "__main__":
    main()
