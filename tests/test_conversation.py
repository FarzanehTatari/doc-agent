"""ConversationMemory tests — no API key required."""

from doc_agent.memory.conversation import ConversationMemory


def _make(budget=10_000, history=12) -> ConversationMemory:
    return ConversationMemory(
        max_history=history, max_token_budget=budget, response_token_budget=0
    )


def test_add_and_recent_returns_in_order():
    mem = _make()
    mem.add("user", "first")
    mem.add("assistant", "second")
    mem.add("user", "third")
    assert [m["role"] for m in mem.recent()] == ["user", "assistant", "user"]


def test_recent_drops_oldest_when_over_budget():
    mem = _make(budget=20)  # very small budget, only newest fits
    mem.add("user", "a" * 200)  # ~50 tokens — won't fit
    mem.add("assistant", "b" * 200)  # ~50 tokens — won't fit
    mem.add("user", "c")  # tiny — fits
    recent = mem.recent()
    # Must start with user role per Anthropic; older heavies are gone
    assert recent[0]["role"] == "user"
    assert recent[-1]["content"] == "c"


def test_pinned_messages_always_included():
    mem = _make(budget=20)
    pinned = mem.add("user", "pin me " * 50)  # would normally not fit
    mem.pin(pinned.id)
    mem.add("assistant", "small")
    mem.add("user", "another")
    contents = [m["content"] for m in mem.recent()]
    assert any("pin me" in c for c in contents), "pinned must survive budget pressure"


def test_max_history_trims():
    mem = _make(history=4)
    # Add 6 alternating turns
    mem.add("user", "u1")
    mem.add("assistant", "a1")
    mem.add("user", "u2")
    mem.add("assistant", "a2")
    mem.add("user", "u3")
    mem.add("assistant", "a3")
    recent = mem.recent()
    assert len(recent) <= 4
    assert recent[-1]["content"] == "a3"


def test_clear_preserves_pinned_by_default():
    mem = _make()
    m1 = mem.add("user", "keep me")
    mem.pin(m1.id)
    mem.add("assistant", "throw me")
    removed = mem.clear()
    assert removed == 1
    assert len(mem) == 1
    assert mem.all()[0].pinned is True


def test_clear_all_removes_pinned_too():
    mem = _make()
    m1 = mem.add("user", "u")
    mem.pin(m1.id)
    mem.add("assistant", "a")
    removed = mem.clear(keep_pinned=False)
    assert removed == 2
    assert len(mem) == 0


def test_save_and_load_round_trip(tmp_path):
    p = tmp_path / "conv.json"
    mem = _make()
    mem.persist_path = p
    a = mem.add("user", "hello")
    mem.add("assistant", "hi")
    mem.pin(a.id)
    mem.save()

    mem2 = ConversationMemory.load(p)
    assert len(mem2) == 2
    assert mem2.all()[0].pinned is True
    assert mem2.all()[0].content == "hello"


def test_recent_drops_leading_assistant():
    """Anthropic requires user-first; if budget trim leaves us with assistant first, drop it."""
    mem = _make(budget=10)  # tight
    # add a "small" user then a "small" assistant; recent should start with user
    mem.add("user", "u1")
    mem.add("assistant", "a1")
    recent = mem.recent()
    assert recent[0]["role"] == "user"
