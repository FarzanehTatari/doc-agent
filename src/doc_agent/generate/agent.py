"""Tool-using agent loop.

Iterates `messages.create` calls, dispatching any `tool_use` blocks the model
emits and feeding the results back as `tool_result` blocks, until the model
returns `stop_reason == 'end_turn'` or we hit `max_iterations`.

Anthropic's tool-use protocol in a nutshell:
    request:  messages=[user], tools=[...]
    response: content=[text..., tool_use(name, input, id), ...], stop_reason='tool_use'
    we run the tools, then:
    request:  messages=[user, assistant_response, user{tool_result(id, content)}], tools=[...]
    response: content=[text...], stop_reason='end_turn'
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from doc_agent.ai.client import AIClient
from doc_agent.generate.tools import ToolContext, dispatch_tool_call, tool_definitions
from doc_agent.utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class ToolCallRecord:
    """One tool invocation captured during a run — useful for transcripts."""

    name: str
    input: dict
    output: Any


@dataclass
class AgentResult:
    """Outcome of a `run_agent` call.

    `text` is the FINAL response only (from the end_turn turn). Intermediate
    "thinking out loud" prose the model emits alongside tool calls goes into
    `transcript` instead — that way the deliverable Markdown isn't polluted
    with the model's internal monologue, but the reasoning is still available
    for debugging.
    """

    text: str
    transcript: list[str] = field(default_factory=list)  # intermediate prose, per turn
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    stop_reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    iterations: int = 0
    error: str | None = None


def run_agent(
    client: AIClient,
    ctx: ToolContext,
    *,
    user_prompt: str,
    system: str | None = None,
    max_tokens: int = 4096,
    max_iterations: int = 12,
    on_text: Callable[[str], None] | None = None,
    on_tool: Callable[[str, dict], None] | None = None,
) -> AgentResult:
    """Run a tool-using agent loop until end_turn or max_iterations.

    Args:
        client:         AIClient (must support chat_with_tools)
        ctx:            ToolContext — canonical JSON + optional RAG + facts
        user_prompt:    the user's request (single message)
        system:         system prompt (deliverable-specific instructions)
        max_tokens:     per-turn output cap
        max_iterations: hard stop on tool-loop iterations
        on_text:        optional callback fired with each text chunk between turns
        on_tool:        optional callback fired with (tool_name, tool_input)

    Returns:
        AgentResult with the final text, every tool call made, and usage stats.
    """
    tools = tool_definitions()
    messages: list[dict] = [{"role": "user", "content": user_prompt}]
    result = AgentResult(text="")

    for iteration in range(max_iterations):
        result.iterations = iteration + 1
        try:
            response = client.chat_with_tools(
                messages=messages,
                tools=tools,
                system=system,
                max_tokens=max_tokens,
            )
        except Exception as e:  # noqa: BLE001
            log.debug("Agent call failed", exc_info=True)
            result.error = f"{type(e).__name__}: {e}"
            return result

        # Accumulate usage stats
        usage = getattr(response, "usage", None)
        if usage is not None:
            result.input_tokens += int(getattr(usage, "input_tokens", 0) or 0)
            result.output_tokens += int(getattr(usage, "output_tokens", 0) or 0)
        result.stop_reason = response.stop_reason or ""

        # Split this turn into text vs tool_use blocks
        turn_text = ""
        tool_uses: list = []
        for block in response.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                turn_text += getattr(block, "text", "") or ""
            elif btype == "tool_use":
                tool_uses.append(block)

        if turn_text and on_text:
            on_text(turn_text)

        # End-of-conversation: this is the deliverable text — return it
        if response.stop_reason == "end_turn":
            result.text = turn_text   # final response only — no intermediate prose
            return result

        # Tool-use turn: dispatch each tool, append assistant + tool_results, loop.
        # Any prose the model emitted alongside its tool calls is "thinking
        # out loud" — capture it for debugging via `transcript`, but DO NOT
        # accumulate into `result.text`; that's reserved for the final answer.
        if response.stop_reason == "tool_use":
            if turn_text:
                result.transcript.append(turn_text)
            messages.append({"role": "assistant", "content": response.content})
            tool_results: list[dict] = []
            for tu in tool_uses:
                tname = getattr(tu, "name", "")
                tinput = getattr(tu, "input", {}) or {}
                tid = getattr(tu, "id", "")
                if on_tool:
                    on_tool(tname, tinput)
                output = dispatch_tool_call(ctx, tname, tinput)
                result.tool_calls.append(
                    ToolCallRecord(
                        name=tname,
                        input=tinput,
                        output=output if isinstance(output, (dict, list)) else {"value": output},
                    )
                )
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tid,
                        "content": json.dumps(output, default=str),
                    }
                )
            messages.append({"role": "user", "content": tool_results})
            continue

        # Some other stop reason (max_tokens, refusal, etc.) — bail
        if turn_text:
            result.transcript.append(turn_text)
        result.error = f"Unexpected stop_reason: {response.stop_reason}"
        return result

    # Loop exited without an end_turn
    result.error = f"Reached max_iterations ({max_iterations}) without end_turn"
    return result
