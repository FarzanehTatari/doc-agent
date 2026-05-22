"""High-level RAG orchestration.

Built on top of `DocumentChunker` + `RAGStore`. Surfaces a small API the CLI
and the chat loop both call:

    rag.add_document(path)
    rag.search(query, top_k=5) -> list[RetrievalResult]
    rag.format_for_prompt(query, max_tokens) -> str | None
    rag.list_documents() -> dict[name, chunk_count]
    rag.remove_document(name)
    rag.stats()
    rag.clear()
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from doc_agent.ai.tokens import estimate_tokens
from doc_agent.rag.chunker import SUPPORTED_EXTENSIONS, DocumentChunker
from doc_agent.rag.store import RAGStore
from doc_agent.utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class RetrievalResult:
    """One retrieved chunk packaged for display + prompt assembly."""

    text: str
    citation: str   # e.g. "manual.pdf#p7"
    source: str
    score: float

    def as_prompt_block(self) -> str:
        return f"[{self.citation}] (score {self.score:.2f})\n{self.text}"


class RAGManager:
    """Coordinates chunking + storage + retrieval."""

    def __init__(
        self,
        store_path: Path,
        *,
        collection_name: str = "doc_agent_rag",
        chunk_size: int = 800,
        chunk_overlap: int = 100,
        embedding_function=None,  # tests inject a stub
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._store = RAGStore(
            store_path,
            collection_name=collection_name,
            embedding_function=embedding_function,
        )

    # ----- ingest --------------------------------------------------------
    def add_document(
        self,
        path: Path | str,
        *,
        progress: Callable[[str], None] | None = None,
    ) -> dict:
        """Chunk and index one file. Returns {chunks, source, replaced}."""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(p)
        if not DocumentChunker.supports(p):
            raise ValueError(
                f"Unsupported file type: {p.suffix}. "
                f"Supported: {sorted(SUPPORTED_EXTENSIONS)}"
            )

        if progress:
            progress(f"Reading {p.name}...")
        existing = self._store.list_sources().get(p.name, 0)
        if existing:
            if progress:
                progress(f"Replacing {existing} existing chunks for {p.name}")
            self._store.remove_source(p.name)

        if progress:
            progress(f"Chunking {p.name}...")
        chunks = DocumentChunker.chunk_file(
            p, chunk_size=self.chunk_size, overlap=self.chunk_overlap
        )

        if progress:
            progress(f"Indexing {len(chunks)} chunks...")
        n = self._store.add_chunks(chunks)
        if progress:
            progress(f"✓ {p.name}: {n} chunks indexed")
        return {"chunks": n, "source": p.name, "replaced": bool(existing)}

    def remove_document(self, source: str) -> int:
        return self._store.remove_source(source)

    def clear(self) -> None:
        self._store.clear()

    # ----- retrieve ------------------------------------------------------
    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> list[RetrievalResult]:
        """Return ranked RetrievalResults for the query."""
        raw = self._store.search(query, top_k=top_k)
        results: list[RetrievalResult] = []
        for chunk, score in raw:
            if score < min_score:
                continue
            results.append(
                RetrievalResult(
                    text=chunk.text,
                    citation=chunk.citation,
                    source=chunk.source,
                    score=score,
                )
            )
        return results

    def format_for_prompt(
        self,
        query: str,
        *,
        top_k: int = 5,
        min_score: float = 0.0,
        max_tokens: int = 4000,
    ) -> str | None:
        """Build a system-prompt block from top retrievals, token-budgeted.

        Returns None if no chunks pass the score gate.
        """
        results = self.search(query, top_k=top_k, min_score=min_score)
        if not results:
            return None

        lines: list[str] = []
        used = 0
        kept = 0
        for r in results:
            block = r.as_prompt_block()
            est = estimate_tokens(block) + 4
            if used + est > max_tokens:
                break
            lines.append(block)
            used += est
            kept += 1

        if not lines:
            return None

        header = (
            "## Reference documents (retrieved from your RAG library)\n"
            "Cite using the bracketed identifier when you draw on them. "
            "If the documents don't contain what's needed, say so.\n"
        )
        return header + "\n\n".join(lines)

    # ----- inspect -------------------------------------------------------
    def list_documents(self) -> dict[str, int]:
        return self._store.list_sources()

    def stats(self) -> dict:
        return self._store.stats()
