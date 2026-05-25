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

    stream_text = st.checkbox(
        "Stream text live as the model writes",
        value=True,
        help="Show the document being written token-by-token. Uncheck for a faster, "
        "quieter run with only progress updates.",
    )


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

        # Live-streaming pane — populated only when stream_text is enabled.
        stream_holder: dict[str, object] = {"buf": "", "placeholder": None, "title": ""}
        if stream_text:
            with st.container(border=True):
                st.caption("✍️  Live preview — current document being written")
                stream_title = st.empty()
                stream_holder["title"] = stream_title
                stream_holder["placeholder"] = st.empty()

        def on_doc_start(sub_path, kind):
            """Reset the live pane at the start of each (sub, kind) generation."""
            stream_holder["buf"] = ""
            ph = stream_holder.get("placeholder")
            title = stream_holder.get("title")
            if title:
                title.markdown(f"**{sub_path}** · _{kind}_")
            if ph:
                ph.markdown("_…waiting for first token…_")

        def on_text(delta: str):
            """Append each streamed delta to the live pane."""
            if not stream_text:
                return
            stream_holder["buf"] = (stream_holder["buf"] or "") + (delta or "")
            ph = stream_holder.get("placeholder")
            if ph:
                ph.markdown(stream_holder["buf"])

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
                on_text=on_text if stream_text else None,
                on_doc_start=on_doc_start if stream_text else None,
                stream=stream_text,
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


# ---- 3. Preview & edit generated docs --------------------------------------
summary = get(K.GENERATION_SUMMARY)
if summary is not None and summary.docs:
    st.markdown("---")
    st.subheader("3 · Preview & edit")
    labels = [f"{d.subsystem_path} · {d.deliverable}" for d in summary.docs]
    choice = st.selectbox("Document", options=range(len(labels)), format_func=lambda i: labels[i])
    doc = summary.docs[choice]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Iterations", doc.iterations)
    c2.metric("Tool calls",  doc.tool_calls_made)
    c3.metric("Input tok",   f"{doc.input_tokens:,}")
    c4.metric("Output tok",  f"{doc.output_tokens:,}")

    # Per-doc editor key — keeps unsaved edits separate across documents.
    editor_key = f"editor::{doc.subsystem_path}::{doc.deliverable}"

    mode = st.radio(
        "Mode",
        options=["View", "Edit"],
        horizontal=True,
        key=f"mode_{choice}",
        label_visibility="collapsed",
    )

    if mode == "View":
        st.markdown(doc.text)
        if doc.citations:
            st.caption("Citations: " + ", ".join(doc.citations))

        # Hint when the user has unsaved buffered edits sitting in the editor
        buf = st.session_state.get(editor_key)
        if buf is not None and buf != doc.text:
            st.info(
                "You have unsaved edits in the editor for this document. "
                "Switch to **Edit** mode to save or revert them.",
                icon="✏️",
            )
    else:  # Edit mode
        # Compute the on-disk path the same way write_run_outputs does.
        target_dir = Path(get(K.GENERATED_DIR) or (settings.data_dir / "generated" / canonical.model.name))
        md_path = target_dir / doc.filename(strip_model_prefix=canonical.model.name)

        st.caption(f"Editing `{md_path.name}` — Markdown source.")
        st.text_area(
            "Markdown source",
            value=doc.text,
            key=editor_key,
            height=480,
            label_visibility="collapsed",
        )

        b1, b2, b3, _ = st.columns([1, 1, 1, 3])
        save = b1.button("💾 Save", key=f"save_btn_{choice}", type="primary")
        revert = b2.button("↺ Revert", key=f"revert_btn_{choice}")
        b3.caption("Save writes both the in-memory doc and the `.md` on disk.")

        if revert:
            # Drop the buffered edits — text_area will repopulate from doc.text
            st.session_state.pop(editor_key, None)
            st.rerun()

        if save:
            from doc_agent.generate import write_run_outputs

            new_text = st.session_state.get(editor_key, doc.text)
            doc.text = new_text  # mutate the GeneratedDoc in the summary

            # Re-emit the full run (docs + _INDEX.md) so links + metadata stay
            # consistent. write_run_outputs is idempotent.
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
                write_run_outputs(summary, target_dir)
                st.toast(f"Saved {md_path.name}", icon="💾")
            except Exception as e:  # noqa: BLE001
                st.error(f"Failed to write `{md_path}`: {e}")

    st.markdown("---")
    st.success("Ready to export. Continue to the **Export** page.")
    st.page_link("pages/3_📤_Export.py", label="Go to Export →", icon="📤")
