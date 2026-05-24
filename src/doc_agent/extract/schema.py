"""Canonical JSON schema for an extracted Simulink model.

This is the contract between the MATLAB extractor (`matlab/extract_slx.m`) and
every downstream Python consumer. Bump `CanonicalModel.schema_version` whenever
you change a field's meaning in a breaking way; new optional fields don't need
a version bump.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Provenance(BaseModel):
    """Where a fact came from. Lets you trace any entity back to its source."""

    source: str = ""        # file path (.slx, .sldd, .a2l, .arxml)
    element: str = ""       # block handle, .sldd entry name, etc.
    version: str = ""       # git hash / file mtime / MATLAB release


class Port(BaseModel):
    name: str
    port_number: int = 1
    data_type: str = ""
    dimensions: str = ""
    sample_time: str = ""


class Block(BaseModel):
    """A non-subsystem leaf block inside some subsystem."""

    model_config = ConfigDict(extra="ignore")

    id: str = ""
    name: str
    type: str               # e.g. "Sum", "Gain", "TransferFcn"
    parameters: dict[str, str] = Field(default_factory=dict)
    referenced_calibrations: list[str] = Field(default_factory=list)
    link_status: str = "none"   # 'none' | 'resolved' | 'unresolved' | 'implicit'
    provenance: Provenance = Field(default_factory=Provenance)


class Subsystem(BaseModel):
    """A subsystem in the model hierarchy. Top-level model = depth 0."""

    model_config = ConfigDict(extra="ignore")

    id: str = ""
    name: str
    path: str                       # 'Model/Sub/Nested'
    depth: int = 0
    parent_path: str = ""
    is_atomic: bool = False
    is_virtual: bool = True
    inports: list[Port] = Field(default_factory=list)
    outports: list[Port] = Field(default_factory=list)
    blocks: list[Block] = Field(default_factory=list)
    child_subsystem_paths: list[str] = Field(default_factory=list)
    annotations: list[str] = Field(default_factory=list)
    provenance: Provenance = Field(default_factory=Provenance)


class Signal(BaseModel):
    """A connection between two ports (top-level wiring)."""

    id: str = ""
    name: str = ""
    from_block: str = ""
    to_block: str = ""
    provenance: Provenance = Field(default_factory=Provenance)


class Calibration(BaseModel):
    """A calibration entry from the .sldd."""

    id: str = ""
    name: str
    value: str = ""             # stringified — MATLAB values can be vectors/matrices
    data_type: str = ""
    units: str = ""
    min: str = ""
    max: str = ""
    description: str = ""
    provenance: Provenance = Field(default_factory=Provenance)


class DataDictionarySignal(BaseModel):
    """A Simulink.Signal entry from the .sldd."""

    id: str = ""
    name: str
    data_type: str = ""
    dimensions: str = ""
    description: str = ""
    provenance: Provenance = Field(default_factory=Provenance)


class DataDictionary(BaseModel):
    name: str = ""
    path: str = ""
    calibrations: list[Calibration] = Field(default_factory=list)
    signals: list[DataDictionarySignal] = Field(default_factory=list)


class Stateflow(BaseModel):
    """Placeholder for Stateflow charts — full extraction lands in Slice 2."""

    id: str = ""
    name: str = ""
    path: str = ""
    provenance: Provenance = Field(default_factory=Provenance)


class ModelHeader(BaseModel):
    name: str
    file: str = ""
    version: str = ""               # Simulink release that saved the model
    extracted_at: str = ""          # ISO-8601 timestamp
    extractor_version: str = "0.1"


class CanonicalModel(BaseModel):
    """The top-level extracted artifact.

    Field stability:
        `schema_version`     bumped on breaking shape changes
        `extractor_version`  bumped per extract_slx.m revision
    Both ride along so consumers can detect mismatched producer/consumer pairs.
    """

    model_config = ConfigDict(extra="ignore")

    schema_version: int = 1
    model: ModelHeader
    subsystems: list[Subsystem] = Field(default_factory=list)
    signals: list[Signal] = Field(default_factory=list)
    stateflow: list[Stateflow] = Field(default_factory=list)
    data_dictionary: DataDictionary | None = None

    # ----- convenience helpers used by Phase 4 tools ---------------------
    def find_subsystem(self, path: str) -> Subsystem | None:
        for s in self.subsystems:
            if s.path == path:
                return s
        return None

    def all_block_types(self) -> set[str]:
        return {b.type for s in self.subsystems for b in s.blocks}

    def calibration_names(self) -> list[str]:
        if not self.data_dictionary:
            return []
        return [c.name for c in self.data_dictionary.calibrations]
