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
    on_tool=None,
    on_text=None,
) -> GeneratedDoc:
    """Generate one deliverable for one subsystem via the tool-using agent."""
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
