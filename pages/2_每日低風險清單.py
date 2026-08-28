from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from gaga_scanner import (
    add_transition_labels,
    confirm_candidate,
    latest_saved_low_risk,
    load_history,
    load_taiwan_stock_universe,
    quick_screen_universe,
    save_history,
)

APP_DIR = Path(__file__).resolve().parents[1]

st.title("📋 每日軋軋低風險清單")
st.caption(
    "兩階段掃描：先用 Yahoo Finance 做技術初篩，再只對候選股跑完整 V4.10 "
    "低風險區模型（MA13 / 40 / 63 / 150 / 1000＋估值＋月營收）。"
)

st.info(
    "這一頁是 V4.11 試行版。第一次掃描只能標記「首次確認」；"
    "從第二個不同交易日開始，才會出現真正的「🆕 今日新進低風險區」。"
)

with st.sidebar:
    st.subheader("每日掃描設定")
    token = st.text_input(
        "FinMind Token（選填）",
        type="password",
        key="finmind_token",
    )
    markets = st.multiselect(
        "市場",
        ["上市", "上櫃"],
        default=["上市", "上櫃"],
    )
    max_choice = st.selectbox(
        "最多掃描檔數",
        ["100（快速測試）", "300（建議先用）", "600", "全部"],
        index=1,
    )
    confirm_n = st.slider(
        "第二階段完整確認檔數",
        min_value=10,
        max_value=60,
        value=25,
        step=5,
        help="FinMind 月營收大致會對每一檔完整確認股送出 1 次 request。",
    )
    industry_filter = st.selectbox(
        "產業",
        ["全部產業"],
        index=0,
        disabled=True,
        help="載入股票清單後，主畫面可再選產業。",
    )

# Show latest saved result before running a new scan.
saved_date, saved_low = latest_saved_low_risk(APP_DIR)
if saved_date:
    st.subheader(f"最近一次已儲存清單｜行情日 {saved_date}")
    if saved_low.empty:
        st.caption("最近一次完整確認結果中，沒有股票落在低風險承接區。")
    else:
        preview = saved_low.copy()
        preview["低風險區"] = preview.apply(
            lambda r: f"{r['safe_low']:.2f}～{r['safe_high']:.2f}", axis=1
        )
        preview["營收 YoY"] = preview["revenue_yoy"].apply(
            lambda x: "—" if pd.isna(x) else f"{x*100:+.1f}%"
        )
        show_cols = [
            "daily_status", "stock_id", "stock_name", "market",
            "price", "低風險區", "low_risk_streak", "營收 YoY",
        ]
        preview = preview[show_cols].rename(columns={
            "daily_status": "今日狀態",
            "stock_id": "代號",
            "stock_name": "股票",
            "market": "市場",
            "price": "現價",
            "low_risk_streak": "連續確認",
        })
        st.dataframe(preview, hide_index=True, use_container_width=True)

st.markdown("---")

try:
    universe = load_taiwan_stock_universe(token)
except Exception as e:
    st.error(f"無法取得台股清單：{e}")
    st.stop()

if markets:
    universe = universe[universe["market"].isin(markets)].copy()
else:
    universe = universe.iloc[0:0].copy()

industries = sorted(
    x for x in universe["industry_category"].dropna().astype(str).unique()
    if x.strip()
)
selected_industry = st.selectbox(
    "篩選產業",
    ["全部產業"] + industries,
)
if selected_industry != "全部產業":
    universe = universe[
        universe["industry_category"].astype(str) == selected_industry
    ].copy()

# Deterministic spread across the universe when using a scan cap,
# rather than taking only the lowest stock IDs.
choice_to_n = {
    "100（快速測試）": 100,
    "300（建議先用）": 300,
    "600": 600,
    "全部": None,
}
cap = choice_to_n[max_choice]
if cap is not None and len(universe) > cap:
    positions = np.linspace(0, len(universe) - 1, cap, dtype=int)
    scan_universe = universe.iloc[positions].drop_duplicates("stock_id").copy()
else:
    scan_universe = universe.copy()

c1, c2, c3 = st.columns(3)
c1.metric("目前股票池", f"{len(universe):,}")
c2.metric("本次第一階段", f"{len(scan_universe):,}")
c3.metric("完整確認上限", f"{confirm_n}")

st.caption(
    "若選「全部」，Yahoo Finance 需要分批下載大量行情，可能花數分鐘。"
    "300 檔模式是測試用的均勻抽樣，不代表全市場完整結果。"
)

run = st.button(
    "🐾 更新今日掃描",
    type="primary",
    use_container_width=True,
    disabled=scan_universe.empty,
)

if run:
    progress = st.progress(0, text="第一階段：下載行情並做技術初篩…")

    def update_progress(v):
        progress.progress(
            min(int(v * 55), 55),
            text=f"第一階段：技術初篩 {v*100:.0f}%",
        )

    quick = quick_screen_universe(
        scan_universe,
        batch_size=80,
        period="1y",
        progress_callback=update_progress,
    )

    if quick.empty:
        progress.empty()
        st.warning("第一階段沒有找到候選股，或 Yahoo Finance 暫時無法取得足夠行情。")
        st.stop()

    candidates = quick.head(confirm_n).copy()
    st.caption(
        f"第一階段找到 {len(quick)} 檔寬鬆候選；"
        f"接著完整確認排名前 {len(candidates)} 檔。"
    )

    confirmed = []
    errors = []
    total = len(candidates)

    for i, (_, row) in enumerate(candidates.iterrows(), start=1):
        progress.progress(
            55 + int(i / max(total, 1) * 45),
            text=f"第二階段：完整確認 {i}/{total}｜{row['stock_id']} {row['stock_name']}",
        )
        try:
            confirmed.append(confirm_candidate(row, token))
        except Exception as e:
            errors.append({
                "stock_id": row["stock_id"],
                "stock_name": row["stock_name"],
                "error": str(e)[:160],
            })

    progress.empty()

    current = pd.DataFrame(confirmed)
    if current.empty:
        st.error("第二階段沒有成功完成任何個股確認。")
        if errors:
            st.dataframe(pd.DataFrame(errors), hide_index=True)
        st.stop()

    history_before = load_history(APP_DIR)
    current = add_transition_labels(current, history_before)
    save_history(APP_DIR, current)
    st.session_state["latest_scanner_results"] = current

    low = current[current["is_low_risk"]].copy()
    new_count = int((low["daily_status"] == "🆕 今日新進").sum()) if not low.empty else 0

    a, b, c = st.columns(3)
    a.metric("完整確認成功", len(current))
    b.metric("低風險區", len(low))
    c.metric("今日新進", new_count)

    if errors:
        with st.expander(f"有 {len(errors)} 檔確認失敗"):
            st.dataframe(pd.DataFrame(errors), hide_index=True, use_container_width=True)

# Show current-session result after scan.
current = st.session_state.get("latest_scanner_results")
if isinstance(current, pd.DataFrame) and not current.empty:
    st.markdown("---")
    st.subheader("今日完整確認結果")

    only_new = st.toggle("只看「今日新進」", value=False)

    low = current[current["is_low_risk"]].copy()
    if only_new:
        low = low[low["daily_status"] == "🆕 今日新進"].copy()

    if low.empty:
        st.warning("目前這次完整確認中，沒有符合篩選條件的低風險股票。")
    else:
        low["低風險區"] = low.apply(
            lambda r: f"{r['safe_low']:.2f}～{r['safe_high']:.2f}", axis=1
        )
        low["營收 YoY"] = low["revenue_yoy"].apply(
            lambda x: "—" if pd.isna(x) else f"{x*100:+.1f}%"
        )
        low["營收加速度"] = low["revenue_acceleration"].apply(
            lambda x: "—" if pd.isna(x) else f"{x*100:+.1f}pp"
        )
        low["距承接區上緣"] = (
            (low["price"] / low["safe_high"] - 1) * 100
        ).round(2)

        columns = [
            "daily_status",
            "stock_id",
            "stock_name",
            "market",
            "industry_category",
            "price",
            "低風險區",
            "low_risk_streak",
            "ma13",
            "ma40",
            "ma63",
            "ma150",
            "ma1000",
            "營收 YoY",
            "營收加速度",
            "valuation_score",
            "technical_score",
            "data_status",
            "scan_date",
        ]
        show = low[columns].rename(columns={
            "daily_status": "今日狀態",
            "stock_id": "代號",
            "stock_name": "股票",
            "market": "市場",
            "industry_category": "產業",
            "price": "現價",
            "low_risk_streak": "連續確認",
            "ma13": "MA13",
            "ma40": "MA40",
            "ma63": "MA63",
            "ma150": "MA150",
            "ma1000": "MA1000",
            "valuation_score": "估值安全",
            "technical_score": "籌碼技術",
            "data_status": "資料狀態",
            "scan_date": "行情日",
        })

        st.dataframe(
            show,
            hide_index=True,
            use_container_width=True,
            column_config={
                "現價": st.column_config.NumberColumn(format="%.2f"),
                "MA13": st.column_config.NumberColumn(format="%.2f"),
                "MA40": st.column_config.NumberColumn(format="%.2f"),
                "MA63": st.column_config.NumberColumn(format="%.2f"),
                "MA150": st.column_config.NumberColumn(format="%.2f"),
                "MA1000": st.column_config.NumberColumn(format="%.2f"),
            },
        )

        csv_bytes = show.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "下載這次低風險清單 CSV",
            data=csv_bytes,
            file_name="gaga_low_risk_today.csv",
            mime="text/csv",
            use_container_width=True,
        )

    with st.expander("查看第二階段所有完整確認股票"):
        all_show = current[
            [
                "daily_status", "stock_id", "stock_name", "zone",
                "price", "safe_low", "safe_high",
                "valuation_score", "technical_score", "data_status", "scan_date",
            ]
        ].copy()
        st.dataframe(all_show, hide_index=True, use_container_width=True)

st.markdown("---")
st.caption(
    "掃描邏輯：第一階段是寬鬆技術初篩，不等於低風險結論；"
    "第二階段才使用與個股頁一致的 V4.10 價格區模型。"
    "「今日新進」只會在本機已保存前一個交易日的完整確認紀錄後成立。"
)
