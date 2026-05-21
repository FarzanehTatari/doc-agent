"""Token estimation for Claude.

Rule of thumb (Anthropic): ~4 characters per token for English prose, ~2.5
characters per token for code or non-English text. This estimator is intentionally
rough — exact counts can be obtained via Anthropic's `count_tokens` endpoint when
needed, but for budget planning a fast local estimator is enough.
"""

from __future__ import annotations

from collections.abc import Iterable

CHARS_PER_TOKEN_ENGLISH = 4.0
CHARS_PER_TOKEN_DENSE = 2.5  # code, JSON, non-English
ROLE_OVERHEAD_TOKENS = 4  # per message — role + structural framing


def estimate_tokens(text: str | None) -> int:
    """Estimate the token count for a piece of text.

    Heuristic: if the text looks code-dense (lots of punctuation, low whitespace
    ratio), use a tighter ratio. Otherwise default to the English ratio.
    """
    if not text:
        return 0
    n = len(text)
    if n == 0:
        return 0
    # Cheap "dense" detector — code, JSON, and CJK languages all hit this
    nonword = sum(1 for c in text if not c.isalnum() and not c.isspace())
    ratio = CHARS_PER_TOKEN_DENSE if nonword / n > 0.30 else CHARS_PER_TOKEN_ENGLISH
    return max(1, int(n / ratio))


def estimate_message_tokens(message: dict) -> int:
    """Estimate the token count for a single Anthropic message dict.

    Handles both plain-string and content-list (multi-modal) forms.
    """
    content = message.get("content", "")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        # Multi-modal content blocks: pull out text and ignore images (we'd need
        # the actual image dimensions to estimate image tokens accurately).
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        text = "\n".join(parts)
    else:
        text = str(content)
    return estimate_tokens(text) + ROLE_OVERHEAD_TOKENS


def estimate_messages_tokens(messages: Iterable[dict]) -> int:
    """Estimate total token count for a list of Anthropic messages."""
    return sum(estimate_message_tokens(m) for m in messages)


def format_tokens(n: int) -> str:
    """Human-friendly formatting: 1234 -> '1.2K', 123 -> '123'."""
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n / 1000:.1f}K"
    return f"{n / 1_000_000:.2f}M"
