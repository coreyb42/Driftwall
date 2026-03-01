"""Query ChromaDB for content chunks relevant to the current wallpaper image."""

from __future__ import annotations

from pathlib import Path

from .content_store import ContentChunk, get_chroma_client, get_collection
from .db import ImageRecord


def build_image_query(image: ImageRecord) -> str:
    """Build a rich query string from ImageRecord fields for semantic search."""
    parts = []
    for value in (
        image.one_paragraph,
        image.one_sentence,
        image.keywords,
        image.mood,
        image.primary_subject,
        image.setting,
        image.season,
        image.time_of_day,
        image.dominant_colors,
    ):
        if value:
            parts.append(value.replace("|", " "))
    return " ".join(parts)


def search_content(
    query_text: str,
    collection,
    embed_model: str,
    host: str,
    n_results: int = 10,
) -> list[ContentChunk]:
    """Embed query_text and return the top-n matching ContentChunks."""
    import ollama  # type: ignore[import]

    client = ollama.Client(host=host)
    resp = client.embed(model=embed_model, input=[query_text])
    query_embedding = resp.embeddings[0]

    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )
    except Exception:
        return []

    chunks: list[ContentChunk] = []
    ids = results.get("ids", [[]])[0]
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]

    for chunk_id, doc, meta in zip(ids, documents, metadatas):
        meta = meta or {}
        chunks.append(
            ContentChunk(
                id=chunk_id,
                text=doc,
                source_path=meta.get("source_path", ""),
                source_type=meta.get("source_type", "text"),
                chunk_index=int(meta.get("chunk_index", 0)),
                metadata={
                    k: v for k, v in meta.items()
                    if k not in ("source_path", "source_type", "chunk_index")
                },
            )
        )
    return chunks


def get_content_for_image(
    image: ImageRecord,
    chroma_path: Path,
    config,  # Config
    n_results: int = 10,
) -> list[ContentChunk]:
    """High-level helper: build query from image metadata and search ChromaDB."""
    query = build_image_query(image)
    if not query.strip():
        return []

    try:
        client = get_chroma_client(chroma_path)
        collection = get_collection(client)
        return search_content(
            query_text=query,
            collection=collection,
            embed_model=config.content.embed_model,
            host=config.ollama.host,
            n_results=n_results,
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Content search failed: %s", e)
        return []
