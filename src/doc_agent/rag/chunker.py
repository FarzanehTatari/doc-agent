"""Document text extraction and chunking.

Supported file types:
    .pdf, .docx, .md, .markdown, .txt, .rst, .py, .m, .c, .cpp, .h, .json, .xml, .yml, .yaml

Each file is parsed into one or more `Section`s (e.g. one Section per PDF page),
and each section is split into overlapping `Chunk`s using a sliding window with
smart break points (paragraph > sentence > word boundary).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from doc_agent.ai.tokens import estimate_tokens
from doc_agent.utils.logger import get_logger

log = get_logger(__name__)

SUPPORTED_EXTENSIONS = {
    ".pdf", ".docx",
    ".md", ".markdown", ".txt", ".rst",
    ".py", ".m", ".c", ".cpp", ".cc", ".h", ".hpp",
    ".json", ".xml", ".yml", ".yaml", ".toml",
    ".html", ".htm",
}
# Files we recognize as "code" — used to prefer slightly tighter token estimates
CODE_EXTENSIONS = {".py", ".m", ".c", ".cpp", ".cc", ".h", ".hpp", ".json", ".xml"}

CHARS_PER_TOKEN = 4  # rough conversion for the sliding-window step
DEFAULT_CHUNK_SIZE = 800     # tokens
DEFAULT_OVERLAP = 100        # tokens


@dataclass
class Section:
    """One semantic unit before chunking (a PDF page, a whole DOCX, etc.)."""

    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Chunk:
    """One indexable text fragment with provenance."""

    text: str
    source: str            # basename of the source file
    chunk_index: int       # 0-based, per source
    tokens: int            # estimated
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def citation(self) -> str:
        page = self.metadata.get("page")
        if page is not None:
            return f"{self.source}#p{page}"
        section = self.metadata.get("section")
        if section:
            return f"{self.source}#{section}"
        return f"{self.source}#chunk{self.chunk_index}"

    def to_dict(self) -> dict:
        return asdict(self)


# --- public API ---------------------------------------------------------------
class DocumentChunker:
    """Static class — extract text from a file and split it into chunks."""

    @classmethod
    def supports(cls, path: Path | str) -> bool:
        return Path(path).suffix.lower() in SUPPORTED_EXTENSIONS

    @classmethod
    def chunk_file(
        cls,
        path: Path | str,
        *,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        overlap: int = DEFAULT_OVERLAP,
    ) -> list[Chunk]:
        """Read the file, split into chunks."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(path)
        ext = path.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file type: {ext}. "
                f"Supported: {sorted(SUPPORTED_EXTENSIONS)}"
            )

        sections = cls._extract_sections(path, ext)
        chunks: list[Chunk] = []
        for sec in sections:
            chunks.extend(cls._split_section(sec, source=path.name,
                                             chunk_size=chunk_size, overlap=overlap,
                                             start_index=len(chunks)))
        return chunks

    @classmethod
    def chunk_text(
        cls,
        text: str,
        *,
        source: str = "inline",
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        overlap: int = DEFAULT_OVERLAP,
    ) -> list[Chunk]:
        """Chunk a raw text string — useful for tests and ad-hoc inputs."""
        sec = Section(text=text, metadata={})
        return cls._split_section(sec, source=source, chunk_size=chunk_size, overlap=overlap)

    # --- text extraction --------------------------------------------------
    @classmethod
    def _extract_sections(cls, path: Path, ext: str) -> list[Section]:
        if ext == ".pdf":
            return cls._extract_pdf(path)
        if ext == ".docx":
            return [Section(text=cls._extract_docx(path), metadata={})]
        # text-ish files
        return [Section(text=cls._read_text(path), metadata={})]

    @classmethod
    def _read_text(cls, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return path.read_text(encoding="latin-1", errors="replace")

    @classmethod
    def _extract_pdf(cls, path: Path) -> list[Section]:
        try:
            from pypdf import PdfReader
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "pypdf is required for PDF support. `pip install pypdf`."
            ) from e
        reader = PdfReader(str(path))
        sections: list[Section] = []
        for i, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception as e:  # noqa: BLE001
                log.warning("pypdf failed to extract page %d of %s: %s", i, path.name, e)
                text = ""
            text = _normalize_whitespace(text)
            if not text.strip():
                continue
            sections.append(Section(text=text, metadata={"page": i}))
        return sections

    @classmethod
    def _extract_docx(cls, path: Path) -> str:
        try:
            from docx import Document
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "python-docx is required for DOCX support. `pip install python-docx`."
            ) from e
        doc = Document(str(path))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        # Tables — flatten to plain text rows
        for table in doc.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    paragraphs.append(" | ".join(cells))
        return "\n\n".join(paragraphs)

    # --- chunking ---------------------------------------------------------
    @classmethod
    def _split_section(
        cls,
        section: Section,
        *,
        source: str,
        chunk_size: int,
        overlap: int,
        start_index: int = 0,
    ) -> list[Chunk]:
        text = section.text.strip()
        if not text:
            return []

        target_chars = max(200, chunk_size * CHARS_PER_TOKEN)
        overlap_chars = max(0, overlap * CHARS_PER_TOKEN)

        chunks: list[Chunk] = []
        pos = 0
        idx = start_index
        text_len = len(text)
        while pos < text_len:
            end_target = min(pos + target_chars, text_len)
            if end_target >= text_len:
                # Last chunk — take everything that's left
                chunk_text = text[pos:].strip()
            else:
                # Try to break at a friendly boundary near end_target
                cut = _find_break_point(text, pos, end_target)
                chunk_text = text[pos:cut].strip()
                end_target = cut

            if chunk_text:
                chunks.append(
                    Chunk(
                        text=chunk_text,
                        source=source,
                        chunk_index=idx,
                        tokens=estimate_tokens(chunk_text),
                        metadata=dict(section.metadata),
                    )
                )
                idx += 1

            if end_target >= text_len:
                break
            # Advance with overlap, but always make forward progress
            pos = max(end_target - overlap_chars, pos + 1)

        return chunks


# --- helpers -----------------------------------------------------------------
def _normalize_whitespace(text: str) -> str:
    """Collapse runs of whitespace, normalize newlines, strip control chars."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(c for c in text if c == "\n" or c == "\t" or c >= " ")
    # Collapse 3+ blank lines into 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# Sentence boundary heuristic — periods, question marks, exclamations followed by space or eol
_SENTENCE_END_RE = re.compile(r"[.!?][\)\]\"']?\s")


def _find_break_point(text: str, start: int, target: int) -> int:
    """Find the best cut point at or before `target` for chunk start `start`.

    Tries in order: double-newline (paragraph), sentence end, single newline,
    space (word boundary). Falls back to the hard target.
    """
    search_window = max(start, target - 400)  # look back up to ~100 tokens
    segment = text[search_window:target]

    # Paragraph
    last_para = segment.rfind("\n\n")
    if last_para != -1:
        return search_window + last_para + 2

    # Sentence end
    sentence_matches = list(_SENTENCE_END_RE.finditer(segment))
    if sentence_matches:
        return search_window + sentence_matches[-1].end()

    # Single newline
    last_newline = segment.rfind("\n")
    if last_newline != -1:
        return search_window + last_newline + 1

    # Word boundary
    last_space = segment.rfind(" ")
    if last_space != -1:
        return search_window + last_space + 1

    return target
