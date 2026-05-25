"""Session-state helpers for the Streamlit UI.

Streamlit reruns the page script on every interaction. To keep large objects
(the parsed CanonicalModel, generation summaries, file paths) alive across
reruns, we stash them in `st.session_state` behind these typed helpers so the
pages don't have to know the string keys.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


# --- session-state keys (single source of truth) -----------------------------
class K:
    UPLOAD_DIR              = "upload_dir"
    SLX_PATH                = "slx_path"
    SLDD_PATH               = "sldd_path"
    EXTRACTED_JSON_PATH     = "extracted_json_path"
    CANONICAL               = "canonical"            # CanonicalModel
    GENERATION_SUMMARY      = "generation_summary"   # GenerationRunSummary
    GENERATED_DIR           = "generated_dir"        # Path to generate-all output dir
    EXPORT_PATHS            = "export_paths"         # dict[str, Path]: format → file


def get(key: str, default: Any = None) -> Any:
    """Read a value from Streamlit session state.

    Imported inside the function so this module can be imported in tests
    that don't have streamlit installed (the tests stub it out)."""
    import streamlit as st
    return st.session_state.get(key, default)


def put(key: str, value: Any) -> None:
    import streamlit as st
    st.session_state[key] = value


def delete(key: str) -> None:
    import streamlit as st
    if key in st.session_state:
        del st.session_state[key]


def reset_pipeline() -> None:
    """Clear every pipeline artifact so the user can start over."""
    for key in (
        K.SLX_PATH, K.SLDD_PATH, K.EXTRACTED_JSON_PATH,
        K.CANONICAL, K.GENERATION_SUMMARY,
        K.GENERATED_DIR, K.EXPORT_PATHS,
    ):
        delete(key)


# --- pipeline status flags --------------------------------------------------
def has_extracted() -> bool:
    return get(K.CANONICAL) is not None


def has_generated() -> bool:
    summary = get(K.GENERATION_SUMMARY)
    return summary is not None and len(getattr(summary, "docs", [])) > 0


def has_exported() -> bool:
    paths = get(K.EXPORT_PATHS) or {}
    return any(Path(p).exists() for p in paths.values())


def pipeline_summary() -> dict:
    """One-line status of each step. Used by Home + the sidebar."""
    canonical = get(K.CANONICAL)
    gen = get(K.GENERATION_SUMMARY)
    exports = get(K.EXPORT_PATHS) or {}
    return {
        "extracted": {
            "done": canonical is not None,
            "subsystems": (len(canonical.subsystems) if canonical else 0),
            "calibrations": (
                len(canonical.data_dictionary.calibrations)
                if canonical and canonical.data_dictionary
                else 0
            ),
            "stateflow_charts": (len(canonical.stateflow) if canonical else 0),
        },
        "generated": {
            "done": gen is not None and len(getattr(gen, "docs", [])) > 0,
            "docs": (len(gen.docs) if gen else 0),
            "tokens": (
                (gen.total_input_tokens + gen.total_output_tokens) if gen else 0
            ),
        },
        "exported": {
            "done": any(Path(p).exists() for p in exports.values()),
            "formats": [k for k, p in exports.items() if Path(p).exists()],
        },
    }


# --- upload directory --------------------------------------------------------
def ensure_upload_dir() -> Path:
    """Create (and remember) a persistent uploads directory under data_dir."""
    from doc_agent.config import settings
    cached = get(K.UPLOAD_DIR)
    if cached and Path(cached).exists():
        return Path(cached)
    settings.ensure_data_dir()
    p = settings.data_dir / "ui_uploads"
    p.mkdir(parents=True, exist_ok=True)
    put(K.UPLOAD_DIR, str(p))
    return p
