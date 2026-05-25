"""Extract page — upload .slx + .sldd, run MATLAB extractor, validate JSON."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from doc_agent.config import settings
from doc_agent.ui._brand import apply_brand
from doc_agent.ui.state import K, ensure_upload_dir, get, put

st.set_page_config(page_title="Extract · doc-agent", page_icon="📄", layout="wide")
apply_brand()
st.title("📄 Extract  ·  `.slx` + `.sldd` → canonical JSON")


# ---- 1. Upload --------------------------------------------------------------
with st.container(border=True):
    st.subheader("1 · Upload your Simulink files")
    c1, c2 = st.columns(2)
    with c1:
        slx_file = st.file_uploader(
            "Simulink model (`.slx`)",
            type=["slx"],
            help="The model you want to document. Required.",
        )
    with c2:
        sldd_file = st.file_uploader(
            "Data dictionary (`.sldd`)",
            type=["sldd"],
            help=(
                "Optional. If present, the extractor walks it for calibration "
                "values, units, ranges, and Simulink.Signal entries."
            ),
        )

    if slx_file is not None:
        upload_dir = ensure_upload_dir()
        slx_path = upload_dir / slx_file.name
        slx_path.write_bytes(slx_file.getbuffer())
        put(K.SLX_PATH, str(slx_path))
        st.caption(f"Saved → `{slx_path}`")
        if sldd_file is not None:
            sldd_path = upload_dir / sldd_file.name
            sldd_path.write_bytes(sldd_file.getbuffer())
            put(K.SLDD_PATH, str(sldd_path))
            st.caption(f"Saved → `{sldd_path}`")


# ---- 2. Run extract ---------------------------------------------------------
with st.container(border=True):
    st.subheader("2 · Run the MATLAB extractor")
    slx_path = get(K.SLX_PATH)

    if not slx_path:
        st.info("Upload a `.slx` above to enable extraction.")
    else:
        st.caption(
            "Headless MATLAB call: `matlab -batch \"extract_slx(...)\"`. "
            "Cold start can take 10–30 s; subsequent calls are faster."
        )
        cols = st.columns([1, 4])
        run = cols[0].button("▶  Extract", type="primary", width="stretch")
        cols[1].caption(f"Target: `{Path(slx_path).name}`")

        if run:
            try:
                from doc_agent.extract import MatlabBridge
            except Exception as e:  # noqa: BLE001
                st.error(f"Cannot import the extractor: {e}")
                st.stop()

            settings.ensure_data_dir()
            settings.extracted_dir.mkdir(parents=True, exist_ok=True)
            out_path = settings.extracted_dir / f"{Path(slx_path).stem}.json"

            with st.status("Running MATLAB extractor…", expanded=True) as status:
                try:
                    bridge = MatlabBridge()
                    st.write(f"Using MATLAB at `{bridge.matlab}`")
                    st.write(f"Writing canonical JSON to `{out_path}`")
                    canonical = bridge.extract_slx(slx_path, out_path)
                    put(K.CANONICAL, canonical)
                    put(K.EXTRACTED_JSON_PATH, str(out_path))
                    status.update(label="Extraction complete ✓", state="complete")
                except Exception as e:  # noqa: BLE001
                    status.update(label="Extraction failed", state="error")
                    st.exception(e)
                    st.stop()


# ---- 3. Review the canonical JSON ------------------------------------------
canonical = get(K.CANONICAL)
if canonical is not None:
    st.markdown("---")
    st.subheader("3 · Canonical model")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Subsystems", len(canonical.subsystems))
    c2.metric(
        "Calibrations",
        len(canonical.data_dictionary.calibrations) if canonical.data_dictionary else 0,
    )
    c3.metric("Stateflow charts", len(canonical.stateflow))
    c4.metric("Top-level signals", len(canonical.signals))

    if canonical.subsystems:
        sub_rows = [
            {
                "path": s.path,
                "depth": s.depth,
                "blocks": len(s.blocks),
                "inports": len(s.inports),
                "outports": len(s.outports),
                "atomic": s.is_atomic,
            }
            for s in canonical.subsystems
        ]
        st.markdown("**Subsystems**")
        st.dataframe(sub_rows, width="stretch", hide_index=True)

    if canonical.data_dictionary and canonical.data_dictionary.calibrations:
        st.markdown("**Calibrations**")
        st.dataframe(
            [
                {
                    "name": c.name, "value": c.value, "units": c.units,
                    "min": c.min, "max": c.max, "description": c.description,
                }
                for c in canonical.data_dictionary.calibrations
            ],
            width="stretch", hide_index=True,
        )

    if canonical.stateflow:
        st.markdown("**Stateflow charts**")
        st.dataframe(
            [
                {
                    "name": c.name, "path": c.path,
                    "states": len(c.states), "transitions": len(c.transitions),
                }
                for c in canonical.stateflow
            ],
            width="stretch", hide_index=True,
        )

    st.success("Ready to generate. Continue to the **Generate** page in the sidebar.")
    st.page_link("pages/2_⚙️_Generate.py", label="Go to Generate →", icon="⚙️")
