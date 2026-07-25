"""Rate Calendar tab: recommended rate calendar, filterable by property/
room_type/rate_plan/date range, with confidence score + arm explanation.
Pick any row below to drill into the full context (occupancy/ADR, events,
pace/pickup, comp set, segment/LOS, room & rate type) that drove it."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

from dashboard.api_client import get_properties, get_rate_calendar
from dashboard.context_panel import render_context_panel


def render():
    st.header("📅 Rate Calendar")
    st.caption("Recommended/published prices. Select a row below to see the full context behind it.")
    properties = get_properties()
    prop_options = {p["property_id"]: f"{p['name']} ({p['property_id']})" for p in properties}

    col1, col2, col3 = st.columns(3)
    with col1:
        property_id = st.selectbox("Property", options=[None] + list(prop_options), format_func=lambda x: "All" if x is None else prop_options[x])
    with col2:
        start_date = st.date_input("Start date", value=dt.date.today())
    with col3:
        end_date = st.date_input("End date", value=dt.date.today() + dt.timedelta(days=60))

    rows = get_rate_calendar(property_id=property_id, start_date=str(start_date), end_date=str(end_date))
    if not rows:
        st.info("No published rate calendar rows yet - use Scenario Simulator or trigger a live /score call.")
        return

    df = pd.DataFrame(rows)
    display_df = df[["property_id", "room_type", "rate_plan", "stay_date", "reference_rate", "published_price",
                      "arm_label", "arm_offset_pct", "confidence_score", "confidence_label", "status"]]
    st.dataframe(display_df, use_container_width=True)

    st.subheader("Price trend")
    if property_id:
        chart_df = display_df.sort_values("stay_date")
        st.line_chart(chart_df.set_index("stay_date")[["reference_rate", "published_price"]])

    st.subheader("🔍 Inspect a specific decision")
    row_labels = {
        i: f"{r['property_id']} | {r['room_type']}/{r['rate_plan']} | {r['stay_date']} -> ${r['published_price']:.2f}"
        for i, r in enumerate(rows)
    }
    selected_idx = st.selectbox(
        "Choose a row", options=list(row_labels), format_func=lambda i: row_labels[i], key="rate_calendar_drilldown"
    )
    render_context_panel(rows[selected_idx].get("context", {}), expanded=True)
