"""Streamlit entrypoint — Home / status page.

Launch with:  streamlit run src/doc_agent/ui/home.py
Or via:       doc-agent ui
"""

from __future__ import annotations

import streamlit as st

from doc_agent import __version__
from doc_agent.config import settings
from doc_agent.ui._brand import apply_brand
from doc_agent.ui.state import pipeline_summary, reset_pipeline

st.set_page_config(
    page_title="doc-agent",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)
apply_brand()


def _sidebar() -> None:
    with st.sidebar:
        st.markdown(f"### doc-agent  \n*v{__version__}*")
        st.markdown("---")
        st.markdown("**Connection**")
        if settings.has_api_key:
            st.success(f"API key set · `{settings.ai_model}`", icon="✅")
        else:
            st.error("No `ANTHROPIC_API_KEY`", icon="❌")
            st.caption(
                "Put it in your `.env` and restart, or set it in the shell "
                "before launching."
            )
        st.markdown("---")
        st.markdown("**Pipeline**")
        s = pipeline_summary()
        st.markdown(_pipeline_chip("Extract", s["extracted"]["done"]))
        st.markdown(_pipeline_chip("Generate", s["generated"]["done"]))
        st.markdown(_pipeline_chip("Export", s["exported"]["done"]))
        st.markdown("---")
        if st.button("🗑️  Reset pipeline state", width="stretch"):
            reset_pipeline()
            st.rerun()


def _pipeline_chip(label: str, done: bool) -> str:
    return f"{'✅' if done else '⚪️'}  {label}"


def main() -> None:
    _sidebar()

    st.title("📄 doc-agent")
    st.markdown(
        "AI-powered documentation for Simulink control models. "
        "Walks your `.slx` + `.sldd`, generates per-subsystem docs (Design Doc, "
        "System Requirements, Unit Requirements), and exports a consolidated "
        "deliverable in HTML, DOCX, or PDF."
    )

    s = pipeline_summary()

    # --- Status cards -----------------------------------------------------
    c1, c2, c3 = st.columns(3)
    with c1:
        st.subheader("1 · Extract")
        if s["extracted"]["done"]:
            st.metric("Subsystems",  s["extracted"]["subsystems"])
            st.metric("Calibrations", s["extracted"]["calibrations"])
            st.metric("Stateflow",    s["extracted"]["stateflow_charts"])
            st.success("Extracted ✓")
        else:
            st.info("Upload a `.slx` (and optionally a `.sldd`) on the Extract page.")
            st.page_link("pages/1_📄_Extract.py", label="Go to Extract →")
    with c2:
        st.subheader("2 · Generate")
        if s["generated"]["done"]:
            st.metric("Documents", s["generated"]["docs"])
            st.metric("Tokens",    f"{s['generated']['tokens']:,}")
            st.success("Generated ✓")
        elif s["extracted"]["done"]:
            st.info("Pick deliverables and run the agent.")
            st.page_link("pages/2_⚙️_Generate.py", label="Go to Generate →")
        else:
            st.caption("Extract first.")
    with c3:
        st.subheader("3 · Export")
        if s["exported"]["done"]:
            fmts = ", ".join(sorted(s["exported"]["formats"])).upper()
            st.metric("Formats", fmts or "—")
            st.success("Exported ✓")
        elif s["generated"]["done"]:
            st.info("Convert to HTML / DOCX / PDF.")
            st.page_link("pages/3_📤_Export.py", label="Go to Export →")
        else:
            st.caption("Generate first.")

    st.markdown("---")
    with st.expander("ℹ️  How this works"):
        st.markdown(
            """
**The pipeline, in order:**

1. **Extract** — MATLAB reads your `.slx` + `.sldd`, emits a canonical JSON.
2. **Generate** — A tool-using LLM agent walks the JSON subsystem-by-subsystem,
   calling tools to look up calibrations, trace signals, search RAG, and honor
   your project facts. Produces per-subsystem Markdown.
3. **Export** — Consolidate the Markdown files into a single styled HTML, DOCX,
   or PDF.

Use the **Library** page to manage facts (project rules the agent must respect)
and to add reference documents to the RAG library (specs, design memos, PDFs).
"""
        )


if __name__ == "__main__":
    main()
