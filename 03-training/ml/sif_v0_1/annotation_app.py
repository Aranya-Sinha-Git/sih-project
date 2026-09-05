"""Local SIF annotation UI backed by durable on-laptop storage."""
from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from label_store import default_store

QUEUE = ROOT / "data" / "labeling_queue.csv"
STORE = default_store()
STORE.initialize()

st.set_page_config(page_title="SIF v0.1 annotation", layout="wide")
st.title("SIF v0.1 — human review")
st.caption("Label credible potential severity from the narrative. Native outcome is context, not the target label.")
reviewer = st.sidebar.text_input("Reviewer name")
st.sidebar.caption(f"Saved locally: {STORE.database}")
st.sidebar.caption(f"Safety backup: {STORE.backup}")
queue = pd.read_csv(QUEUE, dtype=str).fillna("")
done = STORE.current()
remaining = queue[~queue.candidate_id.isin(done.candidate_id)]
st.progress((len(queue) - len(remaining)) / max(len(queue), 1), text=f"{len(queue) - len(remaining)} of {len(queue)} saved")
if message := st.session_state.pop("saved_message", None):
    if message.startswith("Decision saved; export failed:"):
        st.warning(message)
    else:
        st.success(message)
if remaining.empty:
    st.success("All queued reports have a saved decision."); st.stop()
row = remaining.iloc[0]
st.subheader(f"{row['source']} · {row['source_record_id']}")
st.text_area("Narrative", row["narrative"], height=250, disabled=True)
st.caption(f"Native outcome (not the SIF label): {row['source_native_outcome']}")
label = st.radio("Reviewer SIF label", ["SIF_POTENTIAL", "NON_SIF_POTENTIAL", "UNCERTAIN", "SKIP"], index=2)
confidence = st.selectbox("Confidence", ["", "low", "medium", "high"])
notes = st.text_area("Notes (optional)")
if st.button("Save and continue", type="primary"):
    if label in {"SIF_POTENTIAL", "NON_SIF_POTENTIAL"} and len(reviewer.strip()) < 2:
        st.error("Enter the reviewer name before saving a binary reviewed label."); st.stop()
    try:
        STORE.save(row.to_dict(), label, confidence, notes, reviewer)
        st.session_state["saved_message"] = "Decision saved to the laptop database, backup, and CSV exports."
    except RuntimeError as error:
        st.session_state["saved_message"] = str(error)
    st.rerun()
