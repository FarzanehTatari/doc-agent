"""Canonical schema round-trip tests — no MATLAB required."""

import json

import pytest

from doc_agent.extract import (
    Block,
    Calibration,
    CanonicalModel,
    DataDictionary,
    DataDictionarySignal,
    ModelHeader,
    Port,
    Stateflow,
    StateflowState,
    StateflowTransition,
    Subsystem,
)


def _sample() -> CanonicalModel:
    return CanonicalModel(
        model=ModelHeader(name="VSEModel", file="/tmp/VSEModel.slx", version="2025b"),
        subsystems=[
            Subsystem(
                id="abc1234567",
                name="WheelAverager",
                path="VSEModel/WheelAverager",
                depth=1,
                parent_path="VSEModel",
                inports=[Port(name="In1", port_number=1, data_type="single")],
                outports=[Port(name="Out1", port_number=1, data_type="single")],
                blocks=[
                    Block(name="Sum", type="Sum", parameters={"Inputs": "++"}),
                    Block(
                        name="LPF",
                        type="TransferFcn",
                        parameters={"Numerator": "[1]", "Denominator": "[K_VSE_FILT_TC 1]"},
                        referenced_calibrations=["K_VSE_FILT_TC"],
                    ),
                ],
            )
        ],
        data_dictionary=DataDictionary(
            name="VSEModel.sldd",
            calibrations=[Calibration(name="K_VSE_FILT_TC", value="0.05", units="s")],
        ),
    )


def test_minimum_required_fields():
    m = CanonicalModel(model=ModelHeader(name="Tiny"))
    assert m.schema_version == 1
    assert m.subsystems == []
    assert m.data_dictionary is None


def test_round_trip_json_preserves_content():
    original = _sample()
    j = original.model_dump_json()
    reloaded = CanonicalModel.model_validate_json(j)
    assert reloaded == original


def test_round_trip_via_pretty_json_file(tmp_path):
    p = tmp_path / "extracted.json"
    p.write_text(_sample().model_dump_json(indent=2), encoding="utf-8")
    loaded = CanonicalModel.model_validate(json.loads(p.read_text(encoding="utf-8")))
    assert loaded.subsystems[0].name == "WheelAverager"


def test_helpers():
    m = _sample()
    assert m.find_subsystem("VSEModel/WheelAverager").name == "WheelAverager"
    assert m.find_subsystem("Missing") is None
    assert "TransferFcn" in m.all_block_types()
    assert m.calibration_names() == ["K_VSE_FILT_TC"]


def test_unknown_extra_fields_ignored():
    raw = {
        "schema_version": 1,
        "model": {"name": "X"},
        "subsystems": [],
        "future_field": "anything goes",
    }
    m = CanonicalModel.model_validate(raw)
    assert m.model.name == "X"


def test_missing_required_model_name_fails():
    raw = {"schema_version": 1, "model": {}}
    with pytest.raises(Exception):
        CanonicalModel.model_validate(raw)


def test_load_canonical_via_bridge_static(tmp_path):
    """The static loader is the integration point — exercise it without MATLAB."""
    from doc_agent.extract import MatlabBridge

    p = tmp_path / "fake.json"
    p.write_text(_sample().model_dump_json(indent=2), encoding="utf-8")
    loaded = MatlabBridge.load_canonical(p)
    assert loaded.model.name == "VSEModel"
    assert len(loaded.subsystems) == 1


def test_load_canonical_rejects_garbage(tmp_path):
    from doc_agent.extract import MatlabBridge

    p = tmp_path / "bad.json"
    p.write_text('{"this_is_not": "a canonical model"}', encoding="utf-8")
    with pytest.raises(RuntimeError):
        MatlabBridge.load_canonical(p)


# ---- Slice 2 — populated data dictionary + stateflow ---------------------
def test_populated_data_dictionary_round_trips():
    m = CanonicalModel(
        model=ModelHeader(name="X"),
        data_dictionary=DataDictionary(
            name="X.sldd",
            path="/tmp/X.sldd",
            calibrations=[
                Calibration(
                    name="K_VSE_FILT_TC",
                    value="0.05",
                    data_type="double",
                    units="s",
                    min="0.01",
                    max="1.0",
                    description="Low-pass filter time constant",
                )
            ],
            signals=[
                DataDictionarySignal(
                    name="vEgo_kmh",
                    data_type="double",
                    description="Filtered ego speed",
                )
            ],
        ),
    )
    j = m.model_dump_json()
    m2 = CanonicalModel.model_validate_json(j)
    assert m2 == m
    assert m2.data_dictionary.calibrations[0].units == "s"
    assert m2.calibration_names() == ["K_VSE_FILT_TC"]


def test_stateflow_with_states_and_transitions():
    sf = Stateflow(
        name="ModeManager",
        path="X/ModeManager",
        states=[
            StateflowState(name="Init", actions={"entry": "x = 0;"}),
            StateflowState(name="Running", is_atomic=True),
        ],
        transitions=[
            StateflowTransition(source="Init", destination="Running", condition="ready"),
        ],
    )
    m = CanonicalModel(model=ModelHeader(name="X"), stateflow=[sf])
    m2 = CanonicalModel.model_validate_json(m.model_dump_json())
    assert m2 == m
    assert m2.stateflow[0].states[0].actions["entry"] == "x = 0;"
    assert m2.stateflow[0].transitions[0].condition == "ready"


def test_empty_stateflow_default_is_empty_list():
    m = CanonicalModel(model=ModelHeader(name="X"))
    assert m.stateflow == []
    m2 = CanonicalModel.model_validate({"schema_version": 1, "model": {"name": "X"}})
    assert m2.stateflow == []
