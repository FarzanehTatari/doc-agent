"""FactsMemory tests — no API key required."""

import pytest

from doc_agent.memory.facts import FactsMemory


def test_add_and_query(tmp_path):
    f = FactsMemory(tmp_path / "facts.md")
    f.add("Signals use camelCase.", category="naming", priority="critical", keywords=["naming"])
    f.add("Speed in km/h.", category="domain", priority="high")
    assert len(f) == 2
    assert len(f.by_category("naming")) == 1
    assert len(f.by_priority("critical")) == 1


def test_for_prompt_orders_by_priority(tmp_path):
    f = FactsMemory(tmp_path / "facts.md")
    f.add("low one", priority="low")
    f.add("critical one", priority="critical")
    f.add("normal one", priority="normal")
    block = f.for_prompt(max_tokens=500)
    # critical must appear before low in the rendered block
    assert block.index("critical one") < block.index("normal one") < block.index("low one")


def test_save_and_load_round_trip(tmp_path):
    p = tmp_path / "facts.md"
    f = FactsMemory(p)
    f.add("First fact.", category="naming", priority="high", keywords=["a", "b"])
    f.add("Second fact.", category="policy", priority="critical")
    f.save()

    f2 = FactsMemory(p)
    assert len(f2) == 2
    names = {x.text for x in f2.all()}
    assert "First fact." in names
    # keywords survive a round trip
    first = next(x for x in f2.all() if x.text == "First fact.")
    assert "a" in first.keywords and "b" in first.keywords


def test_token_budget_truncates_for_prompt(tmp_path):
    f = FactsMemory(tmp_path / "facts.md")
    for i in range(50):
        f.add(f"fact number {i} with some padding text", priority="normal")
    short = f.for_prompt(max_tokens=20)
    full = f.for_prompt(max_tokens=10_000)
    assert len(short) < len(full)


def test_duplicate_add_is_rejected(tmp_path):
    f = FactsMemory(tmp_path / "facts.md")
    f.add("Same text.", category="other")
    with pytest.raises(ValueError):
        f.add("Same text.", category="other")


def test_remove(tmp_path):
    f = FactsMemory(tmp_path / "facts.md")
    fact = f.add("Removable.", category="other")
    assert f.remove(fact.id) is True
    assert f.remove(fact.id) is False
    assert len(f) == 0


def test_update_changes_id(tmp_path):
    f = FactsMemory(tmp_path / "facts.md")
    fact = f.add("Original.", category="other")
    old_id = fact.id
    f.update(old_id, text="Updated.")
    new_id = f.all()[0].id
    assert new_id != old_id
    assert f.all()[0].text == "Updated."


def test_disabled_fact_round_trips(tmp_path):
    """Round-trip regression: disabling a fact must persist through save+load
    without (a) flipping back to enabled or (b) accumulating ~~ markers in the text.
    """
    p = tmp_path / "facts.md"
    f = FactsMemory(p)
    fact = f.add(
        "Signal names use camelCase.",
        category="naming",
        priority="critical",
        keywords=["naming"],
    )
    f.update(fact.id, enabled=False)
    f.save()

    # Reload from disk
    f2 = FactsMemory(p)
    assert len(f2) == 1
    loaded = f2.all()[0]
    assert loaded.enabled is False, "enabled state was lost on reload"
    # Tildes must be stripped from the text
    assert loaded.text == "Signal names use camelCase."
    assert "~~" not in loaded.text
    # Keywords should survive too
    assert loaded.keywords == ["naming"]


def test_re_enabling_strips_markers_cleanly(tmp_path):
    """Toggle off → save → toggle on → save: text stays clean, no leftover tildes."""
    p = tmp_path / "facts.md"
    f = FactsMemory(p)
    fact = f.add("Vehicle speed is always in km/h.", category="domain", priority="high")
    f.update(fact.id, enabled=False)
    f.save()

    f2 = FactsMemory(p)
    f2.update(f2.all()[0].id, enabled=True)
    f2.save()

    f3 = FactsMemory(p)
    assert f3.all()[0].enabled is True
    assert f3.all()[0].text == "Vehicle speed is always in km/h."
    assert "~~" not in f3.all()[0].text


def test_disabled_fact_with_tags_round_trips(tmp_path):
    """Strikethrough + trailing tags both need to be handled."""
    p = tmp_path / "facts.md"
    f = FactsMemory(p)
    fact = f.add(
        "Use ASIL-D for safety functions.",
        category="policy",
        priority="critical",
        keywords=["safety", "asil"],
    )
    f.update(fact.id, enabled=False)
    f.save()

    f2 = FactsMemory(p)
    loaded = f2.all()[0]
    assert loaded.enabled is False
    assert loaded.text == "Use ASIL-D for safety functions."
    assert set(loaded.keywords) == {"safety", "asil"}


def test_text_with_internal_tildes_is_not_misread_as_disabled(tmp_path):
    """If a fact's text legitimately contains `~~` in the middle, don't
    mistake it for a strikethrough wrapper."""
    p = tmp_path / "facts.md"
    f = FactsMemory(p)
    f.add("Some prose ~~ in the middle of text.", category="other")
    f.save()

    f2 = FactsMemory(p)
    loaded = f2.all()[0]
    assert loaded.enabled is True
    assert "~~" in loaded.text   # the inline tildes survive untouched
