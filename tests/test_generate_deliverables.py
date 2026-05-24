"""Deliverable definitions — quick contract tests."""

import pytest

from doc_agent.generate import DELIVERABLES, get


def test_three_deliverables_registered():
    assert set(DELIVERABLES.keys()) == {"autodoc", "sysreq", "unitreq"}


def test_each_deliverable_has_required_fields():
    for d in DELIVERABLES.values():
        assert d.kind
        assert d.title
        assert d.system_prompt
        assert "{subsystem_path}" in d.user_prompt_template
        assert "{model_name}" in d.user_prompt_template


def test_get_returns_correct_deliverable():
    assert get("autodoc").title == "Design Doc"
    assert get("sysreq").title == "System Requirements"
    assert get("unitreq").title == "Unit Requirements"


def test_get_is_case_insensitive():
    assert get("AUTODOC").kind == "autodoc"
    assert get("AutoDoc").kind == "autodoc"


def test_get_unknown_kind_raises():
    with pytest.raises(ValueError, match="Unknown deliverable"):
        get("testcase")  # not in Slice 1
    with pytest.raises(ValueError):
        get("")


def test_user_prompt_template_substitutes_cleanly():
    d = get("autodoc")
    out = d.user_prompt_template.format(
        subsystem_path="X/Y", model_name="X"
    )
    assert "X/Y" in out and "model `X`" in out


def test_system_prompt_mentions_tools_and_hallucination_guard():
    """The system prompt is our anti-hallucination contract."""
    for d in DELIVERABLES.values():
        sp = d.system_prompt.lower()
        assert "tool" in sp
        # Each deliverable should warn against invented names
        assert "invent" in sp or "never" in sp


def test_all_deliverables_include_engineering_observations():
    """Every deliverable must always contain an Engineering Observations section
    with a `None.` fallback when there's nothing to report. This is the user-
    explicit consistency requirement — observations should never be silently
    omitted between runs."""
    for kind in ("autodoc", "sysreq", "unitreq"):
        sp = get(kind).system_prompt
        assert "Engineering Observations" in sp, f"{kind}: missing section"
        assert "ALWAYS" in sp, f"{kind}: missing ALWAYS guarantee"
        assert "None." in sp, f"{kind}: missing None. fallback"
