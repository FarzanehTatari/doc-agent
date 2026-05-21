"""SessionStore tests."""

from doc_agent.memory.session import SessionStore


def test_set_get_delete(tmp_path):
    s = SessionStore(tmp_path / "session.json")
    s.set("model", "claude-opus-4-7")
    assert s.get("model") == "claude-opus-4-7"
    assert s.get("missing", "default") == "default"
    assert s.delete("model") is True
    assert s.delete("model") is False
    assert s.get("model") is None


def test_save_and_load_round_trip(tmp_path):
    p = tmp_path / "session.json"
    s = SessionStore(p)
    s.set("counter", 42)
    s.set("flags", {"streaming": True, "debug": False})
    s.save()

    s2 = SessionStore(p)
    assert s2.get("counter") == 42
    assert s2.get("flags") == {"streaming": True, "debug": False}


def test_contains_and_len(tmp_path):
    s = SessionStore(tmp_path / "session.json")
    s.set("a", 1)
    s.set("b", 2)
    assert "a" in s
    assert "c" not in s
    assert len(s) == 2
    s.clear()
    assert len(s) == 0
