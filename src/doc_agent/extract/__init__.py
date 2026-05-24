"""Phase 2 — MATLAB extraction bridge.

Public surface:
    `MatlabBridge`     — wraps `matlab -batch ...` and returns validated CanonicalModel
    `CanonicalModel`   — Pydantic schema for the extracted artifact
    plus every sub-model used by CanonicalModel
"""

from doc_agent.extract.bridge import MatlabBridge
from doc_agent.extract.schema import (
    Block,
    Calibration,
    CanonicalModel,
    DataDictionary,
    DataDictionarySignal,
    ModelHeader,
    Port,
    Provenance,
    Signal,
    Stateflow,
    StateflowState,
    StateflowTransition,
    Subsystem,
)

__all__ = [
    "Block",
    "Calibration",
    "CanonicalModel",
    "DataDictionary",
    "DataDictionarySignal",
    "MatlabBridge",
    "ModelHeader",
    "Port",
    "Provenance",
    "Signal",
    "Stateflow",
    "StateflowState",
    "StateflowTransition",
    "Subsystem",
]
