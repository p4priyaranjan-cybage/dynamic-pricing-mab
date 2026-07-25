"""Shared 'why this recommendation' context panel - renders the full
decision context (as returned by the API alongside every score/rate-
calendar/approval-queue row) grouped into the categories a revenue manager
actually thinks in, instead of a flat list of raw feature names.

Used by scenario_simulator.py, rate_calendar.py, and approval_queue.py so
the same grouping/formatting logic isn't duplicated three times.
"""
from __future__ import annotations

import streamlit as st

# (group title with icon, [(context_key, display_label, format_spec), ...])
# format_spec is a str.format-style spec applied to the raw value; "s" for
# plain string/boolean values. Matches config/context_schema.yaml field-for-field.
CONTEXT_GROUPS: list[tuple[str, list[tuple[str, str, str]]]] = [
    (
        "📈 Occupancy & ADR Trends",
        [
            ("occupancy_pct", "Occupancy", "{:.1f}%"),
            ("adr_trend_pct", "ADR Trend", "{:+.1f}%"),
            ("remaining_inventory_pct", "Remaining Inventory", "{:.1f}%"),
        ],
    ),
    (
        "🎉 Events & Local Demand",
        [
            ("event_flag", "Local Event Active", "bool"),
            ("event_intensity", "Event Intensity", "{:.2f}"),
        ],
    ),
    (
        "📊 Booking Pace & Pickup",
        [
            ("pace_vs_stly_pct", "Pace vs Last Year", "{:+.1f}%"),
            ("pickup_last_7d", "Pickup (7d)", "{:.1f} rooms"),
            ("lead_time_days", "Lead Time", "{:.0f} days"),
        ],
    ),
    (
        "🏘️ Comp Set & Market View",
        [
            ("comp_set_avg_rate", "Comp Set Avg Rate", "${:.2f}"),
            ("our_rate_vs_compset_index", "Our Rate vs Comp Set", "{:.2f}x"),
            ("compset_rate_trend_pct", "Comp Set Trend", "{:+.1f}%"),
            ("compset_rank", "Our Rank in Comp Set", "#{:.0f}"),
            ("compset_dispersion", "Comp Set Dispersion", "{:.2f}"),
        ],
    ),
    (
        "👥 Segment & LOS Context",
        [
            ("segment", "Guest Segment", "s"),
            ("los_bucket", "Length of Stay", "s"),
            ("day_of_week", "Day of Week", "s"),
        ],
    ),
    (
        "🛏️ Room Type & Rate Plan",
        [
            ("room_type", "Room Type", "s"),
            ("rate_plan", "Rate Plan", "s"),
        ],
    ),
]


def _format_value(context: dict, key: str, fmt: str):
    if key not in context or context[key] is None:
        return "N/A"
    value = context[key]
    if fmt == "bool":
        return "Yes" if value else "No"
    if fmt == "s":
        return str(value).replace("_", " ").title()
    try:
        return fmt.format(value)
    except (ValueError, TypeError):
        return str(value)


def render_context_panel(context: dict, expanded: bool = True) -> None:
    """Renders `context` (the raw dict returned by the API - see
    config/context_schema.yaml for the full field list) grouped into the
    6 categories a revenue manager reasons in: Occupancy & ADR trends,
    Events & local demand, Booking pace/pickup, Comp set & market view,
    Segment & LOS context, Room Type & Rate Type."""
    if not context:
        st.caption("No context available for this decision.")
        return

    with st.expander("🔍 Why this recommendation? — Full context", expanded=expanded):
        for title, fields in CONTEXT_GROUPS:
            st.markdown(f"**{title}**")
            cols = st.columns(len(fields))
            for col, (key, label, fmt) in zip(cols, fields):
                col.metric(label, _format_value(context, key, fmt))
