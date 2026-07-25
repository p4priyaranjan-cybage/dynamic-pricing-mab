"""Approval Queue tab: pending_approval decisions with approve/reject/
override actions (routes through the /approval-queue/{id}/... endpoints).
Each row expands to show the full decision context (occupancy/ADR, events,
pace/pickup, comp set, segment/LOS, room & rate type) so a reviewer can see
*why* the price was recommended, not just the number."""
from __future__ import annotations

import streamlit as st

from dashboard.api_client import approve_decision, get_approval_queue, override_decision, reject_decision
from dashboard.context_panel import render_context_panel


def render():
    st.header("✅ Approval Queue")
    rows = get_approval_queue()
    if not rows:
        st.success("No pending approvals.")
        return

    st.caption(f"{len(rows)} decision(s) awaiting review - expand a row to see the context behind the recommendation.")
    approver = st.text_input("Approver name", value="revenue_manager")
    for row in rows:
        with st.expander(
            f"{row['property_id']} | {row['room_type']}/{row['rate_plan']} | {row['stay_date']} | "
            f"{row['arm_label']} ({row['arm_offset_pct']*100:+.1f}%) -> ${row['published_price']:.2f} "
            f"[{row['confidence_label']}]"
        ):
            render_context_panel(row.get("context", {}), expanded=False)
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                if st.button("Approve", key=f"approve_{row['decision_id']}"):
                    approve_decision(row["decision_id"], approver)
                    st.rerun()
            with c2:
                if st.button("Reject", key=f"reject_{row['decision_id']}"):
                    reject_decision(row["decision_id"], approver)
                    st.rerun()
            with c3:
                override_price = st.number_input("Override price", value=row["published_price"], key=f"price_{row['decision_id']}")
            with c4:
                if st.button("Override & Approve", key=f"override_{row['decision_id']}"):
                    override_decision(row["decision_id"], approver, override_price)
                    st.rerun()
