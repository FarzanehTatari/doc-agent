"""Runner-level helpers — preamble stripping etc."""

from doc_agent.generate.runner import _strip_preamble


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
