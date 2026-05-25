"""Runner-level helpers — preamble stripping etc."""

from unittest.mock import MagicMock

from doc_agent.extract import CanonicalModel, ModelHeader, Subsystem
from doc_agent.generate import GeneratedDoc, generate_all, write_run_outputs
from doc_agent.generate.deliverables import get as get_deliverable
from doc_agent.generate.runner import (
    _build_child_context,
    _first_paragraph,
    _strip_preamble,
    _subsystem_order,
)


def test_already_clean_passes_through():
    src = "# WheelAverager\n\nBody text."
    assert _strip_preamble(src) == "# WheelAverager\n\nBody text."


def test_leading_whitespace_is_trimmed():
    src = "\n\n  # WheelAverager\n\nBody."
    out = _strip_preamble(src)
    assert out.startswith("# WheelAverager")


def test_preamble_with_newline_is_dropped():
    src = (
        "I'll start by exploring the model structure.\n\n"
        "# System Requirements — LowPassFilter\n\n"
        "## Inputs\n- SR-IN-001\n"
    )
    out = _strip_preamble(src)
    assert out.startswith("# System Requirements")
    assert "I'll start" not in out


def test_preamble_concatenated_on_same_line_is_dropped():
    # The exact wedge from the user's screenshot
    src = "I'll start by exploring the model structure and project conventions.# Unit Requirements — LowPassFilter"
    out = _strip_preamble(src)
    assert out.startswith("# Unit Requirements")
    assert "I'll start" not in out


def test_long_preamble_is_dropped():
    src = (
        "Gain block (FilterGain) with gain K_VSE_FILT_TC. Despite its name "
        "'LowPassFilter,' there is no integrator. I'll write the requirements "
        "to what the model actually shows.\n\n"
        "# System Requirements — LowPassFilter\n\n## Inputs\n- SR-IN-001"
    )
    out = _strip_preamble(src)
    assert out.startswith("# System Requirements")
    assert "Despite its name" not in out


def test_no_heading_returns_original():
    src = "Just some prose with no heading at all."
    assert _strip_preamble(src) == src


def test_empty_text_passes_through():
    assert _strip_preamble("") == ""
    assert _strip_preamble("   ") == "   "


def test_hash_inside_word_is_not_treated_as_heading():
    # `#test` (no space) and `function#name` shouldn't be matched
    src = "Some prose with #tag and function#name embedded.\n\n# Real Heading\n\nBody."
    out = _strip_preamble(src)
    assert out.startswith("# Real Heading")


# =============================================================================
# Slice 2 — generate_all orchestrator
# =============================================================================
def _model_with_subs(*subs) -> CanonicalModel:
    return CanonicalModel(model=ModelHeader(name="M"), subsystems=list(subs))


def _stub_runner(*, returns: dict | None = None, captured: list | None = None):
    """A fake `generate_for_subsystem` for use as `_runner` in generate_all.

    `returns` is a dict mapping (subsystem_path, kind) -> text.
    Each call captures (path, kind, additional_user_context) into `captured`.
    """
    returns = returns or {}
    captured = captured if captured is not None else []

    def runner(*, client, canonical, subsystem_path, deliverable, rag, facts,
               max_tokens, max_iterations, additional_user_context, on_tool):
        captured.append((subsystem_path, deliverable.kind, additional_user_context))
        text = returns.get(
            (subsystem_path, deliverable.kind),
            f"# {subsystem_path}\n\nGenerated.",
        )
        return GeneratedDoc(
            subsystem_path=subsystem_path,
            deliverable=deliverable.kind,
            text=text,
            tool_calls_made=1,
            iterations=1,
            input_tokens=100,
            output_tokens=50,
        )

    return runner, captured


# ---- _subsystem_order ----------------------------------------------------
def test_subsystem_order_deepest_first():
    a = Subsystem(name="A", path="M/A", depth=1, parent_path="M")
    b = Subsystem(name="B", path="M/A/B", depth=2, parent_path="M/A")
    c = Subsystem(name="C", path="M/A/B/C", depth=3, parent_path="M/A/B")
    canon = _model_with_subs(a, b, c)
    order = [s.path for s in _subsystem_order(canon)]
    assert order == ["M/A/B/C", "M/A/B", "M/A"]


def test_subsystem_order_preserves_sibling_order():
    a = Subsystem(name="A", path="M/A", depth=1, parent_path="M")
    b = Subsystem(name="B", path="M/B", depth=1, parent_path="M")
    c = Subsystem(name="C", path="M/C", depth=1, parent_path="M")
    canon = _model_with_subs(a, b, c)
    order = [s.path for s in _subsystem_order(canon)]
    assert order == ["M/A", "M/B", "M/C"]


# ---- _first_paragraph ----------------------------------------------------
def test_first_paragraph_skips_heading():
    text = "# Title\n\nFirst paragraph here.\n\nSecond one."
    assert _first_paragraph(text) == "First paragraph here."


def test_first_paragraph_truncates_long_text():
    para = "x" * 500
    text = f"# T\n\n{para}"
    out = _first_paragraph(text, max_chars=100)
    assert len(out) <= 101  # 100 chars + ellipsis
    assert out.endswith("…")


def test_first_paragraph_empty():
    assert _first_paragraph("") == ""


# ---- _build_child_context -----------------------------------------------
def test_child_context_none_when_no_children():
    s = Subsystem(name="A", path="M/A", depth=1, parent_path="M",
                  child_subsystem_paths=[])
    assert _build_child_context(s, "autodoc", {}) is None


def test_child_context_skips_undocumented_children():
    s = Subsystem(name="A", path="M/A", depth=1, parent_path="M",
                  child_subsystem_paths=["M/A/X", "M/A/Y"])
    # X has a doc, Y does not
    docs = {("M/A/X", "autodoc"): GeneratedDoc(
        subsystem_path="M/A/X", deliverable="autodoc",
        text="# X\n\nDoes the X thing.")}
    ctx = _build_child_context(s, "autodoc", docs)
    assert ctx is not None
    assert "M/A/X" in ctx
    assert "M/A/Y" not in ctx
    assert "Does the X thing" in ctx


# ---- generate_all -------------------------------------------------------
def test_generate_all_empty_model_returns_empty_summary():
    canon = _model_with_subs()
    summary = generate_all(client=MagicMock(), canonical=canon, kinds=["autodoc"])
    assert summary.docs == []
    assert summary.failures == []


def test_generate_all_runs_every_subsystem_x_kind():
    a = Subsystem(name="A", path="M/A", depth=1, parent_path="M")
    b = Subsystem(name="B", path="M/B", depth=1, parent_path="M")
    canon = _model_with_subs(a, b)
    runner, captured = _stub_runner()
    summary = generate_all(
        client=MagicMock(), canonical=canon,
        kinds=["autodoc", "sysreq"], _runner=runner,
    )
    assert len(summary.docs) == 4
    pairs = {(p, k) for p, k, _ in captured}
    assert pairs == {("M/A", "autodoc"), ("M/A", "sysreq"),
                     ("M/B", "autodoc"), ("M/B", "sysreq")}


def test_generate_all_walks_deepest_first():
    a = Subsystem(name="A", path="M/A", depth=1, parent_path="M",
                  child_subsystem_paths=["M/A/B"])
    b = Subsystem(name="B", path="M/A/B", depth=2, parent_path="M/A")
    canon = _model_with_subs(a, b)
    runner, captured = _stub_runner()
    generate_all(
        client=MagicMock(), canonical=canon,
        kinds=["autodoc"], _runner=runner,
    )
    paths = [p for p, _, _ in captured]
    assert paths == ["M/A/B", "M/A"]  # deepest first


def test_generate_all_passes_child_context_to_parents():
    a = Subsystem(name="A", path="M/A", depth=1, parent_path="M",
                  child_subsystem_paths=["M/A/B"])
    b = Subsystem(name="B", path="M/A/B", depth=2, parent_path="M/A")
    canon = _model_with_subs(a, b)
    returns = {("M/A/B", "autodoc"): "# B\n\nThe B subsystem averages two signals."}
    runner, captured = _stub_runner(returns=returns)
    generate_all(
        client=MagicMock(), canonical=canon,
        kinds=["autodoc"], _runner=runner,
    )
    # First call (the child) gets no child context
    child_ctx_for_b = next(c for p, k, c in captured if p == "M/A/B")
    assert child_ctx_for_b is None
    # Second call (the parent) gets the child's summary
    child_ctx_for_a = next(c for p, k, c in captured if p == "M/A")
    assert child_ctx_for_a is not None
    assert "M/A/B" in child_ctx_for_a
    assert "averages two signals" in child_ctx_for_a


def test_generate_all_records_failures():
    a = Subsystem(name="A", path="M/A", depth=1, parent_path="M")
    canon = _model_with_subs(a)

    def bad_runner(**_):
        raise RuntimeError("boom")

    summary = generate_all(
        client=MagicMock(), canonical=canon,
        kinds=["autodoc"], _runner=bad_runner,
    )
    assert summary.docs == []
    assert len(summary.failures) == 1
    assert "boom" in summary.failures[0]


# ---- write_run_outputs --------------------------------------------------
def test_write_run_outputs_writes_files_and_index(tmp_path):
    from doc_agent.generate import GenerationRunSummary

    summary = GenerationRunSummary(
        model="VSEModel",
        docs=[
            GeneratedDoc(
                subsystem_path="VSEModel/A", deliverable="autodoc",
                text="# A\n\nbody"),
            GeneratedDoc(
                subsystem_path="VSEModel/B", deliverable="sysreq",
                text="# B\n\nbody"),
        ],
        elapsed_s=12.34,
    )
    out = tmp_path / "out"
    idx = write_run_outputs(summary, out)
    assert (out / "A_autodoc.md").exists()
    assert (out / "B_sysreq.md").exists()
    assert idx.name == "_INDEX.md"
    contents = idx.read_text()
    assert "VSEModel" in contents
    assert "A_autodoc.md" in contents
    assert "B_sysreq.md" in contents


def test_generated_doc_filename_strips_model_prefix():
    d = GeneratedDoc(
        subsystem_path="VSEModel/WheelAverager", deliverable="autodoc",
        text="x")
    assert d.filename(strip_model_prefix="VSEModel") == "WheelAverager_autodoc.md"


def test_generated_doc_filename_handles_nested_path():
    d = GeneratedDoc(
        subsystem_path="VSEModel/A/B/Leaf", deliverable="sysreq", text="x")
    assert d.filename(strip_model_prefix="VSEModel") == "A_B_Leaf_sysreq.md"
