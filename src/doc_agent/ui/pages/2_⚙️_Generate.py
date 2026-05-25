"""Generate page — run the tool-using agent on one or many subsystems."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from doc_agent.config import settings
from doc_agent.ui._brand import apply_brand
from doc_agent.ui.state import K, get, put

st.set_page_config(page_title="Generate · doc-agent", page_icon="⚙️", layout="wide")
apply_brand()
st.title("⚙️  Generate  ·  canonical JSON → Markdown docs")

canonical = get(K.CANONICAL)

if canonical is None:
    st.warning("No extracted model in this session. Run Extract first.")
    st.page_link("pages/1_📄_Extract.py", label="← Go to Extract", icon="📄")
    st.stop()


# ---- 1. Choose what to generate --------------------------------------------
with st.container(border=True):
    st.subheader("1 · Choose subsystems and deliverables")
    sub_paths_default = [s.path for s in canonical.subsystems]
    c1, c2 = st.columns([3, 2])
    with c1:
        chosen_subs = st.multiselect(
            "Subsystems",
            options=sub_paths_default,
            default=sub_paths_default,
            help="Bottom-up order is preserved automatically; selection just gates which ones get done.",
        )
    with c2:
        kinds = st.multiselect(
            "Deliverables",
            options=["autodoc", "sysreq", "unitreq"],
            default=["autodoc"],
            help="autodoc = Design Doc · sysreq = System Reqs · unitreq = Unit Reqs",
        )

    c1, c2 = st.columns(2)
    use_rag = c1.checkbox("Use RAG library (if non-empty)", value=True)
    use_facts = c2.checkbox("Apply project facts", value=True)

    c1, c2 = st.columns(2)
    max_tokens = c1.slider("Max output tokens / call", 512, 8192, 4096, step=256)
    max_iters = c2.slider("Max tool-loop iterations", 4, 24, 12)


# ---- 2. Run -----------------------------------------------------------------
with st.container(border=True):
    st.subheader("2 · Run")
    can_run = bool(chosen_subs and kinds)
    if not can_run:
        st.info("Pick at least one subsystem and one deliverable.")
    if not settings.has_api_key:
        st.error("No `ANTHROPIC_API_KEY` — set it in `.env` and restart.")
        can_run = False

    total = len(chosen_subs) * len(kinds)
    st.caption(f"Total runs: **{total}** · Bottom-up order is preserved.")

    run = st.button(
        "▶  Generate documents",
        type="primary",
        disabled=not can_run,
        width="content",
    )

    if run:
        from doc_agent.ai.client import AIClient
        from doc_agent.generate import generate_all
        from doc_agent.memory import FactsMemory
        from doc_agent.rag import RAGManager

        # Build a transient canonical that only contains the chosen subsystems.
        # generate_all walks `canonical.subsystems`, so filter accordingly.
        filtered = canonical.model_copy(deep=True)
        filtered.subsystems = [s for s in canonical.subsystems if s.path in chosen_subs]

        # Optional RAG + facts
        rag = None
        if use_rag:
            try:
                r = RAGManager(
                    store_path=settings.rag_dir,
                    collection_name=settings.rag_collection,
                )
                if r.stats()["chunks"] > 0:
                    rag = r
            except Exception:  # noqa: BLE001
                rag = None
        facts = FactsMemory(settings.facts_path) if use_facts else None

        client = AIClient()

        progress = st.progress(0.0, text="Starting…")
        log = st.empty()
        msgs: list[str] = []

        def on_progress(current, total, sub_path, kind, doc):
            frac = current / total if total else 1.0
            label = f"[{current}/{total}] {sub_path} · {kind}"
            progress.progress(frac, text=label)
            if doc is None:
                msgs.append(f"❌  {label} — FAILED")
            else:
                msgs.append(
                    f"✅  {label}  ({doc.iterations} iter, "
                    f"{doc.tool_calls_made} tool, "
                    f"{doc.input_tokens}+{doc.output_tokens} tok)"
                )
            log.markdown("\n".join(f"- {m}" for m in msgs[-12:]))

        try:
            summary = generate_all(
                client=client,
                canonical=filtered,
                kinds=kinds,
                rag=rag,
                facts=facts,
                max_tokens=max_tokens,
                max_iterations=max_iters,
                on_progress=on_progress,
            )
        except Exception as e:  # noqa: BLE001
            st.exception(e)
            st.stop()

        # Persist to disk and remember the output directory
        from doc_agent.generate import write_run_outputs
        target_dir = settings.data_dir / "generated" / canonical.model.name
        target_dir.mkdir(parents=True, exist_ok=True)
        index_path = write_run_outputs(summary, target_dir)

        put(K.GENERATION_SUMMARY, summary)
        put(K.GENERATED_DIR, str(target_dir))

        progress.progress(1.0, text="Done")
        st.success(
            f"Wrote {len(summary.docs)} document(s) to `{target_dir}` "
            f"in {summary.elapsed_s:.1f} s "
            f"(in {summary.total_input_tokens:,} + "
            f"out {summary.total_output_tokens:,} tokens, "
            f"{summary.total_tool_calls} tool calls)."
        )
        if summary.failures:
            with st.expander(f"⚠️  {len(summary.failures)} failure(s)"):
                for f in summary.failures:
                    st.code(f, language=None)


# ---- 3. Preview generated docs ---------------------------------------------
summary = get(K.GENERATION_SUMMARY)
if summary is not None and summary.docs:
    st.markdown("---")
    st.subheader("3 · Preview")
    labels = [f"{d.subsystem_path} · {d.deliverable}" for d in summary.docs]
    choice = st.selectbox("Document", options=range(len(labels)), format_func=lambda i: labels[i])
    doc = summary.docs[choice]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Iterations", doc.iterations)
    c2.metric("Tool calls",  doc.tool_calls_made)
    c3.metric("Input tok",   f"{doc.input_tokens:,}")
    c4.metric("Output tok",  f"{doc.output_tokens:,}")

    st.markdown(doc.text)
    if doc.citations:
        st.caption("Citations: " + ", ".join(doc.citations))

    st.markdown("---")
    st.success("Ready to export. Continue to the **Export** page.")
    st.page_link("pages/3_📤_Export.py", label="Go to Export →", icon="📤")
