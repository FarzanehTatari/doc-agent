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


def test_messages_history_is_prepended():
    """Chat-mode: history + new user prompt all go to the API."""
    client = MagicMock()
    client.chat_with_tools = MagicMock(
        return_value=_response(blocks=[_block("text", text="ok")])
    )
    history = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]
    run_agent(client, _ctx(), user_prompt="and another", messages_history=history)
    sent = client.chat_with_tools.call_args.kwargs["messages"]
    assert len(sent) == 3
    assert sent[0]["content"] == "hello"
    assert sent[1]["content"] == "hi there"
    assert sent[2]["content"] == "and another"
    assert sent[2]["role"] == "user"


def test_messages_history_drops_dangling_user_turn():
    """If history ends with `user` (a previous run crashed), drop it so the
    new user_prompt doesn't produce a user/user adjacency Anthropic rejects."""
    client = MagicMock()
    client.chat_with_tools = MagicMock(
        return_value=_response(blocks=[_block("text", text="ok")])
    )
    history = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "reply"},
        {"role": "user", "content": "second — never got an answer"},
    ]
    run_agent(client, _ctx(), user_prompt="retry", messages_history=history)
    sent = client.chat_with_tools.call_args.kwargs["messages"]
    # The dangling "second" user turn is dropped; we get first/reply/retry.
    assert [m["content"] for m in sent] == ["first", "reply", "retry"]


def test_empty_history_equivalent_to_no_history():
    """Passing [] should behave the same as passing nothing."""
    client = MagicMock()
    client.chat_with_tools = MagicMock(
        return_value=_response(blocks=[_block("text", text="hi")])
    )
    run_agent(client, _ctx(), user_prompt="x", messages_history=[])
    sent = client.chat_with_tools.call_args.kwargs["messages"]
    assert sent == [{"role": "user", "content": "x"}]


def test_stream_true_routes_to_streaming_call():
    """When stream=True, run_agent must use chat_with_tools_stream (not the
    blocking chat_with_tools), and pass on_text straight through so deltas
    flow to the caller."""
    client = MagicMock()
    client.chat_with_tools_stream = MagicMock(
        return_value=_response(blocks=[_block("text", text="hello")])
    )
    seen_text: list[str] = []
    out = run_agent(
        client, _ctx(), user_prompt="hi",
        on_text=lambda t: seen_text.append(t),
        stream=True,
    )
    assert out.text == "hello"
    # The streaming method got called, not the blocking one.
    client.chat_with_tools_stream.assert_called_once()
    # And the callback was forwarded as a kwarg so the SDK can fire it per delta.
    assert "on_text" in client.chat_with_tools_stream.call_args.kwargs


def test_stream_true_suppresses_per_turn_on_text():
    """In streaming mode, on_text is fired per-delta by the SDK. The agent
    must NOT also fire it with the per-turn aggregate (would double-fire)."""
    client = MagicMock()
    client.chat_with_tools_stream = MagicMock(
        return_value=_response(blocks=[_block("text", text="hello world")])
    )
    seen: list[str] = []
    run_agent(
        client, _ctx(), user_prompt="hi",
        on_text=lambda t: seen.append(t),
        stream=True,
    )
    # Mocked SDK doesn't fire deltas — so seen should stay empty even though
    # the turn produced text "hello world".
    assert seen == []


def test_stream_false_still_uses_blocking_call():
    """Default (stream=False) must keep using chat_with_tools, preserving
    backward compatibility for all existing callers."""
    client = MagicMock()
    client.chat_with_tools = MagicMock(
        return_value=_response(blocks=[_block("text", text="ok")])
    )
    # chat_with_tools_stream should not be touched when stream is False.
    client.chat_with_tools_stream = MagicMock()
    run_agent(client, _ctx(), user_prompt="x")
    client.chat_with_tools.assert_called_once()
    client.chat_with_tools_stream.assert_not_called()


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
