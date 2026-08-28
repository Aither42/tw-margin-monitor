from __future__ import annotations

import streamlit as st

st.set_page_config(
    page_title="軋軋台股決策助手 V4.11",
    page_icon="🐾",
    layout="wide",
)

pages = [
    st.Page(
        "pages/1_個股分析.py",
        title="軋軋個股分析",
        icon="🐾",
        default=True,
    ),
    st.Page(
        "pages/2_每日低風險清單.py",
        title="每日低風險清單",
        icon="📋",
    ),
]

nav = st.navigation(pages, position="sidebar")
nav.run()
