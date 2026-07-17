import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from config import DEFAULT_WEEKS
from data_fetcher import MarketDataError, get_market_data
from indicators import calculate_risk


st.set_page_config(
    page_title="台股融資風險儀表板 V2",
    page_icon="📊",
    layout="wide",
)


@st.cache_data(ttl=21_600, show_spinner=False)
def load_data(weeks: int) -> dict:
    return get_market_data(weeks)


def metric_delta(value: float, suffix: str = "%") -> str:
    return f"{value:+,.2f}{suffix}"


def normalized_indices(taiex: pd.DataFrame, tpex: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for frame, column, name in (
        (taiex, "taiex", "加權指數"),
        (tpex, "tpex", "櫃買指數"),
    ):
        if frame.empty:
            continue
        current = frame[["date", column]].dropna().copy()
        if current.empty or float(current.iloc[0][column]) == 0:
            continue
        current["標準化指數"] = current[column] / float(current.iloc[0][column]) * 100
        current["市場"] = name
        frames.append(current[["date", "標準化指數", "市場"]])
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


with st.sidebar:
    st.header("顯示設定")
    weeks = st.slider("觀察週數", min_value=8, max_value=52, value=DEFAULT_WEEKS)
    if st.button("立即重新整理", width="stretch"):
        st.cache_data.clear()
        st.rerun()
    st.caption("官方資料快取 6 小時，降低交易所端點負擔。")

st.title("📊 台股融資風險儀表板 V2")
st.caption("以證交所與櫃買中心公開資料，監測融資增幅、價跌資增與市場回落壓力。")

try:
    with st.spinner("正在讀取 TWSE／TPEx 官方資料…首次載入約需 20–60 秒"):
        data = load_data(weeks)
except (MarketDataError, ValueError) as exc:
    st.error(str(exc))
    st.info("請稍後按「立即重新整理」。若持續失敗，可能是官方資料服務維護中。")
    st.stop()

taiex = data["taiex"]
tpex = data["tpex"]
margin = data["margin"]
risk = calculate_risk(taiex, margin)

st.caption(f"儀表板更新時間：{data['update_time']}（Asia/Taipei）")
for warning in data["warnings"]:
    st.warning(warning)

latest_taiex = taiex.iloc[-1]
latest_tpex = tpex.iloc[-1] if not tpex.empty else None
latest_margin = margin.iloc[-1] if not margin.empty else None

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("融資風險", risk["level"], f"{risk['score']:.1f} / 100", delta_color="off")
with col2:
    if latest_margin is not None:
        st.metric(
            f"上市融資餘額（{latest_margin['date']:%m/%d}）",
            f"{latest_margin['margin_balance']:,.1f} 億",
            f"單日 {latest_margin['margin_daily_change']:+,.1f} 億",
            delta_color="inverse",
        )
    else:
        st.metric("上市融資餘額", "資料暫缺")
with col3:
    st.metric(
        f"加權指數（{latest_taiex['date']:%m/%d}）",
        f"{latest_taiex['taiex']:,.2f}",
        metric_delta(risk["daily_return"]),
    )
with col4:
    if latest_tpex is not None:
        tpex_previous = float(tpex.iloc[-2]["tpex"]) if len(tpex) > 1 else float(latest_tpex["tpex"])
        tpex_return = (float(latest_tpex["tpex"]) / tpex_previous - 1) * 100 if tpex_previous else 0
        st.metric(
            f"櫃買指數（{latest_tpex['date']:%m/%d}）",
            f"{latest_tpex['tpex']:,.2f}",
            metric_delta(tpex_return),
        )
    else:
        st.metric("櫃買指數", "資料暫缺")

st.progress(int(round(risk["score"])), text=f"風險壓力 {risk['score']:.1f} / 100")

left, right = st.columns([2, 1])
with left:
    st.subheader(f"近 {weeks} 週市場走勢")
    normalized = normalized_indices(taiex, tpex)
    if not normalized.empty:
        index_fig = px.line(
            normalized,
            x="date",
            y="標準化指數",
            color="市場",
            labels={"date": "日期"},
            color_discrete_map={"加權指數": "#2563eb", "櫃買指數": "#f97316"},
        )
        index_fig.add_hline(y=100, line_dash="dot", line_color="#94a3b8")
        index_fig.update_layout(
            hovermode="x unified",
            legend_title_text="",
            yaxis_title="期初＝100",
            margin=dict(l=10, r=10, t=10, b=10),
        )
        st.plotly_chart(index_fig, width="stretch")

with right:
    st.subheader("風險分數組成")
    component_data = pd.DataFrame(
        {"項目": list(risk["components"].keys()), "分數": list(risk["components"].values())}
    )
    component_fig = px.bar(
        component_data,
        x="分數",
        y="項目",
        orientation="h",
        range_x=[0, 30],
        color="分數",
        color_continuous_scale=["#22c55e", "#facc15", "#ef4444"],
    )
    component_fig.update_layout(
        coloraxis_showscale=False,
        margin=dict(l=10, r=10, t=10, b=10),
        yaxis_title="",
    )
    st.plotly_chart(component_fig, width="stretch")

st.subheader(f"近 {weeks} 週上市融資餘額")
if not margin.empty:
    margin_fig = go.Figure()
    margin_fig.add_trace(
        go.Scatter(
            x=margin["date"],
            y=margin["margin_balance"],
            mode="lines+markers",
            name="融資餘額",
            line=dict(color="#7c3aed", width=3),
            hovertemplate="%{x|%Y-%m-%d}<br>%{y:,.1f} 億<extra></extra>",
        )
    )
    margin_fig.update_layout(
        hovermode="x unified",
        yaxis_title="新台幣（億元）",
        xaxis_title="日期（每週最後交易日）",
        margin=dict(l=10, r=10, t=10, b=10),
    )
    st.plotly_chart(margin_fig, width="stretch")
else:
    st.info("目前沒有可顯示的融資餘額資料。")

summary1, summary2, summary3 = st.columns(3)
summary1.metric("融資餘額 4 週變化", metric_delta(risk["margin_change_4w"]))
summary2.metric("加權指數 4 週變化", metric_delta(risk["index_change_4w"]))
summary3.metric("距 12 週高點", metric_delta(risk["drawdown_12w"]))

with st.expander("風險分數怎麼算？"):
    st.markdown(
        """
        分數介於 0–100，由四項可觀測壓力相加：融資 4 週增幅（30 分）、
        指數下跌但融資增加的背離（25 分）、距 12 週高點的回落（30 分），
        以及最近一日跌幅（15 分）。此分數是市場監測指標，不是券商公布的
        個別帳戶融資維持率，也不是投資建議或報酬預測。

        資料來源：[臺灣證券交易所](https://www.twse.com.tw/)／
        [證券櫃檯買賣中心](https://www.tpex.org.tw/)
        """
    )
