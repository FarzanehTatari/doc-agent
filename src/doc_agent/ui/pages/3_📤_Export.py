"""Export page — bundle generated Markdown into HTML / DOCX / PDF and download."""

from __future__ import annotations

import mimetypes
from pathlib import Path

import streamlit as st

from doc_agent.ui._brand import apply_brand
from doc_agent.ui.state import K, get, put

st.set_page_config(page_title="Export · doc-agent", page_icon="📤", layout="wide")
apply_brand()
st.title("📤 Export  ·  Markdown → HTML / DOCX / PDF")

gen_dir = get(K.GENERATED_DIR)
if not gen_dir or not Path(gen_dir).exists():
    st.warning("Nothing generated yet in this session. Run Generate first.")
    st.page_link("pages/2_⚙️_Generate.py", label="← Go to Generate", icon="⚙️")
    st.stop()

gen_dir = Path(gen_dir)

# Lazy import — avoid loading weasyprint at page load
from doc_agent.export import (   # noqa: E402
    Bundle,
    pdf_is_available,
    write_docx,
    write_html,
    write_pdf,
)


# ---- 1. Bundle preview & pick documents ------------------------------------
with st.container(border=True):
    st.subheader("1 · Bundle")
    bundle = Bundle.from_directory(gen_dir)
    st.markdown(f"**Source:** `{gen_dir}`")
    st.markdown(f"**Model:** `{bundle.model_name}` · {len(bundle)} document(s)")

    # Editable table with a per-row "include" checkbox. Order is preserved,
    # title + kind + filename are read-only.
    table_rows = [
        {
            "include": True,
            "order": i + 1,
            "kind": e.kind,
            "title": e.title,
            "file": e.source_path.name,
        }
        for i, e in enumerate(bundle.entries)
    ]

    st.caption("Tick / untick the **include** column to choose which "
               "documents to export.")
    edited = st.data_editor(
        table_rows,
        key="export_table",
        width="stretch",
        hide_index=True,
        column_config={
            "include": st.column_config.CheckboxColumn(
                "include", help="Untick to exclude this document from the export."
            ),
            "order":   st.column_config.NumberColumn("order", disabled=True),
            "kind":    st.column_config.TextColumn("kind",    disabled=True),
            "title":   st.column_config.TextColumn("title",   disabled=True),
            "file":    st.column_config.TextColumn("file",    disabled=True),
        },
    )

    # Build a filtered Bundle that the writers will consume.
    selected_names = {row["file"] for row in edited if row.get("include")}
    filtered_entries = [
        e for e in bundle.entries if e.source_path.name in selected_names
    ]
    selected_bundle = Bundle(
        model_name=bundle.model_name,
        entries=filtered_entries,
        source_dir=bundle.source_dir,
    )
    st.caption(
        f"**{len(selected_bundle)} of {len(bundle)}** document(s) will be exported."
    )


# ---- 2. Export --------------------------------------------------------------
with st.container(border=True):
    st.subheader("2 · Pick format(s) and export")
    c1, c2, c3 = st.columns(3)
    want_html = c1.checkbox("HTML", value=True)
    want_docx = c2.checkbox("DOCX", value=True)
    want_pdf  = c3.checkbox(
        "PDF" + ("" if pdf_is_available() else "  (weasyprint not installed)"),
        value=False,
        disabled=not pdf_is_available(),
    )

    if not pdf_is_available():
        st.caption(
            "📌 To enable PDF: `pip install -e \".[pdf]\"` "
            "(macOS may need `brew install pango` first)."
        )

    has_selection = len(selected_bundle) > 0
    if not has_selection:
        st.info("Tick at least one document in the bundle to enable export.")

    run = st.button(
        "▶  Export selected formats",
        type="primary",
        disabled=not has_selection or not (want_html or want_docx or want_pdf),
    )

    if run:
        # If the user exported a subset, name the output files with a "_partial"
        # suffix so a later full-bundle export doesn't overwrite it (and the
        # original "VSEModel.docx" remains the canonical full export).
        is_partial = len(selected_bundle) < len(bundle)
        stem = bundle.model_name + ("_partial" if is_partial else "")
        out_base = gen_dir / stem
        written: dict[str, Path] = dict(get(K.EXPORT_PATHS) or {})
        results: list[str] = []

        with st.status(
            f"Exporting {len(selected_bundle)} document(s)…", expanded=True
        ) as status:
            if want_html:
                p = out_base.with_suffix(".html")
                try:
                    write_html(selected_bundle, p)
                    written["html"] = p
                    results.append(f"✅ HTML → `{p}`")
                except Exception as e:  # noqa: BLE001
                    results.append(f"❌ HTML failed — {e}")
            if want_docx:
                p = out_base.with_suffix(".docx")
                try:
                    write_docx(selected_bundle, p)
                    written["docx"] = p
                    results.append(f"✅ DOCX → `{p}`")
                except Exception as e:  # noqa: BLE001
                    results.append(f"❌ DOCX failed — {e}")
            if want_pdf:
                p = out_base.with_suffix(".pdf")
                try:
                    write_pdf(selected_bundle, p)
                    written["pdf"] = p
                    results.append(f"✅ PDF → `{p}`")
                except Exception as e:  # noqa: BLE001
                    results.append(f"❌ PDF failed — {e}")

            for r in results:
                st.markdown(r)
            status.update(label="Export complete", state="complete")

        put(K.EXPORT_PATHS, {k: str(v) for k, v in written.items()})


# ---- 3. Downloads -----------------------------------------------------------
exports = get(K.EXPORT_PATHS) or {}
existing = {fmt: Path(p) for fmt, p in exports.items() if Path(p).exists()}
if existing:
    st.markdown("---")
    st.subheader("3 · Download")
    cols = st.columns(len(existing))
    for col, (fmt, path) in zip(cols, sorted(existing.items()), strict=False):
        mime, _ = mimetypes.guess_type(path.name)
        col.download_button(
            label=f"⬇  Download {fmt.upper()}",
            data=path.read_bytes(),
            file_name=path.name,
            mime=mime or "application/octet-stream",
            width="stretch",
            type="primary",
        )
