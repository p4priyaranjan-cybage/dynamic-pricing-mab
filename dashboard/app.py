"""Streamlit dashboard entrypoint - 5 tabs per the plan's API-first design.
Run: streamlit run dashboard/app.py
"""
from __future__ import annotations

import streamlit as st

from dashboard.api_client import API_BASE_URL
from dashboard.tabs import approval_queue, monitoring, properties, rate_calendar, recommendations, scenario_simulator

st.set_page_config(page_title="Dynamic Pricing MAB", layout="wide")
st.title("Dynamic Pricing - Multi-Armed Bandit Control Center")

with st.sidebar:
    st.subheader("Quick guide")
    st.markdown(
        "- **📅 Rate Calendar** - browse published/pending prices; select a row "
        "to see the full context behind it.\n"
        "- **✅ Approval Queue** - review, approve, reject, or override "
        "low-confidence / large-delta recommendations.\n"
        "- **📊 Monitoring** - fleet-wide arm distribution, override rate, "
        "confidence, approval stats.\n"
        "- **🏨 Properties** - browse the fleet (chain/brand/region/cluster).\n"
        "- **🧪 Scenario Simulator** - try a what-if price for any property/"
        "room/date, side-effect-free, and see *why* it was recommended.\n"
        "- **🗓️ Recommendations** - generate daily/weekly/monthly on-demand "
        "recommendations for a property, with full explainability, then "
        "approve/modify/reject each day."
    )
    st.divider()
    st.caption(f"API: {API_BASE_URL}")

tab_names = [
    "📅 Rate Calendar", "✅ Approval Queue", "📊 Monitoring", "🏨 Properties",
    "🧪 Scenario Simulator", "🗓️ Recommendations",
]
tabs = st.tabs(tab_names)

with tabs[0]:
    rate_calendar.render()
with tabs[1]:
    approval_queue.render()
with tabs[2]:
    monitoring.render()
with tabs[3]:
    properties.render()
with tabs[4]:
    scenario_simulator.render()
with tabs[5]:
    recommendations.render()
