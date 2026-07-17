import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import DEFAULT_WEEKS
from data_fetcher import MarketDataError, get_market_data
from indicators import build_risk_river, risk_level


st.set_page_config(
    page_title="台股風險河流圖 V3",
    page_icon="🌊",
    layout="wide",
)


RISK_BANDS = [
    (0, 20, "低風險", "rgba(34, 197, 94, 0.20)"),
    (20, 40, "偏低風險", "rgba(132, 204, 22, 0.18)"),
    (40, 60, "中等風險", "rgba(250, 204, 21, 0.20)"),
    (60, 80, "偏高風險", "rgba(249, 115, 22, 0.18)"),
    (80, 100, "極高風險", "rgba(239, 68, 68, 0.20)"),
]

SERIES_COLORS = {
    "上市風險": "#2563eb",
    "上櫃風險": "#f97316",
    "融資風險": "#7c3aed",
}


@st.cache_data(ttl=21_600, show_spinner=False)
def load_data(weeks: int) -> dict:
    return get_market_data(weeks)


def latest_risks(river: pd.DataFrame) -> dict[str, pd.Series]:
    return {
        name: group.sort_values("date").iloc[-1]
        for name, group in river.groupby("series")
        if not group.empty
    }


def risk_river_figure(river: pd.DataFrame) -> go.Figure:
    figure = go.Figure()
    for lower, upper, label, color in RISK_BANDS:
        figure.add_hrect(
            y0=lower,
            y1=upper,
            fillcolor=color,
            line_width=0,
            layer="below",
            annotation_text=label,
            annotation_position="right",
            annotation_font_size=11,
        )

    for name, group in river.groupby("series"):
        group = group.sort_values("date")
        unit = "億元" if name == "融資風險" else "點"
        figure.add_trace(
            go.Scatter(
                x=group["date"],
                y=group["risk"],
                customdata=group[["raw_value"]],
                mode="lines+markers",
                name=name,
                line=dict(color=SERIES_COLORS[name], width=3),
                marker=dict(size=6),
                hovertemplate=(
                    "%{x|%Y-%m-%d}<br>風險位階：%{y:.1f}<br>"
                    f"原始數值：%{{customdata[0]:,.2f}} {unit}<extra>{name}</extra>"
                ),
            )
        )

    for boundary in (20, 40, 60, 80):
        figure.add_hline(y=boundary, line_width=1, line_dash="dot", line_color="rgba(100,116,139,.45)")

    figure.update_layout(
        height=570,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=10, r=75, t=45, b=10),
        xaxis_title="每週最後交易日",
        yaxis=dict(title="剩餘風險位階", range=[0, 100], dtick=20),
    )
    return figure


with st.sidebar:
    st.header("顯示設定")
    weeks = st.slider("觀察週數", min_value=20, max_value=52, value=DEFAULT_WEEKS)
    if st.button("立即重新整理", width="stretch"):
        st.cache_data.clear()
        st.rerun()
    st.caption("官方資料快取 6 小時；全程使用免費公開資料。")

st.title("🌊 台股風險河流圖 V3")
st.caption("三條線位於同一個 0–100 剩餘風險尺度；顏色代表五個風險區間。")

try:
    with st.spinner("正在讀取 TWSE／TPEx 官方資料…首次載入約需 20–60 秒"):
        data = load_data(weeks)
except (MarketDataError, ValueError) as exc:
    st.error(str(exc))
    st.info("請稍後按「立即重新整理」。若持續失敗，可能是官方資料服務維護中。")
    st.stop()

for warning in data["warnings"]:
    st.warning(warning)

river = build_risk_river(data["taiex"], data["tpex"], data["margin"])
current = latest_risks(river)

metric_columns = st.columns(3)
for column, name in zip(metric_columns, ("上市風險", "上櫃風險", "融資風險")):
    with column:
        if name in current:
            score = float(current[name]["risk"])
            raw = float(current[name]["raw_value"])
            unit = "億元" if name == "融資風險" else "點"
            st.metric(name, f"{score:.1f} / 100", f"{raw:,.1f} {unit}", delta_color="off")
            st.caption(risk_level(score))
        else:
            st.metric(name, "資料暫缺")

st.plotly_chart(risk_river_figure(river), width="stretch")
st.caption(f"更新時間：{data['update_time']}（Asia/Taipei）")

with st.expander("怎麼解讀大跌後的風險？", expanded=True):
    st.markdown(
        """
        - **上市／上櫃線**衡量的是剩餘過熱與震盪風險。大跌會降低價格相對均線的延伸與中期漲幅，
          因此過熱風險下降；但短期波動率會升高，所以不會立刻掉到最低風險。
        - **融資線**衡量槓桿擁擠程度。只有融資餘額實際下降，才代表籌碼清洗獲得確認。
        - 如果指數線快速下降、融資線仍停在紅色區，代表價格已修正但槓桿尚未明顯退出，仍需留意續跌風險。
        - 三條線一起下降，才比較接近「巨大賣壓後，剩餘風險確實降低」的狀態。
        """
    )

with st.expander("計算方法與限制"):
    st.markdown(
        """
        上市與上櫃風險由「相對 20 週均線的延伸、12 週動能、近 4 週波動率」組成；
        融資風險由「26 週餘額位階、4 週增幅、價跌資增背離」組成。所有序列轉換為 0–100，
        只用來比較風險位階，不代表未來報酬機率，也不是投資建議。

        資料來源：[臺灣證券交易所](https://www.twse.com.tw/)／
        [證券櫃檯買賣中心](https://www.tpex.org.tw/)
        """
    )
