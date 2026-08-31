"""Streamlit ops console for the delivery exception handler.

Run: ./venv/bin/python -m streamlit run dashboard.py
"""

import os

import pandas as pd
import requests
import streamlit as st

API = os.environ.get("EXCEPTION_API", "http://localhost:8010")

st.set_page_config(page_title="Delivery Exception Console", layout="wide")


def fetch(path: str):
    try:
        resp = requests.get(f"{API}{path}", timeout=5)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        return None


def post(path: str, payload: dict = None):
    try:
        resp = requests.post(f"{API}{path}", json=payload, timeout=120)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        return None


def require(*payloads):
    if any(p is None for p in payloads):
        st.error(f"Backend unreachable at {API}. Start it with python main.py and refresh.")
        st.stop()


page = st.sidebar.radio("Page", ["Queue", "Case detail", "Metrics", "Evaluation"])
health = fetch("/health")
if health:
    llm = health["llm"]
    label = f"{llm['provider']} ({llm['model']})" if llm["available"] else f"rules only, {llm.get('reason', '')}"
    st.sidebar.success(f"Backend up. LLM: {label}")
else:
    st.sidebar.error(f"Backend unreachable at {API}")

if page == "Queue":
    st.title("Exception queue")
    if st.button("Process all delivery logs"):
        result = post("/process")
        require(result)
        st.success(
            f"Processed {result['processed']} rows: {result['exceptions']} exceptions, "
            f"{result['escalated']} escalated."
        )
    data = fetch("/cases")
    require(data)
    cases = data["cases"]
    if not cases:
        st.info("No cases yet. Click the button above to run the pipeline.")
    else:
        table = [
            {
                "shipment": c["shipment_id"],
                "status": c["status_code"],
                "exception": c["triage"]["is_duplicate"] is False and c["triage"]["is_noise"] is False,
                "resolution": (c["decision"] or {}).get("resolution"),
                "escalate": (c["decision"] or {}).get("escalate"),
                "provider": c["provider"],
                "cached": c["cached"],
            }
            for c in cases
        ]
        st.dataframe(pd.DataFrame(table), use_container_width=True)

elif page == "Case detail":
    st.title("Case detail")
    data = fetch("/cases")
    require(data)
    cases = [c for c in data["cases"] if c["decision"]]
    if not cases:
        st.info("No resolved cases yet.")
    else:
        options = {f"{c['shipment_id']} row {c['row_index']} ({c['status_code']})": c for c in cases}
        picked = options[st.selectbox("Case", list(options))]
        decision = picked["decision"]
        st.subheader("Decision")
        st.write(f"Resolution: {decision['resolution']}, escalate: {decision['escalate']}")
        if decision["escalation_reasons"]:
            st.write("Escalation reasons: " + "; ".join(decision["escalation_reasons"]))
        if decision["policy_overrides"]:
            st.warning("Policy overrides: " + "; ".join(decision["policy_overrides"]))
        st.write("Reasoning: " + decision["reasoning"])
        st.caption("Playbook sections: " + ", ".join(decision["playbook_refs"]))
        comm = picked["communication"]
        if comm:
            st.subheader(f"Customer message ({comm['channel']}, {comm['tone']})")
            if comm["subject"]:
                st.write("Subject: " + comm["subject"])
            st.info(comm["body"])
            if not comm["validation_passed"]:
                st.warning("Validation issues: " + "; ".join(comm["validation_issues"]))
        st.caption(
            f"Model tier: {picked['model_tier']}, LLM cost: ${picked['llm_cost_usd']:.5f}, "
            f"review status: {picked['review_status']}"
        )
        if picked["review_status"] == "pending_review":
            st.subheader("Supervisor review")
            a, b = st.columns(2)
            if a.button("Approve decision"):
                result = post(f"/cases/{picked['case_id']}/approve")
                require(result)
                st.success("Approved. Refresh to see the updated status.")
            with b:
                new_res = st.selectbox("Override resolution", [
                    "RESCHEDULE", "REROUTE_TO_LOCKER", "REPLACE",
                    "RETURN_TO_SENDER", "HOLD_FOR_REVIEW", "NO_ACTION",
                ])
                if st.button("Override"):
                    result = post(f"/cases/{picked['case_id']}/override", {"resolution": new_res})
                    require(result)
                    st.success(f"Overridden to {new_res}. Refresh to see the updated status.")

elif page == "Metrics":
    st.title("Metrics")
    data = fetch("/metrics")
    require(data)
    cases, cache = data["cases"], data["llm_cache"]
    if cases.get("total_cases", 0) == 0:
        st.info("No cases processed yet.")
    else:
        c = st.columns(5)
        c[0].metric("Cases", cases["total_cases"])
        c[1].metric("Exceptions", cases["exceptions"])
        c[2].metric("Escalation rate", f"{cases['escalation_rate']:.0%}")
        c[3].metric("LLM cache hit rate", f"{cache['hit_rate']:.0%}")
        c[4].metric("Avg latency", f"{cases['avg_latency_ms']:.0f} ms")
        c2 = st.columns(4)
        c2[0].metric("LLM cost (total)", f"${cases.get('total_llm_cost_usd', 0):.4f}")
        c2[1].metric("Cost / 1k exceptions", f"${cases.get('cost_per_1000_exceptions_usd', 0):.4f}")
        c2[2].metric("Pending review", cases.get("pending_review", 0))
        rules_share = 0.0
        tiers = cases.get("by_model_tier", {})
        if tiers:
            rules_share = tiers.get("rules", 0) / max(sum(tiers.values()), 1)
        c2[3].metric("Handled free by rules", f"{rules_share:.0%}")
        st.subheader("Exceptions by model tier")
        if tiers:
            st.bar_chart(pd.Series(tiers))
        st.subheader("By resolution")
        st.bar_chart(pd.Series(cases["by_resolution"]))
        st.subheader("Cache")
        st.write(cache)

elif page == "Evaluation":
    st.title("Evaluation vs ground truth")
    if st.button("Run evaluation"):
        report = post("/evaluate")
        require(report)
        c = st.columns(5)
        c[0].metric("Noise/dedup", f"{report['noise_dedup_accuracy']:.0%}")
        c[1].metric("Resolution", f"{report['resolution_accuracy']:.0%}")
        c[2].metric("Escalation", f"{report['escalation_accuracy']:.0%}")
        c[3].metric("Tone", f"{report['tone_accuracy']:.0%}")
        c[4].metric("Task completion", f"{report['task_completion_rate']:.0%}")
        st.dataframe(pd.DataFrame(report["per_case"]), use_container_width=True)
