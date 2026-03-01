"""ChromaDB-backed vector store for content chunks (quotes, book excerpts)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ContentChunk:
    id: str              # "{source_path}::{chunk_index}"
    text: str
    source_path: str
    source_type: str     # "quote" | "text"
    chunk_index: int
    metadata: dict = field(default_factory=dict)  # author, date, source_title, etc.


def get_chroma_client(chroma_path: Path):  # type: ignore[return]
    """Return a persistent ChromaDB client at chroma_path."""
    import chromadb  # type: ignore[import]
    chroma_path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(chroma_path))


def get_collection(client):  # type: ignore[return]
    """Return (or create) the driftwall_content collection."""
    return client.get_or_create_collection(
        name="driftwall_content",
        metadata={"hnsw:space": "cosine"},
    )


def add_chunks(collection, chunks: list[ContentChunk], embeddings: list[list[float]]) -> None:
    """Upsert chunks with pre-computed embeddings into the collection."""
    if not chunks:
        return
    collection.upsert(
        ids=[c.id for c in chunks],
        documents=[c.text for c in chunks],
        embeddings=embeddings,
        metadatas=[
            {
                "source_path": c.source_path,
                "source_type": c.source_type,
                "chunk_index": c.chunk_index,
                **{k: str(v) for k, v in c.metadata.items() if v is not None},
            }
            for c in chunks
        ],
    )


def delete_by_source(collection, source_path: str) -> None:
    """Delete all chunks from a given source file."""
    collection.delete(where={"source_path": source_path})


def get_sources_in_collection(collection) -> set[str]:
    """Return the set of source_path values currently in the collection."""
    try:
        result = collection.get(include=["metadatas"])
        paths: set[str] = set()
        for meta in result.get("metadatas") or []:
            if meta and "source_path" in meta:
                paths.add(meta["source_path"])
        return paths
    except Exception:
        return set()
