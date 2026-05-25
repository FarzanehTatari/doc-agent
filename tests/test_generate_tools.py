"""Tool-dispatch tests — no API key, no Anthropic, no MATLAB."""

from doc_agent.extract import (
    Block,
    Calibration,
    CanonicalModel,
    DataDictionary,
    DataDictionarySignal,
    ModelHeader,
    Port,
    Signal,
    Stateflow,
    StateflowState,
    StateflowTransition,
    Subsystem,
)
from doc_agent.generate.tools import (
    ToolContext,
    dispatch_tool_call,
    tool_definitions,
)


def _sample() -> CanonicalModel:
    return CanonicalModel(
        model=ModelHeader(name="Toy"),
        subsystems=[
            Subsystem(
                name="WheelAverager",
                path="Toy/WheelAverager",
                depth=1,
                parent_path="Toy",
                inports=[Port(name="In1", port_number=1, data_type="double")],
                outports=[Port(name="Out1", port_number=1, data_type="double")],
                blocks=[
                    Block(name="Sum", type="Sum", parameters={"Inputs": "++"}),
                    Block(
                        name="Gain",
                        type="Gain",
                        parameters={"Gain": "K_FOO"},
                        referenced_calibrations=["K_FOO"],
                    ),
                ],
            ),
        ],
        signals=[
            Signal(
                name="vWheel",
                from_block="Toy/Reader/Out1",
                to_block="Toy/WheelAverager/In1",
            ),
        ],
        stateflow=[
            Stateflow(
                name="StatusMonitor",
                path="Toy/StatusMonitor",
                states=[
                    StateflowState(name="OK",       is_atomic=True,  actions={"entry": "s = 0;"}),
                    StateflowState(name="DEGRADED", is_atomic=True,  actions={"entry": "s = 1;"}),
                ],
                transitions=[
                    StateflowTransition(
                        source="OK", destination="DEGRADED", condition="[wheels_partial]"
                    ),
                ],
            ),
        ],
        data_dictionary=DataDictionary(
            name="Toy.sldd",
            calibrations=[
                Calibration(
                    name="K_FOO", value="0.5", units="s",
                    min="0", max="1", description="A foo",
                ),
            ],
            signals=[DataDictionarySignal(name="vEgo_kmh", data_type="double")],
        ),
    )


# ---- definitions ----------------------------------------------------------
def test_tool_definitions_have_required_fields():
    defs = tool_definitions()
    assert len(defs) >= 8   # 6 base + 2 stateflow
    for d in defs:
        assert "name" in d
        assert "description" in d and d["description"]
        assert "input_schema" in d
        assert d["input_schema"].get("type") == "object"


def test_each_tool_has_a_dispatcher():
    from doc_agent.generate.tools import _DISPATCH

    names = {d["name"] for d in tool_definitions()}
    assert names == set(_DISPATCH.keys())


# ---- list_subsystems -----------------------------------------------------
def test_list_subsystems_returns_model_and_subs():
    ctx = ToolContext(canonical=_sample())
    out = dispatch_tool_call(ctx, "list_subsystems", {})
    assert out["model"] == "Toy"
    assert len(out["subsystems"]) == 1
    assert out["subsystems"][0]["name"] == "WheelAverager"
    assert out["subsystems"][0]["block_count"] == 2


# ---- get_subsystem -------------------------------------------------------
def test_get_subsystem_returns_full_detail():
    ctx = ToolContext(canonical=_sample())
    out = dispatch_tool_call(ctx, "get_subsystem", {"path": "Toy/WheelAverager"})
    assert out["name"] == "WheelAverager"
    assert out["is_atomic"] is False
    assert len(out["blocks"]) == 2
    gain = next(b for b in out["blocks"] if b["name"] == "Gain")
    assert gain["referenced_calibrations"] == ["K_FOO"]


def test_get_subsystem_unknown_path_lists_available():
    ctx = ToolContext(canonical=_sample())
    out = dispatch_tool_call(ctx, "get_subsystem", {"path": "Toy/Missing"})
    assert "error" in out
    assert "Toy/WheelAverager" in out["available_paths"]


# ---- trace_signal --------------------------------------------------------
def test_trace_signal_finds_writers_and_readers():
    ctx = ToolContext(canonical=_sample())
    out = dispatch_tool_call(ctx, "trace_signal", {"name": "vWheel"})
    assert out["found"] is True
    assert "Toy/Reader/Out1" in out["writers"]
    assert "Toy/WheelAverager/In1" in out["readers"]


def test_trace_signal_unknown_returns_empty():
    ctx = ToolContext(canonical=_sample())
    out = dispatch_tool_call(ctx, "trace_signal", {"name": "vMissing"})
    assert out["found"] is False
    assert out["writers"] == []


# ---- calibrations --------------------------------------------------------
def test_lookup_calibration_returns_full_metadata():
    ctx = ToolContext(canonical=_sample())
    out = dispatch_tool_call(ctx, "lookup_calibration", {"name": "K_FOO"})
    assert out["value"] == "0.5"
    assert out["units"] == "s"
    assert out["description"] == "A foo"


def test_lookup_calibration_unknown_lists_available():
    ctx = ToolContext(canonical=_sample())
    out = dispatch_tool_call(ctx, "lookup_calibration", {"name": "K_BAR"})
    assert "error" in out
    assert "K_FOO" in out["available_calibrations"]


def test_lookup_calibration_no_dd():
    canon = _sample()
    canon.data_dictionary = None
    ctx = ToolContext(canonical=canon)
    out = dispatch_tool_call(ctx, "lookup_calibration", {"name": "K_FOO"})
    assert "error" in out


def test_list_calibrations():
    ctx = ToolContext(canonical=_sample())
    out = dispatch_tool_call(ctx, "list_calibrations", {})
    assert out["calibrations"] == ["K_FOO"]


def test_list_dd_signals():
    ctx = ToolContext(canonical=_sample())
    out = dispatch_tool_call(ctx, "list_dd_signals", {})
    assert len(out["signals"]) == 1
    assert out["signals"][0]["name"] == "vEgo_kmh"


# ---- search_rag / list_facts (no manager attached) -----------------------
def test_search_rag_without_manager_returns_error():
    ctx = ToolContext(canonical=_sample(), rag=None)
    out = dispatch_tool_call(ctx, "search_rag", {"query": "anything"})
    assert "error" in out


def test_list_facts_without_memory_returns_empty():
    ctx = ToolContext(canonical=_sample(), facts=None)
    out = dispatch_tool_call(ctx, "list_facts", {})
    assert out["facts"] == []


# ---- stateflow tools -----------------------------------------------------
def test_list_stateflow_charts_with_chart():
    ctx = ToolContext(canonical=_sample())
    out = dispatch_tool_call(ctx, "list_stateflow_charts", {})
    assert len(out["charts"]) == 1
    assert out["charts"][0]["name"] == "StatusMonitor"
    assert out["charts"][0]["state_count"] == 2
    assert out["charts"][0]["transition_count"] == 1


def test_list_stateflow_charts_empty():
    canon = _sample()
    canon.stateflow = []
    ctx = ToolContext(canonical=canon)
    out = dispatch_tool_call(ctx, "list_stateflow_charts", {})
    assert out == {"charts": []}


def test_get_stateflow_chart_returns_full_detail():
    ctx = ToolContext(canonical=_sample())
    out = dispatch_tool_call(ctx, "get_stateflow_chart", {"path": "Toy/StatusMonitor"})
    assert out["name"] == "StatusMonitor"
    assert len(out["states"]) == 2
    assert out["states"][0]["actions"]["entry"] == "s = 0;"
    assert len(out["transitions"]) == 1
    assert out["transitions"][0]["source"] == "OK"
    assert out["transitions"][0]["condition"] == "[wheels_partial]"


def test_get_stateflow_chart_unknown_path_lists_available():
    ctx = ToolContext(canonical=_sample())
    out = dispatch_tool_call(ctx, "get_stateflow_chart", {"path": "Toy/Missing"})
    assert "error" in out
    assert "Toy/StatusMonitor" in out["available_paths"]


# ---- error handling ------------------------------------------------------
def test_unknown_tool():
    ctx = ToolContext(canonical=_sample())
    out = dispatch_tool_call(ctx, "do_evil", {})
    assert "Unknown tool" in out["error"]


def test_missing_required_arg():
    ctx = ToolContext(canonical=_sample())
    out = dispatch_tool_call(ctx, "get_subsystem", {})  # no 'path'
    assert "error" in out
