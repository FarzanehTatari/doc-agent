"""Phase 4 — tool-using documentation generation agent."""

from doc_agent.generate.agent import AgentResult, ToolCallRecord, run_agent
from doc_agent.generate.deliverables import (
    AUTODOC,
    DELIVERABLES,
    SYSREQ,
    UNITREQ,
    Deliverable,
    DeliverableKind,
    get,
)
from doc_agent.generate.runner import (
    GeneratedDoc,
    GenerationRunSummary,
    generate_all,
    generate_for_subsystem,
    write_run_outputs,
)
from doc_agent.generate.tools import (
    ToolContext,
    dispatch_tool_call,
    tool_definitions,
)

__all__ = [
    "AUTODOC",
    "SYSREQ",
    "UNITREQ",
    "AgentResult",
    "Deliverable",
    "DeliverableKind",
    "DELIVERABLES",
    "GeneratedDoc",
    "GenerationRunSummary",
    "ToolCallRecord",
    "ToolContext",
    "dispatch_tool_call",
    "generate_all",
    "generate_for_subsystem",
    "get",
    "run_agent",
    "tool_definitions",
    "write_run_outputs",
]
