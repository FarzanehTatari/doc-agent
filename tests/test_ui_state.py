"""UI state helpers — exercise without launching Streamlit.

Streamlit's `session_state` requires a script context; we stub it with a
plain dict so these tests run in any environment.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def fake_streamlit(monkeypatch):
    """Replace `streamlit` with a tiny shim exposing only what state.py needs."""
    fake = types.ModuleType("streamlit")
    fake.session_state = {}
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    yield fake


def test_get_put_delete():
    from doc_agent.ui.state import delete, get, put
    assert get("x") is None
    assert get("x", "fallback") == "fallback"
    put("x", 42)
    assert get("x") == 42
    delete("x")
    assert get("x") is None


def test_reset_pipeline_clears_known_keys(fake_streamlit):
    from doc_agent.ui.state import K, get, put, reset_pipeline
    put(K.SLX_PATH, "/tmp/x.slx")
    put(K.CANONICAL, object())
    put(K.GENERATION_SUMMARY, object())
    put(K.GENERATED_DIR, "/tmp/out")
    put(K.EXPORT_PATHS, {"html": "/tmp/x.html"})
    reset_pipeline()
    for key in (
        K.SLX_PATH, K.SLDD_PATH, K.EXTRACTED_JSON_PATH,
        K.CANONICAL, K.GENERATION_SUMMARY,
        K.GENERATED_DIR, K.EXPORT_PATHS,
    ):
        assert get(key) is None


def test_pipeline_status_flags():
    from doc_agent.ui.state import (
        K, has_exported, has_extracted, has_generated, put,
    )
    assert has_extracted() is False
    assert has_generated() is False
    assert has_exported() is False

    put(K.CANONICAL, object())
    assert has_extracted() is True

    fake_summary = types.SimpleNamespace(docs=[object(), object()])
    put(K.GENERATION_SUMMARY, fake_summary)
    assert has_generated() is True

    # has_exported checks file existence — point at a real file
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
        f.write(b"<html/>")
        tmp_path = f.name
    put(K.EXPORT_PATHS, {"html": tmp_path})
    assert has_exported() is True


def test_pipeline_summary_shape():
    from doc_agent.ui.state import K, pipeline_summary, put
    s = pipeline_summary()
    # Empty state
    assert s["extracted"]["done"] is False
    assert s["generated"]["done"] is False
    assert s["exported"]["done"] is False

    fake_canon = types.SimpleNamespace(
        subsystems=[1, 2, 3],
        data_dictionary=types.SimpleNamespace(calibrations=[1, 2]),
        stateflow=[1],
    )
    put(K.CANONICAL, fake_canon)
    s = pipeline_summary()
    assert s["extracted"]["done"] is True
    assert s["extracted"]["subsystems"] == 3
    assert s["extracted"]["calibrations"] == 2
    assert s["extracted"]["stateflow_charts"] == 1


def test_ensure_upload_dir_caches(monkeypatch, tmp_path):
    """ensure_upload_dir should remember the path across calls."""
    from doc_agent import config as cfg_mod
    from doc_agent.ui.state import ensure_upload_dir

    monkeypatch.setattr(cfg_mod.settings, "data_dir", tmp_path)
    p1 = ensure_upload_dir()
    p2 = ensure_upload_dir()
    assert p1 == p2
    assert p1.exists()
    assert p1.is_dir()
