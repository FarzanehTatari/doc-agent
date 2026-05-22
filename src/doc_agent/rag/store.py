"""ChromaDB-backed vector store.

ChromaDB ships with a built-in ONNX embedding function (`all-MiniLM-L6-v2`,
384-dim) that runs locally — no external embedding API needed. On first use it
downloads ~80 MB of ONNX weights to its cache, then runs offline forever.

Tests can inject a stub embedding function via the `embedding_function` arg to
keep them network-free.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable

from doc_agent.rag.chunker import Chunk
from doc_agent.utils.logger import get_logger

log = get_logger(__name__)


class RAGStore:
    """Wraps a chromadb PersistentClient + one collection.

    Methods:
        add_chunks(chunks)
        search(query, top_k=5, where=None) -> list[(chunk, score)]
        remove_source(source_filename)
        list_sources() -> dict[str, int]   # source -> chunk count
        stats() -> dict
        clear()
    """

    def __init__(
        self,
        path: Path,
        *,
        collection_name: str = "doc_agent_rag",
        embedding_function: Callable | None = None,
    ):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name
        self._embed_fn = embedding_function

        # Lazy chromadb import so module-level imports don't pay the price
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        self._client = chromadb.PersistentClient(
            path=str(self.path),
            settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True),
        )
        # If no embedding function is passed, chromadb uses its default
        # (ONNXMiniLM_L6_V2). Custom embedders are useful for testing.
        kwargs: dict[str, Any] = {"name": collection_name, "metadata": {"hnsw:space": "cosine"}}
        if self._embed_fn is not None:
            kwargs["embedding_function"] = self._embed_fn
        self._collection = self._client.get_or_create_collection(**kwargs)

    # ----- mutate ---------------------------------------------------------
    def add_chunks(self, chunks: list[Chunk]) -> int:
        if not chunks:
            return 0
        ids = [self._chunk_id(c) for c in chunks]
        texts = [c.text for c in chunks]
        metas = [
            {
                "source": c.source,
                "chunk_index": c.chunk_index,
                "tokens": c.tokens,
                **{k: _stringify(v) for k, v in c.metadata.items()},
            }
            for c in chunks
        ]
        # Upsert so re-adding the same file replaces (not duplicates) prior chunks
        self._collection.upsert(ids=ids, documents=texts, metadatas=metas)
        return len(chunks)

    def remove_source(self, source: str) -> int:
        """Delete every chunk whose source filename matches. Returns count removed."""
        # Need to count first because chromadb's delete returns None
        result = self._collection.get(where={"source": source}, include=[])
        ids = result.get("ids", []) or []
        if not ids:
            return 0
        self._collection.delete(ids=ids)
        return len(ids)

    def clear(self) -> None:
        """Drop every chunk in this collection."""
        self._client.delete_collection(self.collection_name)
        kwargs: dict[str, Any] = {
            "name": self.collection_name,
            "metadata": {"hnsw:space": "cosine"},
        }
        if self._embed_fn is not None:
            kwargs["embedding_function"] = self._embed_fn
        self._collection = self._client.get_or_create_collection(**kwargs)

    # ----- query ----------------------------------------------------------
    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[tuple[Chunk, float]]:
        """Return up to `top_k` (chunk, similarity_score) pairs.

        Score is 1.0 - cosine_distance, so higher = more similar; 1.0 = identical.
        """
        n_results = max(1, top_k)
        out = self._collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        docs = (out.get("documents") or [[]])[0]
        metas = (out.get("metadatas") or [[]])[0]
        dists = (out.get("distances") or [[]])[0]
        ids = (out.get("ids") or [[]])[0]

        results: list[tuple[Chunk, float]] = []
        for text, meta, dist, _id in zip(docs, metas, dists, ids, strict=False):
            meta = meta or {}
            chunk = Chunk(
                text=text,
                source=meta.get("source", "?"),
                chunk_index=int(meta.get("chunk_index", 0)),
                tokens=int(meta.get("tokens", 0)),
                metadata={
                    k: v for k, v in meta.items()
                    if k not in {"source", "chunk_index", "tokens"}
                },
            )
            # Convert cosine distance to similarity in [0, 1]
            similarity = max(0.0, 1.0 - float(dist))
            results.append((chunk, similarity))
        return results

    def list_sources(self) -> dict[str, int]:
        """Return {source_filename: chunk_count}."""
        out = self._collection.get(include=["metadatas"])
        counts: dict[str, int] = {}
        for meta in out.get("metadatas") or []:
            src = (meta or {}).get("source", "?")
            counts[src] = counts.get(src, 0) + 1
        return counts

    def stats(self) -> dict:
        sources = self.list_sources()
        return {
            "sources": len(sources),
            "chunks": sum(sources.values()),
            "collection": self.collection_name,
            "path": str(self.path),
        }

    def count(self) -> int:
        try:
            return int(self._collection.count())
        except Exception:  # noqa: BLE001
            return sum(self.list_sources().values())

    # ----- internal -------------------------------------------------------
    @staticmethod
    def _chunk_id(c: Chunk) -> str:
        """Stable id for a chunk — collisions would mean accidental dedupe."""
        page = c.metadata.get("page", "")
        h = hashlib.sha1(
            f"{c.source}::{page}::{c.chunk_index}::{c.text[:80]}".encode("utf-8")
        )
        return h.hexdigest()[:16]


def _stringify(v: Any) -> Any:
    """ChromaDB metadata values must be str | int | float | bool."""
    if isinstance(v, (str, int, float, bool)):
        return v
    return str(v)
