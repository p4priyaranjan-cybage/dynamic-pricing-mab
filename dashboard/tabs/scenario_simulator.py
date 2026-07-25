"""Scenario Simulator tab: side-effect-free "what-if" scoring - calls
/simulate (dry_run=True) by default, never writes a Decision row, never
affects training. Lets a revenue manager explore how the bandit would
price a given property/room_type/rate_plan/date combination, see the full
context (occupancy/ADR, events, pace/pickup, comp set, segment/LOS, room &
rate type) that drove it, manually nudge individual context signals to see
how the price reacts, and optionally publish a real (live, persisted)
decision when they're ready."""
from __future__ import annotations

import datetime as dt

import streamlit as st

from dashboard.api_client import get_properties, get_property_config, score
from dashboard.context_panel import render_context_panel

SEGMENT_OPTIONS = ["transient", "corporate", "group", "leisure"]


def _render_result(result: dict, key_prefix: str) -> None:
    st.divider()
    m1, m2, m3 = st.columns(3)
    m1.metric("Recommended price", f"${result['published_price']:.2f}",
               delta=f"{result['chosen_arm_offset_pct']*100:+.1f}% vs reference")
    m2.metric("Reference rate", f"${result['reference_rate']:.2f}")
    m3.metric("Confidence", f"{result['confidence_label']} ({result['confidence_score']:.2f})")
    st.write(f"Chosen arm: **{result['chosen_arm_label']}**")

    render_context_panel(result.get("context", {}), expanded=True)

    with st.expander(f"All arm probabilities ({key_prefix})"):
        st.bar_chart({a["label"]: a["probability"] for a in result["all_arms"]})
    if result["excluded_arms"]:
        with st.expander("Guardrail-excluded arms"):
            st.json(result["excluded_arms"])


def render():
    st.header("🧪 Scenario Simulator")
    st.caption(
        "Pick a property, room type, rate plan and stay date, then click **Simulate price** to see the "
        "recommended price plus the full context that drove it. Side-effect-free by default - it only "
        "logs a real decision if you explicitly click **Publish as live decision** below."
    )

    properties = get_properties()
    prop_options = {p["property_id"]: f"{p['name']} ({p['property_id']})" for p in properties}

    col1, col2, col3 = st.columns(3)
    with col1:
        property_id = st.selectbox("Property", options=list(prop_options), format_func=lambda x: prop_options[x])

    config = get_property_config(property_id)
    room_type_options = config.get("room_types") or ["standard"]
    rate_plan_options = config.get("rate_plans") or ["bar_flexible"]
    with col2:
        room_type = st.selectbox("Room type", options=room_type_options)
    with col3:
        rate_plan = st.selectbox("Rate plan", options=rate_plan_options)

    col4, col5 = st.columns(2)
    with col4:
        stay_date = st.date_input("Stay date", value=dt.date.today() + dt.timedelta(days=30))
    with col5:
        los_nights = st.number_input("Length of stay (nights)", min_value=1, max_value=14, value=2)

    request_key = (property_id, room_type, rate_plan, str(stay_date), los_nights)

    if st.button("Simulate price", type="primary"):
        result = score(property_id, room_type, rate_plan, str(stay_date), dry_run=True, los_nights=los_nights)
        st.session_state["sim_last_request_key"] = request_key
        st.session_state["sim_last_result"] = result

    # Only show results (and the what-if / publish tools below) if they match
    # the CURRENT form inputs - changing property/room/date invalidates them.
    has_result = st.session_state.get("sim_last_request_key") == request_key
    if not has_result:
        return

    result = st.session_state["sim_last_result"]
    _render_result(result, key_prefix="base")

    base_context = result.get("context", {})
    st.subheader("🔧 What-if: manually adjust context and re-simulate")
    st.caption(
        "Nudge individual demand signals below (e.g. flip on an event, raise/lower occupancy) and "
        "re-simulate to see how the recommended price reacts - still side-effect-free."
    )
    # Deliberately OUTSIDE st.form: widgets inside a form don't trigger a
    # rerun until submit, so a disabled=not event_flag slider inside the
    # form would never react live to the checkbox - it has to live outside
    # so toggling it reruns the script immediately and updates the slider
    # below before the form is submitted.
    event_flag = st.checkbox(
        "Local Event Active", value=bool(base_context.get("event_flag", False)), key="whatif_event_flag"
    )

    with st.form(key="whatif_form"):
        c1, c2, c3 = st.columns(3)
        with c1:
            occupancy_pct = st.slider("Occupancy %", 0.0, 100.0, float(base_context.get("occupancy_pct", 55.0)))
            adr_trend_pct = st.slider("ADR Trend %", -20.0, 20.0, float(base_context.get("adr_trend_pct", 0.0)))
            remaining_inventory_pct = st.slider(
                "Remaining Inventory %", 0.0, 100.0, float(base_context.get("remaining_inventory_pct", 40.0))
            )
        with c2:
            pace_vs_stly_pct = st.slider("Pace vs Last Year %", -30.0, 30.0, float(base_context.get("pace_vs_stly_pct", 0.0)))
            pickup_last_7d = st.slider("Pickup (7d, rooms)", 0.0, 50.0, float(base_context.get("pickup_last_7d", 5.0)))
            segment = st.selectbox(
                "Guest Segment", options=SEGMENT_OPTIONS,
                index=SEGMENT_OPTIONS.index(base_context.get("segment", "transient"))
                if base_context.get("segment") in SEGMENT_OPTIONS else 0,
            )
        with c3:
            event_intensity = st.slider(
                "Event Intensity", 0.0, 1.0, float(base_context.get("event_intensity", 0.0) or 0.0), disabled=not event_flag
            )
            comp_set_avg_rate = st.number_input(
                "Comp Set Avg Rate ($)", min_value=0.0, value=float(base_context.get("comp_set_avg_rate", 200.0))
            )

        submitted = st.form_submit_button("Re-simulate with these overrides", type="primary")

    if submitted:
        overrides = {
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
        whatif_result = score(
            property_id, room_type, rate_plan, str(stay_date), dry_run=True, los_nights=los_nights,
            context_overrides=overrides,
        )
        st.session_state["sim_whatif_result"] = whatif_result

    if "sim_whatif_result" in st.session_state:
        st.markdown("#### Result with manual overrides")
        _render_result(st.session_state["sim_whatif_result"], key_prefix="whatif")

    st.divider()
    st.subheader("📤 Publish as live decision")
    st.warning(
        "This writes a REAL decision to the database (status `pending_approval` or `auto_published`) and "
        "will show up in the Rate Calendar / Approval Queue - unlike everything above, it is **not** "
        "side-effect-free.",
        icon="⚠️",
    )
    if st.button("Publish as live decision"):
        live_result = score(property_id, room_type, rate_plan, str(stay_date), dry_run=False, los_nights=los_nights)
        st.success(f"Published - decision_id `{live_result['decision_id']}`, status visible in Approval Queue / Rate Calendar.")
        _render_result(live_result, key_prefix="live")
