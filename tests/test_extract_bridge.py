"""MatlabBridge tests — uses subprocess monkey-patching so MATLAB is never invoked."""

from __future__ import annotations

import json

import pytest

from doc_agent.extract import MatlabBridge
from doc_agent.extract.schema import CanonicalModel, ModelHeader


def _sample_json() -> str:
    return CanonicalModel(model=ModelHeader(name="VSEModel")).model_dump_json(indent=2)


def test_autodetect_returns_path_if_matlab_on_path(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda x: "/fake/matlab" if x == "matlab" else None)
    monkeypatch.setattr("doc_agent.extract.bridge.glob.glob", lambda *_: [])
    # Path.exists won't be reached when shutil.which returns
    assert MatlabBridge._auto_detect_matlab() == "/fake/matlab"


def test_autodetect_finds_macos_application(monkeypatch, tmp_path):
    fake = tmp_path / "MATLAB_R2099z.app" / "bin" / "matlab"
    fake.parent.mkdir(parents=True)
    fake.write_text("#!/bin/sh\nexit 0\n")
    monkeypatch.setattr("shutil.which", lambda x: None)
    monkeypatch.setattr("doc_agent.extract.bridge.glob.glob", lambda *_: [str(fake)])
    detected = MatlabBridge._auto_detect_matlab()
    assert detected == str(fake)


def test_init_raises_when_matlab_missing(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda x: None)
    monkeypatch.setattr("doc_agent.extract.bridge.glob.glob", lambda *_: [])
    # also force the auto-detection's last-resort path not to exist
    monkeypatch.setattr("pathlib.Path.exists", lambda self: False)
    with pytest.raises(RuntimeError, match="MATLAB executable not found"):
        MatlabBridge(scripts_dir=".")


def test_extract_slx_calls_subprocess_and_loads(monkeypatch, tmp_path):
    # Create a fake scripts dir
    scripts = tmp_path / "matlab"
    scripts.mkdir()

    slx = tmp_path / "VSEModel.slx"
    slx.write_text("fake slx bytes")
    out_json = tmp_path / "extracted.json"

    def fake_run(*args, **kwargs):
        # Simulate MATLAB writing the canonical JSON
        out_json.write_text(_sample_json(), encoding="utf-8")
        class R:
            returncode = 0
            stdout = "ok"
            stderr = ""
        return R()

    monkeypatch.setattr("subprocess.run", fake_run)
    bridge = MatlabBridge(matlab_executable="/fake/matlab", scripts_dir=scripts)
    model = bridge.extract_slx(slx, out_json)
    assert isinstance(model, CanonicalModel)
    assert model.model.name == "VSEModel"


def test_extract_slx_raises_on_nonzero_exit(monkeypatch, tmp_path):
    scripts = tmp_path / "matlab"
    scripts.mkdir()
    slx = tmp_path / "VSEModel.slx"
    slx.write_text("fake")

    def fake_run(*args, **kwargs):
        class R:
            returncode = 2
            stdout = "Building..."
            stderr = "Error: bad block"
        return R()

    monkeypatch.setattr("subprocess.run", fake_run)
    bridge = MatlabBridge(matlab_executable="/fake/matlab", scripts_dir=scripts)
    with pytest.raises(RuntimeError, match="exited with code 2"):
        bridge.extract_slx(slx, tmp_path / "out.json")


def test_load_canonical_round_trip(tmp_path):
    p = tmp_path / "good.json"
    p.write_text(_sample_json(), encoding="utf-8")
    model = MatlabBridge.load_canonical(p)
    assert model.model.name == "VSEModel"


def test_load_canonical_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        MatlabBridge.load_canonical(tmp_path / "nope.json")
