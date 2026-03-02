"""Query ChromaDB for content chunks relevant to the current wallpaper image."""

from __future__ import annotations

import random
from pathlib import Path

from .content_store import ContentChunk, get_chroma_client, get_collection
from .db import ImageRecord, list_content_source_paths


def build_image_query(image: ImageRecord) -> str:
    """Build a query string from ImageRecord fields for semantic search."""
    if image.one_paragraph:
        return image.one_paragraph
    parts = []
    for value in (
        image.one_sentence,
        image.keywords,
        image.mood,
        image.primary_subject,
        image.setting,
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
    source_paths: list[str] | None = None,
) -> list[ContentChunk]:
    """Embed query_text and return the top-n matching ContentChunks."""
    import ollama  # type: ignore[import]

    client = ollama.Client(host=host)
    resp = client.embed(model=embed_model, input=[query_text])
    query_embedding = resp.embeddings[0]

    where_filter = None
    if source_paths:
        unique_paths = [p for p in dict.fromkeys(source_paths) if p]
        if len(unique_paths) == 1:
            where_filter = {"source_path": unique_paths[0]}
        elif unique_paths:
            where_filter = {"source_path": {"$in": unique_paths}}

    query_kwargs = {
        "query_embeddings": [query_embedding],
        "n_results": n_results,
        "include": ["documents", "metadatas", "distances"],
    }
    if where_filter is not None:
        query_kwargs["where"] = where_filter

    try:
        results = collection.query(**query_kwargs)
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
        subset_size = max(0, int(getattr(config.dynamic_overlay, "random_source_subset_size", 0)))
        source_subset: list[str] | None = None
        if subset_size > 0:
            source_paths = list_content_source_paths(config.resolved_db_path)
            if source_paths:
                source_subset = (
                    random.sample(source_paths, subset_size)
                    if len(source_paths) > subset_size
                    else source_paths
                )
        return search_content(
            query_text=query,
            collection=collection,
            embed_model=config.content.embed_model,
            host=config.ollama.host,
            n_results=n_results,
            source_paths=source_subset,
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Content search failed: %s", e)
        return []
