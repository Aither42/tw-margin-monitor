from __future__ import annotations

import streamlit as st


def show_navigation():
    cols = st.columns(3)
    with cols[0]:
        st.page_link("app.py", label="軋軋個股分析", icon="🐾", use_container_width=True)
    with cols[1]:
        st.page_link("pages/2_每日低風險清單.py", label="每日低風險清單", icon="📋", use_container_width=True)
    with cols[2]:
        st.page_link("pages/3_AI_Overheat_Monitor.py", label="AI Overheat Monitor", icon="🌡️", use_container_width=True)

