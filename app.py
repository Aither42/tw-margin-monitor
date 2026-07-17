import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import DEFAULT_WEEKS
from data_fetcher import MarketDataError, get_market_data
from indicators import build_risk_river, risk_level


st.set_page_config(
    page_title="台股量價風險河流圖 V4",
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
        if name == "融資風險":
            customdata = group[["raw_value"]]
            hovertemplate = (
                "%{x|%Y-%m-%d}<br>風險位階：%{y:.1f}<br>"
                f"原始數值：%{{customdata[0]:,.2f}} {unit}<extra>{name}</extra>"
            )
        else:
            customdata = group[
                ["raw_value", "weekly_return", "volume_ratio", "ma30", "ma5", "volume_signal"]
            ]
            hovertemplate = (
                "%{x|%Y-%m-%d}<br>風險位階：%{y:.1f}<br>"
                "指數：%{customdata[0]:,.2f} 點<br>週漲跌：%{customdata[1]:+.2%}<br>"
                "成交量倍數：%{customdata[2]:.2f}x<br>30週線：%{customdata[3]:,.2f}<br>"
                "5週線：%{customdata[4]:,.2f}<br>量價訊號：%{customdata[5]}"
                f"<extra>{name}</extra>"
            )
        figure.add_trace(
            go.Scatter(
                x=group["date"],
                y=group["risk"],
                customdata=customdata,
                mode="lines+markers",
                name=name,
                line=dict(color=SERIES_COLORS[name], width=3),
                marker=dict(size=6),
                hovertemplate=hovertemplate,
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


def volume_price_figure(river: pd.DataFrame) -> go.Figure:
    figure = go.Figure()
    market = river[river["series"].isin(["上市風險", "上櫃風險"])].dropna(
        subset=["weekly_return", "volume_ratio"]
    )
    for name, group in market.groupby("series"):
        group = group.sort_values("date").tail(16)
        figure.add_trace(
            go.Scatter(
                x=group["weekly_return"] * 100,
                y=group["volume_ratio"],
                customdata=group[["date", "risk", "volume_signal"]],
                mode="markers+lines",
                name=name,
                line=dict(color=SERIES_COLORS[name], width=1),
                marker=dict(
                    color=SERIES_COLORS[name],
                    size=[11 if index == len(group) - 1 else 7 for index in range(len(group))],
                ),
                hovertemplate=(
                    "%{customdata[0]|%Y-%m-%d}<br>週漲跌：%{x:+.2f}%<br>"
                    "成交量倍數：%{y:.2f}x<br>風險：%{customdata[1]:.1f}<br>"
                    "訊號：%{customdata[2]}<extra>%{fullData.name}</extra>"
                ),
            )
        )
    figure.add_vline(x=0, line_dash="dot", line_color="rgba(100,116,139,.55)")
    figure.add_hline(y=1, line_dash="dot", line_color="rgba(100,116,139,.55)")
    figure.add_annotation(x=-0.02, y=1.02, xref="paper", yref="paper", text="量增下跌", showarrow=False)
    figure.add_annotation(x=1.02, y=1.02, xref="paper", yref="paper", text="量價齊揚", showarrow=False)
    figure.add_annotation(x=-0.02, y=-0.08, xref="paper", yref="paper", text="量縮下跌", showarrow=False)
    figure.add_annotation(x=1.02, y=-0.08, xref="paper", yref="paper", text="量縮上漲", showarrow=False)
    figure.update_layout(
        height=440,
        hovermode="closest",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=10, r=10, t=45, b=10),
        xaxis_title="每週漲跌（%）",
        yaxis_title="平均日成交量／前10週平均",
    )
    return figure


with st.sidebar:
    st.header("顯示設定")
    weeks = st.slider("觀察週數", min_value=30, max_value=52, value=DEFAULT_WEEKS)
    if st.button("立即重新整理", width="stretch"):
        st.cache_data.clear()
        st.rerun()
    st.caption("官方資料快取 6 小時；全程使用免費公開資料。")

st.title("🌊 台股量價風險河流圖 V4")
st.caption("30 週線判斷中期支撐與乖離，成交量確認漲跌品質；高風險時由 5 週線快速示警。")

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
            if name == "融資風險":
                st.caption(risk_level(score))
            else:
                st.caption(f"{risk_level(score)}｜{current[name]['volume_signal']}")
        else:
            st.metric(name, "資料暫缺")

st.plotly_chart(risk_river_figure(river), width="stretch")
st.caption(f"更新時間：{data['update_time']}（Asia/Taipei）")

st.subheader("上市／上櫃量價關係")
st.plotly_chart(volume_price_figure(river), width="stretch")

market_latest = {name: row for name, row in current.items() if name != "融資風險"}
if market_latest:
    diagnostics = st.columns(len(market_latest))
    for column, (name, row) in zip(diagnostics, market_latest.items()):
        with column:
            divergence = float(row["ma30_divergence"]) * 100
            ma5_state = "站上" if float(row["raw_value"]) >= float(row["ma5"]) else "跌破"
            st.markdown(f"**{name}量價診斷**")
            st.write(f"30週乖離：`{divergence:+.2f}%`")
            st.write(f"5週線：`{ma5_state}`")
            st.write(f"成交量：`{float(row['volume_ratio']):.2f}x`")

with st.expander("V4 風險邏輯", expanded=True):
    st.markdown(
        """
        - **30 週線是中心**：正乖離過大代表過熱；跌破且負乖離擴大代表中期支撐受損，兩端都會提高風險。
        - **成交量確認漲跌**：量增下跌提高賣壓風險；量縮上漲視為反彈品質不足；量縮下跌代表賣壓可能收斂。
        - **5 週線只在高風險啟動**：高風險時跌破 5 週線會追加警報，重新站回則降低部分短線風險。
        - **融資線**衡量槓桿擁擠程度。只有融資餘額實際下降，才代表籌碼清洗獲得確認。
        """
    )

with st.expander("計算方法與限制"):
    st.markdown(
        """
        上市與上櫃風險由「30 週乖離／跌破、每週漲跌與成交量倍數、5 週線高風險觸發」組成；
        融資風險由「26 週餘額位階、4 週增幅、價跌資增背離」組成。所有序列轉換為 0–100，
        只用來比較風險位階，不代表未來報酬機率，也不是投資建議。

        資料來源：[臺灣證券交易所](https://www.twse.com.tw/)／
        [證券櫃檯買賣中心](https://www.tpex.org.tw/)
        """
    )
