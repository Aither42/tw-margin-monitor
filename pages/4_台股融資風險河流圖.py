import streamlit as st
from navigation import show_navigation
from margin_monitor.view import render_margin_monitor

st.set_page_config(page_title='台股融資風險河流圖｜軋軋 V4.14',page_icon='🌊',layout='wide')
show_navigation()
render_margin_monitor()
