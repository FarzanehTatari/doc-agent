"""Library page — manage authoritative facts and the RAG document library."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from doc_agent.config import settings
from doc_agent.ui._brand import apply_brand

st.set_page_config(page_title="Library · doc-agent", page_icon="📚", layout="wide")
apply_brand()
st.title("📚 Library  ·  Facts &amp; RAG")

tab_facts, tab_rag = st.tabs(["📝 Facts", "🔎 RAG documents"])


# =============================================================================
# Facts tab
# =============================================================================
with tab_facts:
    from doc_agent.memory import FactsMemory

    st.caption(
        "Authoritative project facts — naming conventions, units, policies. "
        "Stored in `project_lib/facts.md`. The agent always honors these."
    )
    settings.ensure_data_dir()
    facts = FactsMemory(settings.facts_path)

    # --- existing facts ---
    if len(facts) == 0:
        st.info("No facts yet. Add one below.")
    else:
        rows = [
            {
                "id": f.id,
                "priority": f.priority,
                "category": f.category,
                "text": f.text,
                "enabled": f.enabled,
            }
            for f in facts.all()
        ]
        # Editable so you can toggle `enabled` on/off without removing the fact.
        # The other columns are locked — to change text / category / priority,
        # remove the fact and re-add it (the id is derived from text+category).
        edited = st.data_editor(
            rows,
            column_config={
                "id":       st.column_config.TextColumn("id", disabled=True, width="small"),
                "priority": st.column_config.TextColumn("priority", disabled=True, width="small"),
                "category": st.column_config.TextColumn("category", disabled=True, width="small"),
                "text":     st.column_config.TextColumn("text", disabled=True, width="large"),
                "enabled":  st.column_config.CheckboxColumn(
                    "enabled",
                    help="Toggle to disable a fact without removing it. "
                         "Disabled facts aren't sent to the agent.",
                ),
            },
            width="stretch",
            hide_index=True,
        )

        # Persist any toggles the user made. Match by id so reordering can't
        # cause an off-by-one update.
        changed = False
        fact_by_id = {f.id: f for f in facts.all()}
        for new_row in edited:
            fid = new_row.get("id")
            if fid in fact_by_id and bool(new_row["enabled"]) != fact_by_id[fid].enabled:
                facts.update(fid, enabled=bool(new_row["enabled"]))
                changed = True
        if changed:
            facts.save()
            st.toast("Fact toggle saved.", icon="✅")
            st.rerun()

    # --- add new ---
    with st.expander("➕  Add a new fact", expanded=(len(facts) == 0)):
        with st.form("add_fact", clear_on_submit=True):
            text = st.text_area(
                "Fact text",
                placeholder="Signal names use camelCase with a lowercase unit suffix joined by underscore.",
                height=80,
            )
            c1, c2 = st.columns(2)
            category = c1.selectbox(
                "Category", options=["naming", "domain", "policy", "other"], index=0
            )
            priority = c2.selectbox(
                "Priority", options=["critical", "high", "normal", "low"], index=1
            )
            keywords = st.text_input(
                "Keywords (comma-separated, optional)",
                placeholder="naming, signals",
            )
            submitted = st.form_submit_button("Add fact", type="primary")
            if submitted and text.strip():
                try:
                    kws = [k.strip() for k in keywords.split(",") if k.strip()]
                    facts.add(
                        text.strip(),
                        category=category,    # type: ignore[arg-type]
                        priority=priority,    # type: ignore[arg-type]
                        keywords=kws,
                    )
                    facts.save()
                    st.success("Fact added.")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))

    # --- remove ---
    if len(facts) > 0:
        with st.expander("🗑️  Remove a fact"):
            choice = st.selectbox(
                "Which one?",
                options=[(f.id, f.text) for f in facts.all()],
                format_func=lambda t: f"{t[0]} — {t[1][:80]}",
            )
            if st.button("Remove", type="secondary", key="facts_remove_btn"):
                if facts.remove(choice[0]):
                    facts.save()
                    st.success(f"Removed {choice[0]}.")
                    st.rerun()
                else:
                    st.error("Not found.")


# =============================================================================
# RAG tab
# =============================================================================
with tab_rag:
    st.caption(
        "Reference documents (PDF, DOCX, Markdown, text, code). The agent calls "
        "`search_rag` against this library when it needs design context that "
        "isn't in the model."
    )

    try:
        from doc_agent.rag import RAGManager
    except Exception as e:  # noqa: BLE001
        st.error(f"RAG module unavailable: {e}")
        st.stop()

    settings.ensure_data_dir()
    rag = RAGManager(
        store_path=settings.rag_dir,
        collection_name=settings.rag_collection,
    )
    rag_stats = rag.stats()
    sources = rag.list_documents()

    c1, c2, c3 = st.columns(3)
    c1.metric("Documents", rag_stats["sources"])
    c2.metric("Chunks", rag_stats["chunks"])
    c3.metric("Store", Path(rag_stats["path"]).name)

    if sources:
        st.dataframe(
            [{"document": n, "chunks": c} for n, c in sorted(sources.items())],
            width="stretch", hide_index=True,
        )
    else:
        st.info("No documents indexed. Add one below.")

    # --- add document ---
    with st.expander("➕  Add a document", expanded=(rag_stats["chunks"] == 0)):
        uploaded = st.file_uploader(
            "Pick a file (PDF / DOCX / MD / TXT / code)",
            type=["pdf", "docx", "md", "markdown", "txt", "rst",
                  "py", "m", "c", "cpp", "h", "json", "xml"],
            key="rag_uploader",
        )
        if uploaded is not None and st.button(
            "Index this file", type="primary", key="rag_index_btn"
        ):
            from doc_agent.ui.state import ensure_upload_dir
            up_dir = ensure_upload_dir()
            target = up_dir / uploaded.name
            target.write_bytes(uploaded.getbuffer())
            with st.status(f"Chunking + embedding {target.name}…", expanded=True) as s:
                try:
                    out = rag.add_document(target, progress=lambda m: st.write(m))
                    s.update(label=f"Indexed: {out['chunks']} chunk(s)", state="complete")
                    st.rerun()
                except Exception as e:  # noqa: BLE001
                    s.update(label="Indexing failed", state="error")
                    st.exception(e)

    # --- remove document ---
    if sources:
        with st.expander("🗑️  Remove a document"):
            choice = st.selectbox(
                "Which document?",
                options=sorted(sources.keys()),
                format_func=lambda n: f"{n}  ({sources[n]} chunk{'s' if sources[n] != 1 else ''})",
                key="rag_remove_choice",
            )
            cols = st.columns([1, 4])
            if cols[0].button("Remove", type="secondary", key="rag_remove_btn"):
                n = rag.remove_document(choice)
                if n > 0:
                    st.toast(f"Removed {n} chunk(s) for {choice}.", icon="🗑️")
                    st.rerun()
                else:
                    st.error(f"Nothing removed — {choice} not found in the index.")
            cols[1].caption(
                f"Removes every chunk for `{choice}` from the vector store. "
                "Your original file on disk is **not** deleted."
            )

        # --- bulk clear (behind a confirmation) ---
        with st.expander("⚠️  Clear the entire RAG library"):
            st.warning(
                f"This drops all **{rag_stats['chunks']} chunks** from "
                f"**{rag_stats['sources']} document(s)**. "
                "Original files on disk are untouched. Irreversible."
            )
            confirm = st.checkbox(
                "Yes, I want to wipe the library.",
                key="rag_clear_confirm",
            )
            if st.button(
                "Clear all", type="primary", disabled=not confirm,
                key="rag_clear_btn",
            ):
                rag.clear()
                # Reset the confirmation so a stray re-click doesn't re-fire.
                st.session_state["rag_clear_confirm"] = False
                st.toast("RAG library cleared.", icon="🧹")
                st.rerun()

    # --- search preview ---
    with st.expander("🔎  Preview retrieval (no LLM call)"):
        query = st.text_input("Query", placeholder="e.g. 'low-pass filter design'")
        top_k = st.slider("Top-K", 1, 20, 5)
        if query and st.button("Search", key="rag_search_btn"):
            results = rag.search(query, top_k=top_k)
            if not results:
                st.caption("No matches.")
            for i, r in enumerate(results, 1):
                with st.container(border=True):
                    st.markdown(
                        f"**#{i}**  `{r.citation}`  ·  score `{r.score:.3f}`"
                    )
                    preview = r.text if len(r.text) <= 400 else r.text[:400] + "…"
                    st.text(preview)
