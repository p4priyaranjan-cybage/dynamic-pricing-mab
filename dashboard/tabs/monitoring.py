"""Monitoring tab: arm distribution, override rate, approval stats, average
confidence - fleet-wide or filtered by cluster/tenant."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.api_client import get_metrics, get_properties


def render():
    st.header("📊 Monitoring")
    properties = get_properties()
    clusters = sorted({p["cluster_id"] for p in properties})
    tenants = sorted({p["tenant_id"] for p in properties})

    col1, col2 = st.columns(2)
    with col1:
        cluster_id = st.selectbox("Cluster", options=[None] + clusters)
    with col2:
        tenant_id = st.selectbox("Tenant", options=[None] + tenants)

    metrics = get_metrics(cluster_id=cluster_id, tenant_id=tenant_id)

    c1, c2 = st.columns(2)
    c1.metric("Average confidence", f"{metrics['average_confidence']:.2f}")
    c2.metric("Override rate", f"{metrics['override_rate']*100:.1f}%")

    st.subheader("Arm distribution")
    dist = metrics["arm_distribution"]
    if dist:
        st.bar_chart(pd.Series(dist))
    else:
        st.info("No live decisions logged yet.")

    st.subheader("Approval status breakdown")
    st.json(metrics["approval_stats"])
