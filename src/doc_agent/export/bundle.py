"""Bundle — an ordered collection of Markdown documents to consolidate.

A bundle is the input to every export writer. It's built either from a
directory (typically `project_lib/generated/<ModelName>/`) or from a single
.md file. When built from a directory:

  - `_INDEX.md` (if present) is excluded from the body but its order is honored
    for the rest of the files. Files referenced in the index appear in the
    order they appear; files not in the index are appended alphabetically.
  - The directory's name becomes the bundle's `model_name`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Kind suffixes used by the generator (`_autodoc.md`, `_sysreq.md`, `_unitreq.md`).
_KIND_RE = re.compile(r"_(autodoc|sysreq|unitreq)\.md$", re.IGNORECASE)


@dataclass
class BundleEntry:
    """One Markdown file inside a bundle."""

    source_path: Path
    content: str
    title: str = ""
    kind: str = "doc"  # autodoc | sysreq | unitreq | doc

    @classmethod
    def from_path(cls, path: Path) -> BundleEntry:
        path = Path(path)
        text = path.read_text(encoding="utf-8")
        title = _extract_title(text) or path.stem
        kind = _infer_kind(path.name)
        return cls(source_path=path, content=text, title=title, kind=kind)


@dataclass
class Bundle:
    """Ordered list of `BundleEntry` plus model-level metadata."""

    model_name: str = "model"
    entries: list[BundleEntry] = field(default_factory=list)
    source_dir: Path | None = None

    # ----- constructors -----
    @classmethod
    def from_directory(cls, dir_path: Path | str) -> Bundle:
        dir_path = Path(dir_path)
        if not dir_path.is_dir():
            raise NotADirectoryError(dir_path)

        all_md = sorted(p for p in dir_path.glob("*.md") if p.name != "_INDEX.md")
        order = _order_from_index(dir_path / "_INDEX.md", all_md)

        return cls(
            model_name=dir_path.name,
            entries=[BundleEntry.from_path(p) for p in order],
            source_dir=dir_path,
        )

    @classmethod
    def from_single_file(cls, path: Path | str) -> Bundle:
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(path)
        entry = BundleEntry.from_path(path)
        return cls(
            model_name=path.parent.name or path.stem,
            entries=[entry],
            source_dir=path.parent,
        )

    # ----- helpers --------
    def __len__(self) -> int:
        return len(self.entries)

    def is_empty(self) -> bool:
        return not self.entries


# ----- internals ---------------------------------------------------------
def _extract_title(md: str) -> str:
    """Return the first H1 heading text; empty if none."""
    for line in md.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    return ""


def _infer_kind(name: str) -> str:
    m = _KIND_RE.search(name)
    return m.group(1).lower() if m else "doc"


def _order_from_index(index_path: Path, all_files: list[Path]) -> list[Path]:
    """If `_INDEX.md` exists, return files in the order they appear there.
    Files not referenced in the index are appended in alphabetical order."""
    if not index_path.exists():
        return all_files

    text = index_path.read_text(encoding="utf-8")
    # Extract every markdown link target ending in .md
    linked = [m.group(1) for m in re.finditer(r"\(([^)\s]+?\.md)\)", text)]

    by_name = {p.name: p for p in all_files}
    ordered: list[Path] = []
    seen: set[Path] = set()
    for name in linked:
        # Strip any directory prefix the link might carry
        basename = Path(name).name
        if basename in by_name and by_name[basename] not in seen:
            ordered.append(by_name[basename])
            seen.add(by_name[basename])
    # Append any unreferenced files alphabetically
    for p in all_files:
        if p not in seen:
            ordered.append(p)
            seen.add(p)
    return ordered
