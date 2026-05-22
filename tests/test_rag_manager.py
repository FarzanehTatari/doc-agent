"""RAGManager tests — uses the stub embedder from test_rag_store."""

from __future__ import annotations

import pytest

chromadb = pytest.importorskip("chromadb")

from doc_agent.rag.manager import RAGManager  # noqa: E402
from tests.test_rag_store import StubEmbeddingFunction  # noqa: E402


def _seed_md(tmp_path, name: str, content: str):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


@pytest.fixture()
def rag(tmp_path):
    return RAGManager(
        store_path=tmp_path / "rag",
        collection_name="test_collection",
        chunk_size=80,
        chunk_overlap=10,
        embedding_function=StubEmbeddingFunction(),
    )


def test_add_then_list(tmp_path, rag):
    p = _seed_md(tmp_path, "alpha.md", "Some content about vehicle speed estimation. " * 5)
    out = rag.add_document(p)
    assert out["chunks"] >= 1
    assert out["replaced"] is False
    docs = rag.list_documents()
    assert "alpha.md" in docs


def test_re_add_same_file_replaces(tmp_path, rag):
    p = _seed_md(tmp_path, "alpha.md", "Original content " * 30)
    rag.add_document(p)
    first_count = rag.list_documents()["alpha.md"]
    # Rewrite the file with different content
    p.write_text("Brand new content " * 30, encoding="utf-8")
    out = rag.add_document(p)
    assert out["replaced"] is True
    # No duplication
    sources = rag.list_documents()
    assert list(sources.keys()) == ["alpha.md"]
    assert sources["alpha.md"] >= 1


def test_search_and_format(tmp_path, rag):
    p = _seed_md(
        tmp_path,
        "topic.md",
        "Vehicle speed estimator uses wheel speed sensors and a first-order low-pass filter.",
    )
    rag.add_document(p)
    results = rag.search("Vehicle speed estimator uses wheel speed sensors and a first-order low-pass filter.", top_k=3)
    assert len(results) >= 1
    block = rag.format_for_prompt(
        "Vehicle speed estimator uses wheel speed sensors and a first-order low-pass filter.",
        top_k=3,
        max_tokens=500,
    )
    assert block is not None
    assert "Reference documents" in block
    assert "topic.md" in block


def test_remove_document(tmp_path, rag):
    p = _seed_md(tmp_path, "kill.md", "Content " * 30)
    rag.add_document(p)
    n = rag.remove_document("kill.md")
    assert n >= 1
    assert "kill.md" not in rag.list_documents()


def test_unsupported_file_raises(tmp_path, rag):
    p = tmp_path / "img.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n")
    with pytest.raises(ValueError):
        rag.add_document(p)


def test_search_below_threshold_returns_empty(tmp_path, rag):
    p = _seed_md(tmp_path, "unrelated.md", "Cooking pasta with butter and parsley.")
    rag.add_document(p)
    # Score gate of 0.99 with our stub embedder will reject almost everything
    results = rag.search("totally different topic about quantum mechanics", top_k=5, min_score=0.99)
    assert results == []
