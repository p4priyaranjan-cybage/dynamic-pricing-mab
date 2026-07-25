"""Recommendations tab: on-demand price recommendations for a property
across a daily/weekly/monthly date range, reusing the exact same
explainability payload as Scenario Simulator/Rate Calendar/Approval Queue
(confidence breakdown, arm probabilities, guardrail-excluded arms) for
every day in the range - then Approve, Modify (override), or Reject each
day's recommendation directly from this view. Optionally override context
(occupancy, pace, comp set, events, etc. - same fields as Scenario
Simulator's what-if panel) applied identically to every day, to see how
the recommendation reacts to a specific demand scenario before publishing.

Generating the range is always side-effect-free (POST /recommendations,
persist=false - same as Scenario Simulator's preview). Only clicking
Approve/Modify & Approve actually publishes a real decision (POST /score),
exactly like Scenario Simulator's "Publish as live decision" button, just
applied per-day across the whole range. Reject is a local, UI-only dismissal
- there is nothing to reject server-side for a recommendation that was
never published."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

from dashboard.api_client import get_properties, get_property_config, get_recommendations, override_decision, score
from dashboard.context_panel import render_context_panel

RANGE_PRESETS = {"Daily (1 day)": 1, "Weekly (7 days)": 7, "Monthly (30 days)": 30}
SEGMENT_OPTIONS = ["transient", "corporate", "group", "leisure"]


def render():
    st.header("🗓️ On-Demand Recommendations")
    st.caption(
        "Generate price recommendations for a property across a date range - daily, weekly, or "
        "monthly - each with the full explainability behind it. Generating is side-effect-free; "
        "use Approve / Modify & Approve / Reject per day to act on individual recommendations."
    )

    properties = get_properties()
    prop_options = {p["property_id"]: f"{p['name']} ({p['property_id']})" for p in properties}

    col1, col2, col3 = st.columns(3)
    with col1:
        property_id = st.selectbox(
            "Property", options=list(prop_options), format_func=lambda x: prop_options[x], key="rec_property"
        )

    config = get_property_config(property_id)
    room_type_options = config.get("room_types") or ["standard"]
    rate_plan_options = config.get("rate_plans") or ["bar_flexible"]
    with col2:
        room_type = st.selectbox("Room type", options=room_type_options, key="rec_room_type")
    with col3:
        rate_plan = st.selectbox("Rate plan", options=rate_plan_options, key="rec_rate_plan")

    col4, col5, col6 = st.columns(3)
    with col4:
        preset = st.radio("Range", options=list(RANGE_PRESETS) + ["Custom"], key="rec_preset")
    with col5:
        start_date = st.date_input("Start date", value=dt.date.today() + dt.timedelta(days=1), key="rec_start")
    with col6:
        if preset == "Custom":
            end_date = st.date_input("End date", value=start_date + dt.timedelta(days=6), key="rec_end")
        else:
            end_date = start_date + dt.timedelta(days=RANGE_PRESETS[preset] - 1)
            st.text_input("End date", value=str(end_date), disabled=True)

    los_nights = st.number_input("Length of stay (nights)", min_value=1, max_value=14, value=2, key="rec_los")

    st.divider()
    override_enabled = st.checkbox(
        "🔧 Override context for this range (apply the same manual context to every day generated below)",
        key="rec_override_enabled",
    )
    context_overrides = None
    if override_enabled:
        st.caption(
            "Applied identically to every day below, overriding the naturally simulated context - see "
            "how the recommendation reacts to a specific demand scenario before publishing/approving "
            "anything. Leave unchecked to use the naturally simulated context per day (default)."
        )
        event_flag = st.checkbox("Local Event Active", value=False, key="rec_override_event_flag")
        oc1, oc2, oc3 = st.columns(3)
        with oc1:
            occupancy_pct = st.slider("Occupancy %", 0.0, 100.0, 55.0, key="rec_override_occupancy")
            adr_trend_pct = st.slider("ADR Trend %", -20.0, 20.0, 0.0, key="rec_override_adr_trend")
            remaining_inventory_pct = st.slider("Remaining Inventory %", 0.0, 100.0, 40.0, key="rec_override_inventory")
        with oc2:
            pace_vs_stly_pct = st.slider("Pace vs Last Year %", -30.0, 30.0, 0.0, key="rec_override_pace")
            pickup_last_7d = st.slider("Pickup (7d, rooms)", 0.0, 50.0, 5.0, key="rec_override_pickup")
            segment = st.selectbox("Guest Segment", options=SEGMENT_OPTIONS, key="rec_override_segment")
        with oc3:
            event_intensity = st.slider(
                "Event Intensity", 0.0, 1.0, 0.0, disabled=not event_flag, key="rec_override_event_intensity"
            )
            comp_set_avg_rate = st.number_input(
                "Comp Set Avg Rate ($)", min_value=0.0, value=200.0, key="rec_override_comp_rate"
            )

        context_overrides = {
            "occupancy_pct": occupancy_pct,
            "adr_trend_pct": adr_trend_pct,
            "remaining_inventory_pct": remaining_inventory_pct,
            "pace_vs_stly_pct": pace_vs_stly_pct,
            "pickup_last_7d": pickup_last_7d,
            "segment": segment,
            "event_flag": event_flag,
            "event_intensity": event_intensity if event_flag else 0.0,
            "comp_set_avg_rate": comp_set_avg_rate,
        }

    request_key = (
        property_id, room_type, rate_plan, str(start_date), str(end_date), los_nights,
        tuple(sorted(context_overrides.items())) if context_overrides else None,
    )

    if st.button("Generate recommendations", type="primary"):
        if end_date < start_date:
            st.error("End date must be on or after start date.")
        else:
            with st.spinner(f"Scoring {(end_date - start_date).days + 1} day(s)..."):
                results = get_recommendations(
                    property_id, room_type, rate_plan, str(start_date), str(end_date), los_nights,
                    context_overrides=context_overrides,
                )
            st.session_state["rec_last_key"] = request_key
            st.session_state["rec_last_results"] = results
            st.session_state["rec_last_overrides"] = context_overrides
            st.session_state["rec_actions"] = {}

    if st.session_state.get("rec_last_key") != request_key:
        st.info("Pick a property/room/rate/date range above and click **Generate recommendations**.")
        return

    results = st.session_state.get("rec_last_results") or []
    if not results:
        return

    actions = st.session_state.setdefault("rec_actions", {})

    if st.session_state.get("rec_last_overrides"):
        st.info("🔧 Showing recommendations generated WITH manual context overrides applied (see checkbox above).")

    st.subheader(f"Summary - {len(results)} day(s)")
    summary_df = pd.DataFrame(
        [
            {
                "stay_date": r["stay_date"],
                "arm": r["chosen_arm_label"],
                "offset": f"{r['chosen_arm_offset_pct'] * 100:+.1f}%",
                "price": r["published_price"],
                "confidence": r["confidence_label"],
                "requires_approval": r["requires_approval"],
                "status": actions.get(r["stay_date"], {}).get("status", "pending review"),
            }
            for r in results
        ]
    )
    st.dataframe(summary_df, use_container_width=True)

    approver = st.text_input("Approver name", value="revenue_manager", key="rec_approver")

    st.subheader("Day-by-day detail")
    for r in results:
        day = r["stay_date"]
        done = actions.get(day)
        label = (
            f"{day} | {r['chosen_arm_label']} ({r['chosen_arm_offset_pct'] * 100:+.1f}%) -> "
            f"${r['published_price']:.2f} [{r['confidence_label']}]"
        )
        if done:
            label += f"  —  {done['status']}"
        with st.expander(label):
            render_context_panel(r.get("context", {}), expanded=False)
            with st.expander("All arm probabilities"):
                st.bar_chart({a["label"]: a["probability"] for a in r["all_arms"]})
            if r["excluded_arms"]:
                with st.expander("Guardrail-excluded arms"):
                    st.json(r["excluded_arms"])

            if done:
                st.success(f"{done['status']} - decision_id `{done.get('decision_id', 'n/a')}`")
                continue

            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("✅ Approve", key=f"rec_approve_{day}"):
                    live = score(property_id, room_type, rate_plan, day, dry_run=False, los_nights=los_nights)
                    status = "Published (pending approval)" if live.get("requires_approval") else "Published (auto-published)"
                    actions[day] = {"status": status, "decision_id": live.get("decision_id")}
                    st.rerun()
            with c2:
                override_price = st.number_input(
                    "Modify price ($)", min_value=0.0, value=float(r["published_price"]), key=f"rec_price_{day}"
                )
                if st.button("✏️ Modify & Approve", key=f"rec_modify_{day}"):
                    live = score(property_id, room_type, rate_plan, day, dry_run=False, los_nights=los_nights)
                    override_decision(live["decision_id"], approver, override_price)
                    actions[day] = {"status": "Published (modified & approved)", "decision_id": live.get("decision_id")}
                    st.rerun()
            with c3:
                if st.button("🚫 Reject", key=f"rec_reject_{day}"):
                    actions[day] = {"status": "Rejected (not published)", "decision_id": None}
                    st.rerun()
