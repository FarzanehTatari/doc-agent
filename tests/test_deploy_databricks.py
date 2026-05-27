"""Unit tests for the Databricks deploy helpers.

We can't exercise the actual upload — that needs a live Databricks workspace.
But we CAN cover the validation, transport selection, and error paths, which
are where most bugs would land.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from doc_agent.deploy.databricks import (
    _ensure_transport,
    _validate_canonical_json,
    bootstrap,
    is_databricks_runtime,
    push_canonical_json,
)


# ---- _validate_canonical_json ---------------------------------------------

def _write(tmp_path: Path, name: str, body: str | dict) -> Path:
    p = tmp_path / name
    p.write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")
    return p


def test_validate_accepts_minimal_canonical(tmp_path):
    """A dict with a top-level `model` key is the minimum we accept."""
    p = _write(tmp_path, "ok.json", {"model": {"name": "X"}, "subsystems": []})
    _validate_canonical_json(p)  # no raise


def test_validate_rejects_invalid_json(tmp_path):
    p = _write(tmp_path, "bad.json", "{not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        _validate_canonical_json(p)


def test_validate_rejects_missing_model_key(tmp_path):
    p = _write(tmp_path, "noshape.json", {"subsystems": []})
    with pytest.raises(ValueError, match="missing top-level 'model' key"):
        _validate_canonical_json(p)


def test_validate_rejects_non_object(tmp_path):
    p = _write(tmp_path, "list.json", "[]")
    with pytest.raises(ValueError, match="missing top-level 'model' key"):
        _validate_canonical_json(p)


# ---- bootstrap ------------------------------------------------------------

def test_bootstrap_no_databricks_leaves_env_alone(monkeypatch):
    """When dbutils isn't available, bootstrap does nothing harmful."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.delenv("DATABRICKS_RUNTIME_VERSION", raising=False)
    set_vars = bootstrap(volume_path=None)
    # No secret fetchable, no volume given → nothing should have been set.
    assert set_vars == {}
    assert "ANTHROPIC_API_KEY" not in __import__("os").environ
    assert "DATA_DIR" not in __import__("os").environ


def test_bootstrap_sets_data_dir_from_volume(monkeypatch):
    monkeypatch.delenv("DATA_DIR", raising=False)
    set_vars = bootstrap(volume_path="/Volumes/main/x/y")
    assert set_vars.get("DATA_DIR") == "/Volumes/main/x/y"
    import os
    assert os.environ["DATA_DIR"] == "/Volumes/main/x/y"


def test_bootstrap_respects_existing_env_by_default(monkeypatch):
    """If DATA_DIR is already set, bootstrap should leave it alone."""
    monkeypatch.setenv("DATA_DIR", "/local/path")
    set_vars = bootstrap(volume_path="/Volumes/main/x/y")
    assert "DATA_DIR" not in set_vars
    import os
    assert os.environ["DATA_DIR"] == "/local/path"


def test_bootstrap_overwrite_forces_new_value(monkeypatch):
    monkeypatch.setenv("DATA_DIR", "/local/path")
    bootstrap(volume_path="/Volumes/main/x/y", overwrite=True)
    import os
    assert os.environ["DATA_DIR"] == "/Volumes/main/x/y"


# ---- is_databricks_runtime ------------------------------------------------

def test_is_databricks_runtime_false_locally(monkeypatch):
    monkeypatch.delenv("DATABRICKS_RUNTIME_VERSION", raising=False)
    assert is_databricks_runtime() is False


def test_is_databricks_runtime_true_when_env_set(monkeypatch):
    monkeypatch.setenv("DATABRICKS_RUNTIME_VERSION", "15.4")
    assert is_databricks_runtime() is True


# ---- transport selection --------------------------------------------------

def test_ensure_transport_raises_when_nothing_available(monkeypatch):
    """No SDK, no CLI → clear actionable error, not a stack trace."""
    monkeypatch.setattr(
        "doc_agent.deploy.databricks._sdk_workspace_client", lambda: None
    )
    monkeypatch.setattr(
        "doc_agent.deploy.databricks._cli_available", lambda: False
    )
    with pytest.raises(RuntimeError, match="No Databricks transport available"):
        _ensure_transport()


def test_ensure_transport_prefers_sdk(monkeypatch):
    monkeypatch.setattr(
        "doc_agent.deploy.databricks._sdk_workspace_client", lambda: MagicMock()
    )
    monkeypatch.setattr(
        "doc_agent.deploy.databricks._cli_available", lambda: True
    )
    assert _ensure_transport() == "sdk"


def test_ensure_transport_falls_back_to_cli(monkeypatch):
    monkeypatch.setattr(
        "doc_agent.deploy.databricks._sdk_workspace_client", lambda: None
    )
    monkeypatch.setattr(
        "doc_agent.deploy.databricks._cli_available", lambda: True
    )
    assert _ensure_transport() == "cli"


# ---- push_canonical_json: argument validation -----------------------------

def test_push_rejects_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        push_canonical_json(tmp_path / "does-not-exist.json")


def test_push_rejects_non_json_extension(tmp_path):
    p = tmp_path / "model.txt"
    p.write_text("hi")
    with pytest.raises(ValueError, match="Expected a .json file"):
        push_canonical_json(p)


def test_push_rejects_invalid_canonical_when_validate_true(tmp_path):
    p = _write(tmp_path, "bad.json", {"subsystems": []})  # missing model key
    with pytest.raises(ValueError, match="missing top-level 'model' key"):
        push_canonical_json(p)


def test_push_skips_validation_when_disabled(tmp_path, monkeypatch):
    """validate=False should let garbage through to the transport layer."""
    p = _write(tmp_path, "bad.json", {"subsystems": []})
    # Stub out the transport so the test doesn't try to talk to Databricks.
    monkeypatch.setattr(
        "doc_agent.deploy.databricks._ensure_transport", lambda: "cli"
    )
    with patch("subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        res = push_canonical_json(p, validate=False)
    assert res.transport == "cli"
    assert res.src == p


def test_push_uses_sdk_when_available(tmp_path, monkeypatch):
    p = _write(tmp_path, "ok.json", {"model": {"name": "X"}})
    ws = MagicMock()
    monkeypatch.setattr(
        "doc_agent.deploy.databricks._sdk_workspace_client", lambda: ws
    )
    monkeypatch.setattr(
        "doc_agent.deploy.databricks._cli_available", lambda: True  # would also work
    )
    res = push_canonical_json(p, volume_path="/Volumes/main/x/y")
    assert res.transport == "sdk"
    assert res.dst == "dbfs:/Volumes/main/x/y/extracted/ok.json"
    # The SDK upload was called once
    ws.files.upload.assert_called_once()
