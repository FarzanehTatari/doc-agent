"""Tool surface the LLM uses to query the canonical JSON, RAG, and facts.

Each tool wraps a small Python function. Tools are registered with Anthropic
(as JSON Schema definitions); the LLM decides when to call them; our
`dispatch_tool_call` runs the underlying function and returns the result.

Design notes:
- Every tool returns a dict (JSON-serializable). On error, returns `{"error": "..."}`
  so the model can read the error and react instead of crashing the loop.
- Tools are pure — no side effects, no mutation of the context.
- The full set is intentionally small. Add more only when the agent genuinely
  needs them; every tool adds prompt tokens and increases the model's choices.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from doc_agent.extract import CanonicalModel
from doc_agent.memory import FactsMemory
from doc_agent.rag import RAGManager


# ---- context ----------------------------------------------------------------
@dataclass
class ToolContext:
    """All the state a tool might need. RAG and facts are optional."""

    canonical: CanonicalModel
    rag: RAGManager | None = None
    facts: FactsMemory | None = None


# ---- individual tool implementations ----------------------------------------
def _list_subsystems(ctx: ToolContext) -> dict:
    """List every subsystem in the model with quick summary stats."""
    return {
        "model": ctx.canonical.model.name,
        "subsystems": [
            {
                "path": s.path,
                "name": s.name,
                "depth": s.depth,
                "block_count": len(s.blocks),
                "inport_count": len(s.inports),
                "outport_count": len(s.outports),
            }
            for s in ctx.canonical.subsystems
        ],
    }


def _get_subsystem(ctx: ToolContext, path: str) -> dict:
    """Return blocks, ports, parameters, and referenced calibrations of one subsystem."""
    sub = ctx.canonical.find_subsystem(path)
    if sub is None:
        available = [s.path for s in ctx.canonical.subsystems]
        return {
            "error": f"No subsystem at path '{path}'.",
            "available_paths": available,
        }
    return {
        "name": sub.name,
        "path": sub.path,
        "depth": sub.depth,
        "parent_path": sub.parent_path,
        "is_atomic": sub.is_atomic,
        "inports": [p.model_dump() for p in sub.inports],
        "outports": [p.model_dump() for p in sub.outports],
        "blocks": [
            {
                "name": b.name,
                "type": b.type,
                "parameters": b.parameters,
                "referenced_calibrations": b.referenced_calibrations,
            }
            for b in sub.blocks
        ],
        "child_subsystem_paths": sub.child_subsystem_paths,
        "annotations": sub.annotations,
    }


def _trace_signal(ctx: ToolContext, name: str) -> dict:
    """Find writers and readers of a signal by name (top-level connectivity)."""
    writers: list[str] = []
    readers: list[str] = []
    for sig in ctx.canonical.signals:
        if sig.name == name:
            if sig.from_block:
                writers.append(sig.from_block)
            if sig.to_block:
                readers.append(sig.to_block)
    return {
        "name": name,
        "writers": writers,
        "readers": readers,
        "found": bool(writers or readers),
    }


def _lookup_calibration(ctx: ToolContext, name: str) -> dict:
    """Return value, units, min/max, and description of a calibration."""
    if not ctx.canonical.data_dictionary:
        return {"error": "No data dictionary in this model."}
    for cal in ctx.canonical.data_dictionary.calibrations:
        if cal.name == name:
            return cal.model_dump(exclude={"provenance"})
    return {
        "error": f"Calibration '{name}' not found.",
        "available_calibrations": ctx.canonical.calibration_names(),
    }


def _list_calibrations(ctx: ToolContext) -> dict:
    """Return every calibration name in the data dictionary."""
    return {"calibrations": ctx.canonical.calibration_names()}


def _list_dd_signals(ctx: ToolContext) -> dict:
    """Return every Simulink.Signal entry in the data dictionary."""
    if not ctx.canonical.data_dictionary:
        return {"signals": []}
    return {
        "signals": [
            {
                "name": s.name,
                "data_type": s.data_type,
                "dimensions": s.dimensions,
                "description": s.description,
            }
            for s in ctx.canonical.data_dictionary.signals
        ]
    }


def _search_rag(ctx: ToolContext, query: str, top_k: int = 5) -> dict:
    """Search the user's RAG document library; returns top chunks with citations."""
    if ctx.rag is None:
        return {"error": "RAG library not available in this run."}
    try:
        results = ctx.rag.search(query, top_k=int(top_k))
    except Exception as e:  # noqa: BLE001
        return {"error": f"RAG search failed: {e}"}
    return {
        "results": [
            {"citation": r.citation, "score": round(r.score, 3), "text": r.text}
            for r in results
        ]
    }


def _list_facts(ctx: ToolContext) -> dict:
    """Return active project facts (naming conventions, policies, etc.)."""
    if ctx.facts is None:
        return {"facts": []}
    return {
        "facts": [
            {"text": f.text, "category": f.category, "priority": f.priority}
            for f in ctx.facts.all()
            if f.enabled
        ]
    }


def _list_stateflow_charts(ctx: ToolContext) -> dict:
    """List every Stateflow chart in the model with summary counts."""
    charts = ctx.canonical.stateflow or []
    return {
        "charts": [
            {
                "name": c.name,
                "path": c.path,
                "state_count": len(c.states),
                "transition_count": len(c.transitions),
            }
            for c in charts
        ]
    }


def _get_stateflow_chart(ctx: ToolContext, path: str) -> dict:
    """Return full details of one Stateflow chart: states, transitions, actions."""
    charts = ctx.canonical.stateflow or []
    for c in charts:
        if c.path == path:
            return {
                "name": c.name,
                "path": c.path,
                "states": [
                    {
                        "name": s.name,
                        "is_atomic": s.is_atomic,
                        "actions": s.actions,
                    }
                    for s in c.states
                ],
                "transitions": [
                    {
                        "source": t.source,
                        "destination": t.destination,
                        "condition": t.condition,
                        "action": t.action,
                    }
                    for t in c.transitions
                ],
            }
    available = [c.path for c in charts]
    return {
        "error": f"No Stateflow chart at path '{path}'.",
        "available_paths": available,
    }


# ---- registry ---------------------------------------------------------------
ToolFn = Callable[..., dict]

_DISPATCH: dict[str, ToolFn] = {
    "list_subsystems":   _list_subsystems,
    "get_subsystem":     _get_subsystem,
    "trace_signal":      _trace_signal,
    "lookup_calibration": _lookup_calibration,
    "list_calibrations": _list_calibrations,
    "list_dd_signals":   _list_dd_signals,
    "search_rag":        _search_rag,
    "list_facts":        _list_facts,
    "list_stateflow_charts": _list_stateflow_charts,
    "get_stateflow_chart":   _get_stateflow_chart,
}


def tool_definitions() -> list[dict]:
    """Anthropic-compatible tool definitions. Each is a JSON-Schema spec."""
    return [
        {
            "name": "list_subsystems",
            "description": (
                "List every subsystem in the model with its path, depth, and "
                "block counts. Call this first to see what's available before "
                "drilling into a specific subsystem."
            ),
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "get_subsystem",
            "description": (
                "Get full details of one subsystem: inports, outports, blocks, "
                "parameters, referenced calibrations, annotations."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Full subsystem path, e.g. 'VSEModel/WheelAverager'.",
                    }
                },
                "required": ["path"],
            },
        },
        {
            "name": "trace_signal",
            "description": (
                "Find which blocks write a given signal and which read it. "
                "Use when the user asks where a value comes from or goes to."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Signal name."},
                },
                "required": ["name"],
            },
        },
        {
            "name": "lookup_calibration",
            "description": (
                "Get value, units, min, max, and description of a calibration "
                "from the data dictionary. Always call this before quoting a "
                "calibration's number — never invent values."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Calibration name."},
                },
                "required": ["name"],
            },
        },
        {
            "name": "list_calibrations",
            "description": (
                "List every calibration in the data dictionary. Use to verify "
                "a name exists before referencing it."
            ),
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "list_dd_signals",
            "description": "List every Simulink.Signal entry in the data dictionary.",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "search_rag",
            "description": (
                "Search the user's reference document library (PDFs, specs, design "
                "memos). Returns top chunks with citations. Use for context that "
                "isn't in the model itself."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
                },
                "required": ["query"],
            },
        },
        {
            "name": "list_facts",
            "description": (
                "List active project facts — naming conventions, units, policies "
                "that the documentation must respect."
            ),
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "list_stateflow_charts",
            "description": (
                "List every Stateflow chart in the model. Call this when "
                "`get_subsystem` returns no blocks/ports/children for a subsystem "
                "whose name suggests state logic (e.g. *Manager, *Monitor, *Sequencer) — "
                "a Stateflow chart appears as an empty subsystem to `get_subsystem` "
                "but its real content (states + transitions) lives here."
            ),
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "get_stateflow_chart",
            "description": (
                "Get the states, transitions, entry/during/exit actions, and "
                "transition conditions of one Stateflow chart by path."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Full chart path, e.g. 'VSEModel/StatusMonitor'.",
                    }
                },
                "required": ["path"],
            },
        },
    ]


def dispatch_tool_call(ctx: ToolContext, tool_name: str, tool_input: dict) -> Any:
    """Execute a registered tool by name. Returns a JSON-serializable dict."""
    fn = _DISPATCH.get(tool_name)
    if fn is None:
        return {"error": f"Unknown tool: {tool_name}"}
    try:
        return fn(ctx, **(tool_input or {}))
    except TypeError as e:
        return {"error": f"Bad arguments to {tool_name}: {e}"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
