"""Token estimator tests — no API key required."""

from doc_agent.ai.tokens import (
    estimate_message_tokens,
    estimate_messages_tokens,
    estimate_tokens,
    format_tokens,
)


def test_empty_text_is_zero():
    assert estimate_tokens("") == 0
    assert estimate_tokens(None) == 0


def test_english_prose_uses_4_chars_per_token():
    text = "Hello there, this is a test sentence."  # 37 chars / 4 ≈ 9
    n = estimate_tokens(text)
    assert 7 <= n <= 12


def test_dense_text_uses_smaller_ratio():
    code = '{"a":1,"b":2,"c":[1,2,3],"d":"\\n\\t\\""}'
    text = "Hello there, this is a test sentence."
    # Same length-ish, but dense text should yield MORE tokens
    assert estimate_tokens(code) >= estimate_tokens(text[: len(code)])


def test_message_includes_role_overhead():
    msg = {"role": "user", "content": "hi"}
    assert estimate_message_tokens(msg) >= estimate_tokens("hi") + 1


def test_messages_total_is_sum_of_individuals():
    msgs = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "second answer"},
        {"role": "user", "content": "third"},
    ]
    total = estimate_messages_tokens(msgs)
    parts = sum(estimate_message_tokens(m) for m in msgs)
    assert total == parts


def test_multimodal_content_extracts_text():
    msg = {
        "role": "user",
        "content": [
            {"type": "text", "text": "describe this"},
            {"type": "image", "source": {"type": "base64", "data": "..."}},
        ],
    }
    n = estimate_message_tokens(msg)
    # We don't count image tokens — just the text part + role overhead
    assert n >= estimate_tokens("describe this")


def test_format_tokens_humanizes():
    assert format_tokens(0) == "0"
    assert format_tokens(999) == "999"
    assert format_tokens(1234).endswith("K")
    assert format_tokens(2_500_000).endswith("M")
