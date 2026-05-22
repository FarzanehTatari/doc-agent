"""Retrieval-Augmented Generation: chunking, embedding, search, citations."""

from doc_agent.rag.chunker import Chunk, DocumentChunker, Section
from doc_agent.rag.manager import RAGManager, RetrievalResult
from doc_agent.rag.store import RAGStore

__all__ = [
    "Chunk",
    "DocumentChunker",
    "Section",
    "RAGManager",
    "RAGStore",
    "RetrievalResult",
]
