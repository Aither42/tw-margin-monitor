from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ai_monitor.config import PILLARS, TAIWAN_WATCHLIST
from ai_monitor.engine import run_monitor
from ai_monitor.market import fetch_ticker_metrics
from ai_monitor.scoring import risk_band

st.set_page_config(page_title="AI Overheat Monitor", page_icon="🌡️", layout="wide")

ROOT = Path(__file__).resolve().parents[1]
HISTORY_FILE = ROOT / "data" / "ai_overheat" / "history.csv"

from navigation import show_navigation

st.title("🌡️ AI Overheat Monitor")
show_navigation()
st.caption("全球 AI 供需、Capex、HBM/CoWoS、光通訊、電力建設、融資壓力與市場狂熱的整合偵測器")

with st.sidebar:
    st.header("掃描設定")
    days = st.select_slider("新聞觀察窗", options=[7, 14, 30, 45, 60], value=30, format_func=lambda x: f"{x} 天")
    max_items = st.slider("每個查詢最多文章", 5, 25, 12)
    fetch_market = st.toggle("抓取市場價格資料", value=True)
    st.caption("新聞採 Google News RSS；價格採 Yahoo Finance。無須 API Key。")

    refresh = st.button("🔄 重新掃描", type="primary", use_container_width=True)


@st.cache_data(ttl=1800, show_spinner=False)
def cached_monitor(days: int, max_items: int, fetch_market: bool):
    return run_monitor(days=days, max_items_per_query=max_items, fetch_market=fetch_market)


@st.cache_data(ttl=1800, show_spinner=False)
def cached_tw_market():
    return fetch_ticker_metrics(TAIWAN_WATCHLIST)


if refresh:
    cached_monitor.clear()
    cached_tw_market.clear()

with st.spinner("正在掃描全球 AI 供需訊號…"):
    result = cached_monitor(days, max_items, fetch_market)

if not any(result["pillar_counts"].values()):
    st.warning("本次未取得有效新聞或行情，以下分數為模型預設值，不能視為本次風險判定。請稍後重新掃描。")

score = result["score"]
band = result["band"]
active_flags = [f for f in result["hard_flags"] if f["active"]]

c1, c2, c3, c4 = st.columns(4)
c1.metric("AI 過熱分數", f"{score:.0f} / 100")
c2.metric("風險狀態", band)
c3.metric("硬紅旗", f"{len(active_flags)} / 6")
mean_conf = pd.Series(result["pillar_confidence"]).mean()
c4.metric("資料信心", f"{mean_conf:.0f}%")

fig = go.Figure(
    go.Indicator(
        mode="gauge+number",
        value=score,
        number={"suffix": "/100"},
        title={"text": "AI Overheat Risk"},
        gauge={
            "axis": {"range": [0, 100]},
            "steps": [
                {"range": [0, 30], "color": "#d9f2e6"},
                {"range": [30, 45], "color": "#eef3c8"},
                {"range": [45, 60], "color": "#fff0b3"},
                {"range": [60, 75], "color": "#ffd0a8"},
                {"range": [75, 100], "color": "#ffc2c2"},
            ],
            "threshold": {"line": {"color": "black", "width": 4}, "thickness": 0.8, "value": score},
        },
    )
)
fig.update_layout(height=330, margin=dict(l=30, r=30, t=55, b=20))
st.plotly_chart(fig, use_container_width=True)

st.info(
    "判讀原則：缺貨與需求強勁本身不是過熱；真正危險是產能/Capex 持續增加，但訂單、價格、利用率、毛利或現金回收開始轉弱。"
)

tab1, tab2, tab3, tab4, tab5 = st.tabs(["總覽", "硬紅旗", "新聞訊號", "台灣地震儀", "方法與歷史"])

with tab1:
    rows = []
    for key, cfg in PILLARS.items():
        rows.append(
            {
                "指標": cfg["name"],
                "權重": f"{cfg['weight']*100:.0f}%",
                "風險分數": round(result["pillar_scores"].get(key, 35.0), 1),
                "狀態": risk_band(result["pillar_scores"].get(key, 35.0)),
                "資料信心": f"{result['pillar_confidence'].get(key, 0):.0f}%",
                "樣本數": result["pillar_counts"].get(key, 0),
                "觀察重點": cfg["description"],
            }
        )
    pillar_df = pd.DataFrame(rows)
    st.dataframe(pillar_df, use_container_width=True, hide_index=True)

    bar = go.Figure(
        go.Bar(
            x=pillar_df["風險分數"],
            y=pillar_df["指標"],
            orientation="h",
            text=pillar_df["風險分數"],
            textposition="auto",
        )
    )
    bar.update_layout(xaxis_title="過熱風險分數", xaxis_range=[0, 100], height=430, margin=dict(l=20, r=20, t=20, b=30))
    st.plotly_chart(bar, use_container_width=True)

    if not result["market"].empty:
        st.subheader("市場狂熱代理指標")
        market_view = result["market"].copy()
        market_view = market_view.rename(
            columns={
                "ticker": "Ticker",
                "name": "公司/指數",
                "price": "價格",
                "return_20d_pct": "20日報酬%",
                "return_60d_pct": "60日報酬%",
                "dist_52w_high_pct": "距52週高點%",
                "above_ma50": "高於MA50",
                "rsi14": "RSI14",
            }
        )
        st.dataframe(market_view.round(2), use_container_width=True, hide_index=True)

with tab2:
    st.subheader("六個硬性紅旗")
    st.caption("若同時出現 ≥3 個，總分至少拉到橘燈；≥5 個則至少紅燈。")
    for flag in result["hard_flags"]:
        icon = "🔴" if flag["active"] else "⚪"
        with st.expander(f"{icon} {flag['name']} — 命中 {flag['count']} / 門檻 {flag['threshold']}"):
            if flag["headlines"]:
                for h in flag["headlines"]:
                    st.write("•", h)
            else:
                st.write("目前未抓到足以觸發的可信訊號。")

with tab3:
    st.subheader("新聞訊號")
    news = result["news"].copy()
    if news.empty:
        st.warning("本次沒有抓到新聞資料。")
    else:
        news["published"] = pd.to_datetime(news["published"], utc=True, errors="coerce")
        name_map = {k: v["name"] for k, v in PILLARS.items()}
        news["pillar_name"] = news["pillar"].map(name_map)
        cols = ["published", "pillar_name", "source", "title", "risk_score", "evidence", "link"]
        view = news[cols].rename(
            columns={
                "published": "時間",
                "pillar_name": "雷達",
                "source": "來源",
                "title": "標題",
                "risk_score": "文章風險分數",
                "evidence": "判定理由",
                "link": "連結",
            }
        )
        radar_options = ["全部"] + sorted(view["雷達"].dropna().unique().tolist())
        selected = st.selectbox("篩選雷達", radar_options)
        if selected != "全部":
            view = view[view["雷達"] == selected]
        view = view.sort_values(["文章風險分數", "時間"], ascending=[False, False])
        st.dataframe(
            view,
            use_container_width=True,
            hide_index=True,
            column_config={
                "連結": st.column_config.LinkColumn("連結", display_text="開啟"),
                "文章風險分數": st.column_config.ProgressColumn("文章風險分數", min_value=0, max_value=100),
            },
        )

with tab4:
    st.subheader("台灣 AI 供應鏈地震儀")
    st.caption("目的不是用股價直接判定產業過熱，而是觀察台灣供應鏈是否比美國客戶法說更早出現轉折。")
    with st.spinner("抓取台灣供應鏈價格資料…"):
        tw = cached_tw_market()
    if tw.empty:
        st.warning("目前無法取得台股市場資料。")
    else:
        tw_view = tw.rename(
            columns={
                "ticker": "Ticker",
                "name": "公司",
                "price": "價格",
                "return_20d_pct": "20日報酬%",
                "return_60d_pct": "60日報酬%",
                "dist_52w_high_pct": "距52週高點%",
                "above_ma50": "高於MA50",
                "rsi14": "RSI14",
            }
        )
        st.dataframe(tw_view.round(2), use_container_width=True, hide_index=True)
        st.caption("下一版可再接入台灣每月營收資料，形成『基本面地震儀』；目前版本先用市場價格作高頻代理。")

with tab5:
    st.subheader("評分框架")
    method_df = pd.DataFrame(
        [
            {"區間": "0–29", "狀態": "🟢 健康擴張", "解讀": "需求強、供給仍偏緊"},
            {"區間": "30–44", "狀態": "🟢🟡 升溫", "解讀": "Capex 大，但多數仍能被需求吸收"},
            {"區間": "45–59", "狀態": "🟡 過熱初期", "解讀": "部分供應鏈開始鬆動"},
            {"區間": "60–74", "狀態": "🟠 高風險", "解讀": "供給追上需求，獲利預期可能見頂"},
            {"區間": "75–100", "狀態": "🔴 週期反轉", "解讀": "砍單/降價/庫存/Capex 下修同時出現"},
        ]
    )
    st.dataframe(method_df, use_container_width=True, hide_index=True)

    st.markdown(
        """
**證據分級**
- A：公司財報、法說、官方公告。
- B：Reuters / Bloomberg / FT / WSJ / TrendForce 等可信產業調查。
- C：券商傳聞、供應鏈消息、社群與短影音。

目前 MVP 以「來源權重 + 關鍵詞 + 新聞時效 + 市場價格」計分。這不是語意模型，也不應取代人工閱讀原文；它的任務是把值得注意的轉折先篩出來。
        """
    )

    if HISTORY_FILE.exists():
        try:
            hist = pd.read_csv(HISTORY_FILE)
            if not hist.empty:
                hist["timestamp"] = pd.to_datetime(hist["timestamp"], errors="coerce")
                st.subheader("歷史分數")
                st.line_chart(hist.set_index("timestamp")["score"])
                st.dataframe(hist.tail(30), use_container_width=True, hide_index=True)
        except Exception as exc:
            st.warning(f"讀取歷史資料失敗：{exc}")
    else:
        st.caption("尚未建立 data/ai_overheat/history.csv。可執行 scripts/ai_daily_snapshot.py 產生第一筆。")

st.divider()
st.caption("此工具為研究與風險監控用途，不構成投資建議。新聞分類採規則式自動判讀，重大訊號請回到原始來源確認。")
