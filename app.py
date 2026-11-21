"""ClerkAI demo screen.

    streamlit run app.py
"""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from clerkai.config import load_env
from clerkai.documents import SUPPORTED, read_bytes

load_env()
from clerkai.llm import get_client
from clerkai.pipeline import process_document
from clerkai.store import RunStore

st.set_page_config(page_title="ClerkAI", page_icon=":ledger:", layout="wide")


@st.cache_resource
def resources() -> tuple[object, RunStore]:
    return get_client(), RunStore("clerkai.db")


client, store = resources()
st.title("ClerkAI")
st.caption(f"AI triage for an accounting firm's shared inbox · model: {client.name}")

tab_process, tab_review, tab_monitor = st.tabs(["Process a document", "Review queue", "Monitoring"])

with tab_process:
    upload = st.file_uploader("Upload an invoice, receipt, ATO notice or client email", type=[s[1:] for s in SUPPORTED])
    pasted = st.text_area("...or paste the text", height=150)
    if st.button("Process", type="primary", disabled=not (upload or pasted.strip())):
        text, name = (read_bytes(upload.getvalue(), upload.name), upload.name) if upload else (pasted, "pasted text")
        with st.spinner("Reading the document..."):
            r = process_document(text, name, client, store)

        d = r.decision
        cols = st.columns(4)
        cols[0].metric("Type", r.extraction.doc_type.value if r.extraction else "failed")
        cols[1].metric("Team", d.team)
        cols[2].metric("Priority", d.priority.value)
        cols[3].metric("Needs review", "Yes" if d.needs_review else "No")
        if d.filed_under:
            st.info(f"Filed under: {d.filed_under}")
        if d.hold:
            st.error("Payment on hold: the bank details do not match the supplier record.")
        for reason in d.reasons:
            st.write(f"- {reason}")
        for task in d.tasks:
            st.warning(f"Task: {task}")

        if r.extraction:
            st.subheader("Extracted fields")
            st.json(r.extraction.model_dump(mode="json"))
        if r.draft:
            st.subheader("Draft reply (needs approval, never sent automatically)")
            st.text_area("Draft", r.draft["text"], height=220)
            with st.expander("What the agent looked up"):
                for call in r.draft["tool_calls"]:
                    st.code(f"{call['tool']}({json.dumps(call['args'])[:200]})")
                st.write("Procedures used:", ", ".join(r.draft["sources"]) or "none")
        st.caption(f"{r.latency_ms:.0f} ms · {r.attempts} attempt(s) · PII masked: {r.pii_masked or 'none'}")

with tab_review:
    queue = store.review_queue()
    st.write(f"**{len(queue)}** item(s) waiting for a person.")
    for item in reversed(queue):
        with st.container(border=True):
            st.write(f"**{item['source']}** · {item['team']} · priority {item['priority']}")
            for reason in item["reasons"]:
                st.write(f"- {reason}")

with tab_monitor:
    s = store.stats()
    cols = st.columns(4)
    cols[0].metric("Runs", f"{s['runs']:.0f}")
    cols[1].metric("Failure rate", f"{s['failure_rate']:.0%}")
    cols[2].metric("Review rate", f"{s['review_rate']:.0%}")
    cols[3].metric("Avg latency", f"{s['avg_latency_ms']:.0f} ms")
    cols = st.columns(3)
    cols[0].metric("Avg tokens per document", f"{s['avg_tokens']:.0f}")
    if s["priced_runs"]:
        per_1000 = s["total_cost_usd"] / s["priced_runs"] * 1000
        cols[1].metric("Total AI cost", f"US${s['total_cost_usd']:.4f}")
        cols[2].metric("Cost per 1,000 documents", f"US${per_1000:.2f}")
    else:
        cols[1].metric("AI cost", "set prices to see")
        cols[2].caption("Set CLERKAI_PRICE_IN_PER_M and CLERKAI_PRICE_OUT_PER_M (USD per million tokens).")
    runs = pd.read_sql_query(
        "SELECT id, created_at, source, status, doc_type, team, priority, needs_review, latency_ms, "
        "llm_calls, tokens_in, tokens_out, cost_usd "
        "FROM runs ORDER BY id DESC LIMIT 200",
        store.conn,
    )
    if not runs.empty:
        st.subheader("Latency per run (ms)")
        st.line_chart(runs.sort_values("id").set_index("id")["latency_ms"])
        st.subheader("Recent runs")
        st.dataframe(runs, hide_index=True, use_container_width=True)
