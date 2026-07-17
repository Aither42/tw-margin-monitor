import streamlit as st
from data_fetcher import get_market_data
from indicators import risk_level

st.set_page_config(
    page_title="台股融資斷頭儀表板",
    page_icon="📈",
    layout="wide"
)

data = get_market_data()

st.title("📈 台股融資斷頭儀表板")
st.caption(f"更新時間：{data['update_time']}")

st.divider()

col1, col2, col3 = st.columns(3)

with col1:
    st.metric("融資維持率", f"{data['maintenance']}%")

with col2:
    st.metric("融資餘額", f"{data['margin_balance']} 億")

with col3:
    st.metric("斷頭溫度", f"{data['temperature']} / 10")

st.progress(data["temperature"] / 10)

st.subheader(risk_level(data["temperature"]))

st.metric("今日融資增減", f"{data['margin_change']} 億")

st.info("下一版開始串接台灣證交所公開資料。")