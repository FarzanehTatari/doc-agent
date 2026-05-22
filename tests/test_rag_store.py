"""RAGStore tests using a deterministic stub embedding function.

These tests exercise add/search/remove against a real chromadb PersistentClient
but with embeddings derived from a hash of the text — no model download, no
network, fully reproducible.
"""

from __future__ import annotations

import hashlib

import pytest

# chromadb is heavy and not strictly required to run other tests; skip cleanly if missing
chromadb = pytest.importorskip("chromadb")

from doc_agent.rag.chunker import Chunk  # noqa: E402
from doc_agent.rag.store import RAGStore  # noqa: E402


def _hash_embedding(text: str, dim: int = 32) -> list[float]:
    """Deterministic byte-derived embedding — purely for testing."""
    h = hashlib.sha256(text.encode("utf-8")).digest()
    # Tile to length 4*dim and slice
    raw = (h * ((4 * dim) // len(h) + 1))[: 4 * dim]
    floats = [b / 255.0 for b in raw]
    return floats[:dim]


class StubEmbeddingFunction:
    """ChromaDB-style embedding function with both legacy and new API surface.

    chromadb 0.5+ calls `embed_documents()` when adding and `embed_query()`
    when searching. Older versions just used `__call__`. We implement all three
    so the same stub works across versions.
    """

    def __call__(self, input):  # legacy callable API
        return [_hash_embedding(t) for t in input]

    def embed_documents(self, input):  # chromadb >= 0.5 (add path)
        return [_hash_embedding(t) for t in input]

    def embed_query(self, input):  # chromadb >= 0.5 (query path)
        # `input` may be a single string or a list of strings depending on the
        # chromadb release. Normalize to list-in, list-out.
        if isinstance(input, str):
            return [_hash_embedding(input)]
        return [_hash_embedding(t) for t in input]

    def name(self):
        return "stub_hash_embedder"

    # chromadb's deprecation check looks for an `is_legacy` attribute on the
    # embedding function to silence its warning. Declare it explicitly.
    is_legacy = False


@pytest.fixture()
def store(tmp_path):
    return RAGStore(
        tmp_path / "rag",
        collection_name="test_collection",
        embedding_function=StubEmbeddingFunction(),
    )


def _mk_chunk(text, source="doc.md", idx=0, page=None) -> Chunk:
    meta = {"page": page} if page is not None else {}
    return Chunk(text=text, source=source, chunk_index=idx, tokens=len(text) // 4, metadata=meta)


def test_add_then_count(store):
    n = store.add_chunks([_mk_chunk("hello world", idx=0), _mk_chunk("another chunk", idx=1)])
    assert n == 2
    assert store.count() == 2


def test_list_sources_groups_by_filename(store):
    store.add_chunks(
        [
            _mk_chunk("a", source="alpha.md", idx=0),
            _mk_chunk("b", source="alpha.md", idx=1),
            _mk_chunk("c", source="beta.md", idx=0),
        ]
    )
    sources = store.list_sources()
    assert sources["alpha.md"] == 2
    assert sources["beta.md"] == 1


def test_remove_source(store):
    store.add_chunks(
        [
            _mk_chunk("x", source="a.md", idx=0),
            _mk_chunk("y", source="b.md", idx=0),
        ]
    )
    removed = store.remove_source("a.md")
    assert removed == 1
    assert "a.md" not in store.list_sources()
    assert store.list_sources()["b.md"] == 1


def test_search_returns_results(store):
    store.add_chunks(
        [
            _mk_chunk("vehicle speed estimator subsystem", idx=0),
            _mk_chunk("brake calibration parameters", idx=1),
            _mk_chunk("audio infotainment volume settings", idx=2),
        ]
    )
    results = store.search("vehicle speed estimator subsystem", top_k=2)
    assert len(results) <= 2
    # The exact-match chunk should be the top result
    assert results[0][0].text == "vehicle speed estimator subsystem"
    # Score for an exact match should be high (cosine ~ 1.0)
    assert results[0][1] > 0.9


def test_upsert_replaces_same_chunk(store):
    c = _mk_chunk("identical content", idx=0)
    store.add_chunks([c])
    store.add_chunks([c])  # upsert, not duplicate
    assert store.count() == 1


def test_clear_drops_everything(store):
    store.add_chunks([_mk_chunk("one"), _mk_chunk("two")])
    assert store.count() == 2
    store.clear()
    assert store.count() == 0
