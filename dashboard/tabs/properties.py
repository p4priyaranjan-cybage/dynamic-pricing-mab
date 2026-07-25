"""Properties tab: fleet inventory browser (chain/brand/region/cluster)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.api_client import get_properties


def render():
    st.header("🏨 Properties")
    properties = get_properties()
    df = pd.DataFrame(properties)
    st.dataframe(df, use_container_width=True)

    st.subheader("Fleet composition")
    col1, col2 = st.columns(2)
    with col1:
        st.bar_chart(df.groupby("chain").size())
    with col2:
        st.bar_chart(df.groupby("cluster_id").size())
