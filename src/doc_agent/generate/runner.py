"""Single-subsystem generation runner.

Slice 1 scope: produces one deliverable for one subsystem.
Slice 2 will add bottom-up hierarchical generation across the whole model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from doc_agent.ai.client import AIClient
from doc_agent.extract import CanonicalModel
from doc_agent.generate.agent import run_agent
from doc_agent.generate.deliverables import Deliverable
from doc_agent.generate.tools import ToolContext
from doc_agent.memory import FactsMemory
from doc_agent.rag import RAGManager


# Match a Markdown H1 heading whether it sits at the start of the text
# (with optional leading whitespace) or appears mid-line after the model
# crammed narration in front of it (`...conventions.# Unit Requirements`).
_H1_RE = re.compile(r"(?:^|[^A-Za-z0-9_#])(#\s+\S)")


def _strip_preamble(text: str) -> str:
    """Drop any narration the model emitted before the first H1 heading.

    Models occasionally preamble their final response with "I'll start by ..."
    or "Here's what I found ..." even when told not to. Anything before the
    first `# ` heading is not part of the deliverable, so we cut it.

    Handles three cases:
      1. Clean output that already starts with the heading → return as-is.
      2. Preamble followed by `\\n# Heading` → cut at the heading.
      3. Preamble concatenated with `Heading` on the same line (`...end.# Heading`)
         → cut at the `#`.

    If no heading is found at all, return the original text untouched (so we
    never silently swallow content from a malformed response).
    """
    if not text:
        return text
    stripped = text.lstrip()
    if stripped.startswith("# "):
        return stripped
    m = _H1_RE.search(text)
    if m is None:
        return text
    return text[m.start(1):].lstrip()


@dataclass
class GeneratedDoc:
    """Output of one generation call."""

    subsystem_path: str
    deliverable: str
    text: str
    citations: list[str] = field(default_factory=list)
    tool_calls_made: int = 0
    iterations: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None

    def to_markdown(self, *, include_metadata: bool = True) -> str:
        body = self.text.strip()
        if include_metadata:
            cite_line = (
                f"  *Citations:* {', '.join(self.citations)}\n"
                if self.citations else ""
            )
            err_line = (
                f"  *Error:* {self.error}\n" if self.error else ""
            )
            body += (
                "\n\n---\n"
                f"*Generated for `{self.subsystem_path}` "
                f"({self.deliverable}) by doc-agent — "
                f"{self.tool_calls_made} tool call(s), "
                f"{self.iterations} iteration(s), "
                f"{self.input_tokens}+{self.output_tokens} tokens.*\n"
                + cite_line
                + err_line
            )
        return body

    def filename(self, suffix: str = ".md", strip_model_prefix: str | None = None) -> str:
        """Filesystem-safe filename: `<subsystem-path>_<kind>.md`.

        If `strip_model_prefix` is given, drop the leading `<model>/` from the path
        so files under `<model>/` aren't named `<model>_<model>_<subsystem>...`.
        """
        path = self.subsystem_path
        if strip_model_prefix and path.startswith(strip_model_prefix + "/"):
            path = path[len(strip_model_prefix) + 1 :]
        safe = path.replace("/", "_").replace(" ", "_")
        return f"{safe}_{self.deliverable}{suffix}"


def generate_for_subsystem(
    client: AIClient,
    canonical: CanonicalModel,
    *,
    subsystem_path: str,
    deliverable: Deliverable,
    rag: RAGManager | None = None,
    facts: FactsMemory | None = None,
    max_tokens: int = 4096,
    max_iterations: int = 12,
    additional_user_context: str | None = None,
    on_tool=None,
    on_text=None,
) -> GeneratedDoc:
    """Generate one deliverable for one subsystem via the tool-using agent.

    `additional_user_context`, when supplied, is appended to the user prompt —
    used by `generate_all` to feed parents a brief summary of their children's
    already-generated docs so they can reference them without re-investigating.
    """
    sub = canonical.find_subsystem(subsystem_path)
    if sub is None:
        raise ValueError(
            f"Subsystem not found: {subsystem_path}. "
            f"Available: {[s.path for s in canonical.subsystems]}"
        )

    ctx = ToolContext(canonical=canonical, rag=rag, facts=facts)
    system_prompt = deliverable.system_prompt
    user_prompt = deliverable.user_prompt_template.format(
        subsystem_path=subsystem_path,
        model_name=canonical.model.name,
    )
    if additional_user_context:
        user_prompt = f"{user_prompt}\n\n{additional_user_context}"

    result = run_agent(
        client=client,
        ctx=ctx,
        user_prompt=user_prompt,
        system=system_prompt,
        max_tokens=max_tokens,
        max_iterations=max_iterations,
        on_text=on_text,
        on_tool=on_tool,
    )

    # Pull citations out of any search_rag calls
    citations: list[str] = []
    for tc in result.tool_calls:
        if tc.name == "search_rag" and isinstance(tc.output, dict):
            for r in tc.output.get("results", []):
                cite = r.get("citation")
                if cite and cite not in citations:
                    citations.append(cite)

    return GeneratedDoc(
        subsystem_path=subsystem_path,
        deliverable=deliverable.kind,
        text=_strip_preamble(result.text),
        citations=citations,
        tool_calls_made=len(result.tool_calls),
        iterations=result.iterations,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        error=result.error,
    )


# =============================================================================
# generate_all — Slice 2: hierarchical orchestrator
# =============================================================================
@dataclass
class GenerationRunSummary:
    """Result of a `generate_all` run — every doc produced, plus aggregate stats."""

    model: str
    docs: list[GeneratedDoc] = field(default_factory=list)
    elapsed_s: float = 0.0
    failures: list[str] = field(default_factory=list)  # human-readable "Sub/path · kind"

    @property
    def total_input_tokens(self) -> int:
        return sum(d.input_tokens for d in self.docs)

    @property
    def total_output_tokens(self) -> int:
        return sum(d.output_tokens for d in self.docs)

    @property
    def total_tool_calls(self) -> int:
        return sum(d.tool_calls_made for d in self.docs)


def _subsystem_order(canonical: CanonicalModel) -> list:
    """Return subsystems ordered DEEPEST FIRST (bottom-up).

    Within the same depth, preserve the canonical-JSON order. Bottom-up
    matters because a parent's doc may want to reference its children's —
    and we can only do that if the children are generated first.
    """
    # `subsystems` already includes depth on each entry; sort stably.
    return sorted(
        canonical.subsystems,
        key=lambda s: (-int(s.depth), int(getattr(s, "_order", 0))),
    )


def _first_paragraph(text: str, max_chars: int = 240) -> str:
    """Pull the first non-empty paragraph; truncate if longer than max_chars."""
    if not text:
        return ""
    # Skip empty lines and any leading heading line
    paragraphs = [p.strip() for p in text.strip().split("\n\n") if p.strip()]
    for p in paragraphs:
        if p.startswith("#"):
            continue
        if len(p) > max_chars:
            return p[:max_chars].rstrip() + "…"
        return p
    # Fallback: first chunk of whatever we have
    flat = text.strip().replace("\n", " ")
    return flat[:max_chars].rstrip() + ("…" if len(flat) > max_chars else "")


def _build_child_context(
    subsystem,
    kind: str,
    docs_by_path_kind: dict,
) -> str | None:
    """If this subsystem has child subsystems already documented for `kind`,
    inject a brief summary into the user prompt so the parent can reference them
    without redoing the investigation.
    """
    if not subsystem.child_subsystem_paths:
        return None
    lines: list[str] = []
    for child_path in subsystem.child_subsystem_paths:
        child_doc = docs_by_path_kind.get((child_path, kind))
        if child_doc is None or not child_doc.text:
            continue
        summary = _first_paragraph(child_doc.text)
        if summary:
            lines.append(f"- `{child_path}` — {summary}")
    if not lines:
        return None
    return (
        "Child subsystems already documented (for reference; you may also call "
        "`get_subsystem` for full details):\n" + "\n".join(lines)
    )


def generate_all(
    client: AIClient,
    canonical: CanonicalModel,
    *,
    kinds: list[str] | None = None,
    rag: RAGManager | None = None,
    facts: FactsMemory | None = None,
    max_tokens: int = 4096,
    max_iterations: int = 12,
    on_progress=None,            # fn(current, total, subsystem_path, kind, doc_or_none)
    on_tool=None,                # per-call tool hook, passed through
    _runner=None,                # tests: inject a custom per-call runner
) -> GenerationRunSummary:
    """Walk every subsystem bottom-up; run every deliverable kind per subsystem.

    Bottom-up means a parent's generation sees its children's already-produced
    docs as context (via `_build_child_context`). Within the same depth level,
    siblings are generated in canonical-JSON order.

    `_runner` is an injection point for tests: when supplied, it's called in
    place of `generate_for_subsystem` so we can exercise ordering and
    child-context wiring without hitting the LLM.
    """
    import time as _time
    from doc_agent.generate.deliverables import get as get_deliverable

    if not kinds:
        kinds = ["autodoc"]
    # validate kinds upfront so the run fails fast
    deliverables = [get_deliverable(k) for k in kinds]

    summary = GenerationRunSummary(model=canonical.model.name)
    if not canonical.subsystems:
        return summary

    ordered = _subsystem_order(canonical)
    total = len(ordered) * len(deliverables)
    docs_by_path_kind: dict[tuple[str, str], GeneratedDoc] = {}

    runner = _runner or generate_for_subsystem
    t0 = _time.perf_counter()

    current = 0
    for sub in ordered:
        for deliverable in deliverables:
            current += 1
            child_ctx = _build_child_context(sub, deliverable.kind, docs_by_path_kind)
            try:
                doc = runner(
                    client=client,
                    canonical=canonical,
                    subsystem_path=sub.path,
                    deliverable=deliverable,
                    rag=rag,
                    facts=facts,
                    max_tokens=max_tokens,
                    max_iterations=max_iterations,
                    additional_user_context=child_ctx,
                    on_tool=on_tool,
                )
            except Exception as e:  # noqa: BLE001
                summary.failures.append(
                    f"{sub.path} · {deliverable.kind}: {type(e).__name__}: {e}"
                )
                if on_progress:
                    on_progress(current, total, sub.path, deliverable.kind, None)
                continue

            summary.docs.append(doc)
            docs_by_path_kind[(sub.path, deliverable.kind)] = doc
            if on_progress:
                on_progress(current, total, sub.path, deliverable.kind, doc)

    summary.elapsed_s = _time.perf_counter() - t0
    return summary


def write_run_outputs(
    summary: GenerationRunSummary,
    out_dir: "Path",
    *,
    include_metadata: bool = True,
) -> "Path":
    """Write every doc in the summary into out_dir/ and emit an _INDEX.md.

    Returns the path to the index file.
    """
    from collections import defaultdict
    from pathlib import Path as _Path

    out_dir = _Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    model = summary.model or "model"

    for doc in summary.docs:
        fname = doc.filename(strip_model_prefix=model)
        (out_dir / fname).write_text(
            doc.to_markdown(include_metadata=include_metadata),
            encoding="utf-8",
        )

    # Build the index
    by_sub: dict[str, list[GeneratedDoc]] = defaultdict(list)
    for doc in summary.docs:
        by_sub[doc.subsystem_path].append(doc)

    lines: list[str] = []
    lines.append(f"# {model} — Generated Documentation")
    lines.append("")
    lines.append(
        f"_Generated by doc-agent — {len(summary.docs)} document(s), "
        f"{summary.total_input_tokens:,} input + "
        f"{summary.total_output_tokens:,} output tokens, "
        f"{summary.elapsed_s:.1f} s._"
    )
    if summary.failures:
        lines.append("")
        lines.append("> **Note:** Some generations failed:")
        for f in summary.failures:
            lines.append(f"> - {f}")
    lines.append("")
    lines.append("| Subsystem | Deliverables |")
    lines.append("|---|---|")
    for sub_path in sorted(by_sub.keys()):
        links = " · ".join(
            f"[{d.deliverable}]({d.filename(strip_model_prefix=model)})"
            for d in sorted(by_sub[sub_path], key=lambda d: d.deliverable)
        )
        lines.append(f"| `{sub_path}` | {links} |")

    index_path = out_dir / "_INDEX.md"
    index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return index_path
