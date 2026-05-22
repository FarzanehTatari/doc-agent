"""DocumentChunker tests — no chromadb required."""

from doc_agent.rag.chunker import (
    SUPPORTED_EXTENSIONS,
    Chunk,
    DocumentChunker,
)


def test_supports_known_extensions():
    assert DocumentChunker.supports("doc.pdf")
    assert DocumentChunker.supports("notes.md")
    assert DocumentChunker.supports("code.py")
    assert DocumentChunker.supports("README.txt")
    assert not DocumentChunker.supports("image.png")
    assert not DocumentChunker.supports("audio.mp3")


def test_chunk_text_basic():
    text = "First paragraph.\n\nSecond paragraph here.\n\nThird paragraph too."
    chunks = DocumentChunker.chunk_text(text, source="t.md", chunk_size=20, overlap=2)
    assert len(chunks) >= 1
    assert all(isinstance(c, Chunk) for c in chunks)
    assert all(c.source == "t.md" for c in chunks)
    assert chunks[0].chunk_index == 0
    # Should preserve content
    rejoined = " ".join(c.text for c in chunks)
    assert "First paragraph" in rejoined
    assert "Third paragraph" in rejoined


def test_empty_text_returns_no_chunks():
    chunks = DocumentChunker.chunk_text("", source="empty.md")
    assert chunks == []
    chunks = DocumentChunker.chunk_text("   \n\n   ", source="ws.md")
    assert chunks == []


def test_chunk_size_respected_roughly():
    text = ("Sentence one. " * 200).strip()
    chunks = DocumentChunker.chunk_text(text, source="big.md", chunk_size=50, overlap=5)
    # Each chunk should be smaller than ~10x the requested size in characters
    # (room for sliding-window slack)
    for c in chunks:
        assert len(c.text) <= 50 * 10  # very lenient upper bound


def test_chunk_file_md(tmp_path):
    p = tmp_path / "doc.md"
    p.write_text(
        "# Title\n\nIntro paragraph about widgets.\n\n## Section 1\n\nDetails here.\n",
        encoding="utf-8",
    )
    chunks = DocumentChunker.chunk_file(p)
    assert len(chunks) >= 1
    assert chunks[0].source == "doc.md"


def test_chunk_file_rejects_unknown(tmp_path):
    p = tmp_path / "bin.dat"
    p.write_bytes(b"\x00\x01\x02")
    try:
        DocumentChunker.chunk_file(p)
    except ValueError as e:
        assert ".dat" in str(e) or "Unsupported" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_chunk_file_missing_raises(tmp_path):
    try:
        DocumentChunker.chunk_file(tmp_path / "nope.md")
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("expected FileNotFoundError")


def test_citation_format_with_page():
    c = Chunk(text="x", source="manual.pdf", chunk_index=0, tokens=1, metadata={"page": 7})
    assert c.citation == "manual.pdf#p7"


def test_citation_format_without_page():
    c = Chunk(text="x", source="readme.md", chunk_index=3, tokens=1, metadata={})
    assert c.citation == "readme.md#chunk3"


def test_supported_extensions_includes_common_types():
    for ext in (".pdf", ".docx", ".md", ".txt", ".py", ".m", ".json", ".xml"):
        assert ext in SUPPORTED_EXTENSIONS


def test_chunk_index_is_zero_based_and_monotonic():
    text = "Para one.\n\n" + "Big para. " * 200 + "\n\nPara three."
    chunks = DocumentChunker.chunk_text(text, source="t.md", chunk_size=80, overlap=10)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
