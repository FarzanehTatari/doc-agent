"""Authoritative facts memory backed by a human-editable markdown file.

File format (`facts.md`):

    # Project Facts

    ## Naming Conventions
    - [critical] Signal names use camelCase with unit suffix. #naming #signals
    - [normal] Subsystem names use PascalCase.

    ## Domain
    - [high] Vehicle speed is always reported in km/h, never mph.

    ## Policy
    - [critical] Never reference internal Bosch part numbers in generated docs.

    ## Other
    - [normal] Stateflow charts get state diagrams as Mermaid blocks.

Each fact line: `- [priority] text  #keyword1 #keyword2`

Priority is one of `critical`, `high`, `normal`, `low`. Categories are derived
from the `## Heading` above each block. Lines that don't match the fact pattern
(comments, blank lines, sub-headers) are preserved on save so the file stays
human-friendly.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from doc_agent.ai.tokens import estimate_tokens

Priority = Literal["critical", "high", "normal", "low"]
Category = Literal["naming", "domain", "policy", "other"]

PRIORITY_RANK: dict[str, int] = {"critical": 0, "high": 1, "normal": 2, "low": 3}

_CATEGORY_HEADINGS: dict[str, Category] = {
    "naming conventions": "naming",
    "naming": "naming",
    "domain": "domain",
    "policy": "policy",
    "policies": "policy",
    "other": "other",
}

# Match:  - [priority] text  with trailing #tags
_FACT_RE = re.compile(
    r"^\s*[-*]\s*"
    r"\[(?P<priority>critical|high|normal|low)\]\s*"
    r"(?P<body>.+?)\s*$",
    re.IGNORECASE,
)
_TAG_RE = re.compile(r"#([A-Za-z0-9_-]+)")
# Strip a contiguous trailing run of `  #tag #tag` from the end of the line,
# but leave inline #mentions and sentence punctuation untouched.
_TRAILING_TAGS_RE = re.compile(r"(?:\s+#[A-Za-z0-9_-]+)+\s*$")


@dataclass
class Fact:
    id: str
    text: str
    category: Category = "other"
    priority: Priority = "normal"
    keywords: list[str] = field(default_factory=list)
    enabled: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    def to_markdown(self) -> str:
        kw = " " + " ".join(f"#{k}" for k in self.keywords) if self.keywords else ""
        prefix = "" if self.enabled else "~~"
        suffix = "~~" if self.enabled is False else ""
        return f"- [{self.priority}] {prefix}{self.text}{suffix}{kw}"


class FactsMemory:
    """Markdown-backed facts store.

    Construct with a path; load is automatic if the file exists. Edits via
    `add/update/remove` mutate the in-memory list; call `save()` to write.
    """

    DEFAULT_CATEGORIES: tuple[Category, ...] = ("naming", "domain", "policy", "other")

    def __init__(self, path: Path):
        self.path = Path(path)
        self._facts: list[Fact] = []
        if self.path.exists():
            self.load()

    # ----- mutate ---------------------------------------------------------
    def add(
        self,
        text: str,
        *,
        category: Category = "other",
        priority: Priority = "normal",
        keywords: Iterable[str] | None = None,
    ) -> Fact:
        f = Fact(
            id=self._make_id(text, category),
            text=text.strip(),
            category=category,
            priority=priority,
            keywords=list(keywords or []),
        )
        # Refuse duplicates by id (same text + category)
        if any(existing.id == f.id for existing in self._facts):
            raise ValueError(f"Fact already exists: id={f.id}")
        self._facts.append(f)
        return f

    def remove(self, fact_id: str) -> bool:
        for i, f in enumerate(self._facts):
            if f.id == fact_id:
                del self._facts[i]
                return True
        return False

    def update(
        self,
        fact_id: str,
        *,
        text: str | None = None,
        category: Category | None = None,
        priority: Priority | None = None,
        keywords: Iterable[str] | None = None,
        enabled: bool | None = None,
    ) -> Fact | None:
        f = self._find(fact_id)
        if f is None:
            return None
        if text is not None:
            f.text = text.strip()
        if category is not None:
            f.category = category
        if priority is not None:
            f.priority = priority
        if keywords is not None:
            f.keywords = list(keywords)
        if enabled is not None:
            f.enabled = enabled
        # Recompute id when the identity-bearing fields change
        f.id = self._make_id(f.text, f.category)
        return f

    # ----- query ----------------------------------------------------------
    def all(self) -> list[Fact]:
        return list(self._facts)

    def by_category(self, category: Category) -> list[Fact]:
        return [f for f in self._facts if f.category == category]

    def by_priority(self, priority: Priority) -> list[Fact]:
        return [f for f in self._facts if f.priority == priority]

    def for_prompt(self, *, max_facts: int = 20, max_tokens: int = 2000) -> str:
        """Format enabled facts as a system-prompt block. Priority-ranked, token-budgeted."""
        ranked = sorted(
            (f for f in self._facts if f.enabled),
            key=lambda f: (PRIORITY_RANK.get(f.priority, 99), f.category, f.text),
        )
        out: list[str] = []
        used = 0
        for f in ranked[:max_facts]:
            line = f"- ({f.priority}) {f.text}"
            est = estimate_tokens(line)
            if used + est > max_tokens:
                break
            out.append(line)
            used += est
        if not out:
            return ""
        header = "## Authoritative project facts (always honor these)\n"
        return header + "\n".join(out)

    def stats(self) -> dict:
        return {
            "total": len(self._facts),
            "enabled": sum(1 for f in self._facts if f.enabled),
            "by_priority": {p: len(self.by_priority(p)) for p in PRIORITY_RANK},  # type: ignore
            "by_category": {c: len(self.by_category(c)) for c in self.DEFAULT_CATEGORIES},  # type: ignore
        }

    # ----- persistence ----------------------------------------------------
    def load(self) -> int:
        """(Re-)load from the markdown file. Returns count parsed."""
        self._facts = []
        if not self.path.exists():
            return 0
        text = self.path.read_text(encoding="utf-8")
        current_cat: Category = "other"
        for raw in text.splitlines():
            line = raw.rstrip()
            heading = _heading(line)
            if heading is not None:
                current_cat = _CATEGORY_HEADINGS.get(heading.lower(), "other")
                continue
            m = _FACT_RE.match(line)
            if not m:
                continue
            body = m.group("body").strip()
            tags = _TAG_RE.findall(body)
            # Strip only the trailing run of tags — preserve sentence punctuation
            # and any inline #mentions inside the prose.
            clean = _TRAILING_TAGS_RE.sub("", body).rstrip()
            self._facts.append(
                Fact(
                    id=self._make_id(clean, current_cat),
                    text=clean,
                    category=current_cat,
                    priority=m.group("priority").lower(),  # type: ignore[arg-type]
                    keywords=tags,
                )
            )
        return len(self._facts)

    def save(self) -> Path:
        """Write the markdown file with one section per category."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = ["# Project Facts", ""]
        lines.append("<!-- Edit freely. Format: `- [priority] text  #tag1 #tag2`. -->")
        lines.append("<!-- Priority: critical | high | normal | low -->")
        lines.append("")
        for cat in self.DEFAULT_CATEGORIES:
            facts = self.by_category(cat)
            if not facts:
                continue
            heading = cat.title() if cat != "naming" else "Naming Conventions"
            lines.append(f"## {heading}")
            lines.append("")
            facts_sorted = sorted(facts, key=lambda f: PRIORITY_RANK.get(f.priority, 99))
            for f in facts_sorted:
                lines.append(f.to_markdown())
            lines.append("")
        self.path.write_text("\n".join(lines), encoding="utf-8")
        return self.path

    # ----- internal -------------------------------------------------------
    def _find(self, fact_id: str) -> Fact | None:
        for f in self._facts:
            if f.id == fact_id:
                return f
        return None

    @staticmethod
    def _make_id(text: str, category: str) -> str:
        h = hashlib.sha1(f"{category}::{text.strip().lower()}".encode("utf-8"))
        return h.hexdigest()[:10]

    def __len__(self) -> int:
        return len(self._facts)


def _heading(line: str) -> str | None:
    if line.startswith("## "):
        return line[3:].strip()
    if line.startswith("# "):
        return None  # top-level title — not a category
    return None
