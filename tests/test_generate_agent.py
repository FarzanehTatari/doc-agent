"""Agent-loop tests — the Anthropic SDK is mocked so no API call is made."""

from unittest.mock import MagicMock

from doc_agent.extract import CanonicalModel, ModelHeader, Subsystem
from doc_agent.generate.agent import run_agent
from doc_agent.generate.tools import ToolContext


def _ctx() -> ToolContext:
    return ToolContext(
        canonical=CanonicalModel(
            model=ModelHeader(name="X"),
            subsystems=[Subsystem(name="A", path="X/A", depth=1, parent_path="X")],
        )
    )


def _block(btype: str, **kw):
    """Build a content block (text or tool_use) MagicMock."""
    b = MagicMock()
    b.type = btype
    for k, v in kw.items():
        setattr(b, k, v)
    return b


def _response(stop_reason="end_turn", blocks=None, in_tok=10, out_tok=20):
    r = MagicMock()
    r.content = blocks or []
    r.stop_reason = stop_reason
    r.usage.input_tokens = in_tok
    r.usage.output_tokens = out_tok
    return r


def test_single_turn_no_tools():
    client = MagicMock()
    client.chat_with_tools = MagicMock(
        return_value=_response(blocks=[_block("text", text="Hello world.")])
    )
    out = run_agent(client, _ctx(), user_prompt="Say hi")
    assert out.text == "Hello world."
    assert out.iterations == 1
    assert out.tool_calls == []
    assert out.stop_reason == "end_turn"
    assert out.input_tokens == 10 and out.output_tokens == 20


def test_one_tool_call_then_text():
    client = MagicMock()
    client.chat_with_tools = MagicMock(side_effect=[
        _response(
            stop_reason="tool_use",
            blocks=[_block("tool_use", name="list_subsystems", input={}, id="tu_1")],
        ),
        _response(blocks=[_block("text", text="There is one: X/A.")]),
    ])
    out = run_agent(client, _ctx(), user_prompt="What's there?")
    assert out.iterations == 2
    assert len(out.tool_calls) == 1
    assert out.tool_calls[0].name == "list_subsystems"
    # Tool actually ran — output should contain the real list
    assert "X/A" in str(out.tool_calls[0].output)
    assert out.text == "There is one: X/A."


def test_multiple_tools_in_one_turn():
    client = MagicMock()
    client.chat_with_tools = MagicMock(side_effect=[
        _response(
            stop_reason="tool_use",
            blocks=[
                _block("tool_use", name="list_subsystems", input={}, id="t1"),
                _block("tool_use", name="get_subsystem", input={"path": "X/A"}, id="t2"),
            ],
        ),
        _response(blocks=[_block("text", text="done")]),
    ])
    out = run_agent(client, _ctx(), user_prompt="Look around")
    assert len(out.tool_calls) == 2
    assert [tc.name for tc in out.tool_calls] == ["list_subsystems", "get_subsystem"]


def test_max_iterations_caps_runaway():
    client = MagicMock()
    # Always return tool_use → never finishes
    client.chat_with_tools = MagicMock(
        return_value=_response(
            stop_reason="tool_use",
            blocks=[_block("tool_use", name="list_subsystems", input={}, id="t1")],
        )
    )
    out = run_agent(client, _ctx(), user_prompt="Loop", max_iterations=3)
    assert out.iterations == 3
    assert "max_iterations" in (out.error or "")


def test_api_error_is_captured_in_result():
    client = MagicMock()
    client.chat_with_tools = MagicMock(side_effect=RuntimeError("boom"))
    out = run_agent(client, _ctx(), user_prompt="x")
    assert out.error is not None
    assert "boom" in out.error


def test_on_text_and_on_tool_callbacks_fire():
    client = MagicMock()
    client.chat_with_tools = MagicMock(side_effect=[
        _response(
            stop_reason="tool_use",
            blocks=[
                _block("text", text="thinking..."),
                _block("tool_use", name="list_subsystems", input={}, id="t1"),
            ],
        ),
        _response(blocks=[_block("text", text="answer")]),
    ])
    seen_text: list[str] = []
    seen_tool: list[tuple[str, dict]] = []
    run_agent(
        client, _ctx(), user_prompt="x",
        on_text=lambda t: seen_text.append(t),
        on_tool=lambda n, i: seen_tool.append((n, i)),
    )
    assert "thinking..." in seen_text
    assert ("list_subsystems", {}) in seen_tool
