
from __future__ import annotations

import math
import base64
from pathlib import Path
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import yfinance as yf
from navigation import show_navigation

st.set_page_config(page_title="軋軋台股決策助手 V4.14", page_icon="🐾", layout="wide")

st.markdown(
    """
    <style>
    /* Mobile-first spacing */
    .block-container {
        padding-top: 1rem;
        padding-bottom: 2rem;
        max-width: 920px;
    }

    /* Main decision summary: do not use st.metric for long text */
    .decision-strip {
        border: 1px solid rgba(128,128,128,.25);
        border-radius: 14px;
        padding: 0.72rem 0.9rem;
        margin: 0.35rem 0 0.65rem 0;
        background: rgba(128,128,128,.06);
    }
    .decision-row {
        display: flex;
        align-items: baseline;
        gap: .55rem;
        margin: .18rem 0;
        line-height: 1.35;
        flex-wrap: wrap;
    }
    .decision-label {
        min-width: 5.6rem;
        font-size: .82rem;
        opacity: .72;
        font-weight: 600;
    }
    .decision-value {
        font-size: 1.08rem;
        font-weight: 750;
        word-break: break-word;
    }
    .decision-price {
        font-size: 1.25rem;
        font-weight: 800;
    }


    /* Risk-zone cards */
    .risk-card {
        border-radius: 13px;
        padding: .7rem .75rem;
        margin-bottom: .35rem;
        min-height: 88px;
    }
    .risk-title {
        font-size: .9rem;
        font-weight: 750;
        margin-bottom: .18rem;
    }
    .risk-price {
        font-size: 1.18rem;
        font-weight: 800;
        white-space: nowrap;
    }
    .risk-action {
        font-size: .80rem;
        opacity: .82;
        margin-top: .20rem;
        line-height: 1.3;
    }
    .risk-low { background: rgba(33, 150, 83, .12); border: 1px solid rgba(33,150,83,.28); }
    .risk-mid { background: rgba(242, 153, 74, .12); border: 1px solid rgba(242,153,74,.28); }
    .risk-high { background: rgba(235, 87, 87, .12); border: 1px solid rgba(235,87,87,.28); }

    @media (max-width: 640px) {
        .block-container {
            padding-left: .75rem;
            padding-right: .75rem;
            padding-top: .65rem;
        }
        h1 { font-size: 1.55rem !important; }
        h2 { font-size: 1.18rem !important; }
        h3 { font-size: 1.02rem !important; }

        .decision-strip { padding: .62rem .72rem; }
        .decision-label { min-width: 4.7rem; font-size: .77rem; }
        .decision-value { font-size: 1.02rem; }
        .decision-price { font-size: 1.18rem; }


        .risk-card { min-height: auto; padding: .58rem .62rem; }
        .risk-title { font-size: .83rem; }
        .risk-price { font-size: 1.08rem; }
        .risk-action { font-size: .76rem; }

        /* Keep input row compact */
        div[data-testid="stTextInput"] input {
            min-height: 2.55rem;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# =========================================================
# Helpers
# =========================================================

def safe_float(x):
    try:
        if x is None or pd.isna(x):
            return None
        return float(x)
    except Exception:
        return None

def clamp(x, lo=0.0, hi=100.0):
    return float(max(lo, min(hi, x)))

def fmt_pct(x, digits=1):
    return "—" if x is None or pd.isna(x) else f"{x*100:.{digits}f}%"

def fmt_num(x, digits=2):
    return "—" if x is None or pd.isna(x) else f"{x:,.{digits}f}"

def fmt_price(x):
    return "—" if x is None or pd.isna(x) else f"{x:,.2f}"

def fmt_pct(x):
    return "—" if x is None or pd.isna(x) else f"{x*100:+.1f}%"


APP_DIR = Path(__file__).resolve().parent
ASSET_DIR = APP_DIR / "assets"

@st.cache_data(show_spinner=False)
def image_data_uri(filename: str) -> str:
    """Embed a local mascot image directly in the HTML so mobile cards stay compact."""
    path = ASSET_DIR / filename
    if not path.exists():
        return ""
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"

def mascot_for_context(price: float, zones: dict, holding_status: str, user_cost=None):
    """
    回傳一個 dict，依「未持有 / 已持有」與「成本相對位置」切換軋軋表情。
    keys:
      file, mode_label, state_label, action_label, headline, pnl
    """
    safe_low, safe_high = zones["較安全分批區"]
    neutral_low, neutral_high = zones["中性觀察區"]

    # --------------------------
    # 未持有模式
    # --------------------------
    if holding_status != "已持有":
        if price < safe_low:
            return {
                "file": "gaga_warning.png",
                "mode_label": "未持有模式",
                "state_label": "🐾 跌破支撐警戒",
                "action_label": "先等止跌，不急接",
                "headline": "軋軋：目前已跌破低風險承接區下緣。這不是『更便宜』，而是先確認基本面與趨勢有沒有壞掉。",
                "pnl": None,
            }
        if price <= safe_high:
            return {
                "file": "gaga_accumulate.png",
                "mode_label": "未持有模式",
                "state_label": "🐾 低風險承接",
                "action_label": "可分批承接",
                "headline": "軋軋：目前屬相對低風險承接帶，可以慢慢買、分批買，但仍不一次重壓。",
                "pnl": None,
            }
        if price <= neutral_high:
            return {
                "file": "gaga_observe.png",
                "mode_label": "未持有模式",
                "state_label": "🐾 中風險觀察",
                "action_label": "觀察等回檔",
                "headline": "軋軋：現在比較像觀察區，不急著追；等更有安全邊際的位置再出手會更舒服。",
                "pnl": None,
            }
        return {
            "file": "gaga_warning.png",
            "mode_label": "未持有模式",
            "state_label": "🐾 高風險追價",
            "action_label": "不追價",
            "headline": "軋軋：這裡屬高風險追價帶，重點不是『會不會再漲』，而是現在追的風險報酬不漂亮。",
            "pnl": None,
        }

    # --------------------------
    # 已持有但未輸入成本
    # --------------------------
    if user_cost is None or user_cost <= 0:
        if price < safe_low:
            return {
                "file": "gaga_warning.png",
                "mode_label": "已持有模式（未填成本）",
                "state_label": "🐾 跌破支撐警戒",
                "action_label": "先檢查，不急攤平",
                "headline": "軋軋：你已持有，但目前價格跌破承接區下緣。先看基本面與趨勢有沒有轉壞，不要先急著補。",
                "pnl": None,
            }
        if price <= safe_high:
            return {
                "file": "gaga_accumulate.png",
                "mode_label": "已持有模式（未填成本）",
                "state_label": "🐾 持股在承接區",
                "action_label": "續抱觀察",
                "headline": "軋軋：你已持有，且股價回到相對承接區。這裡偏向續抱觀察，如果要加碼也只建議小量。",
                "pnl": None,
            }
        if price <= neutral_high:
            return {
                "file": "gaga_observe.png",
                "mode_label": "已持有模式（未填成本）",
                "state_label": "🐾 持股觀察中",
                "action_label": "續抱觀察",
                "headline": "軋軋：你已持有，目前落在中風險觀察區。先續抱觀察，不要因為幾天波動就亂改計畫。",
                "pnl": None,
            }
        return {
            "file": "gaga_warning.png",
            "mode_label": "已持有模式（未填成本）",
            "state_label": "🐾 持股偏熱",
            "action_label": "續抱但不加碼",
            "headline": "軋軋：你已持有，但價格處在偏熱位置。重點是續抱時顧風險，而不是看到漲勢就繼續追。",
            "pnl": None,
        }

    # --------------------------
    # 已持有且有輸入成本
    # --------------------------
    pnl = price / user_cost - 1

    # 跌破支撐優先警戒
    if price < safe_low:
        if pnl >= 0.25:
            return {
                "file": "gaga_warning.png",
                "mode_label": "已持有模式",
                "state_label": "🐾 大賺回撤警戒",
                "action_label": "守停利、別硬撐",
                "headline": "軋軋：雖然你仍大幅獲利，但價格已跌破承接區下緣，這是『獲利回撤警戒』，重點是守住紀律與停利。",
                "pnl": pnl,
            }
        if pnl >= 0.08:
            return {
                "file": "gaga_warning.png",
                "mode_label": "已持有模式",
                "state_label": "🐾 小賺轉警戒",
                "action_label": "續抱觀察，不追不攤平",
                "headline": "軋軋：你目前仍有獲利，但技術位置轉弱。先觀察，不要因為曾經賺錢就失去風險感。",
                "pnl": pnl,
            }
        if pnl > -0.05:
            return {
                "file": "gaga_warning.png",
                "mode_label": "已持有模式",
                "state_label": "🐾 成本失守",
                "action_label": "先等止跌",
                "headline": "軋軋：價格跌破承接區，你又接近成本，現在先做的是等止跌與確認理由，不是急著攤平。",
                "pnl": pnl,
            }
        if pnl > -0.15:
            return {
                "file": "gaga_uneasy.png",
                "mode_label": "已持有模式",
                "state_label": "🐾 小套且失守支撐",
                "action_label": "控制部位、別硬拗",
                "headline": "軋軋：現在是小套且失守支撐的狀態。先看投資理由還在不在，避免把『想回本』當成理由。",
                "pnl": pnl,
            }
        return {
            "file": "gaga_loss.png",
            "mode_label": "已持有模式",
            "state_label": "🐾 深套警戒",
            "action_label": "優先風控",
            "headline": "軋軋：目前已是深套且跌破支撐的警戒情境。先檢查基本面與部位風險，別只想等回本。",
            "pnl": pnl,
        }

    # 還在支撐之上時，再依成本區分
    if pnl >= 0.25:
        if price > neutral_high:
            return {
                "file": "gaga_profit.png",
                "mode_label": "已持有模式",
                "state_label": "🐾 大賺但偏熱",
                "action_label": "續抱但不追價",
                "headline": "軋軋：你現在屬大幅獲利，但價格區間偏熱。重點是續抱、守停利，不是因為很會漲就再追。",
                "pnl": pnl,
            }
        return {
            "file": "gaga_profit.png",
            "mode_label": "已持有模式",
            "state_label": "🐾 大賺續抱",
            "action_label": "續抱、守停利",
            "headline": "軋軋：目前有很不錯的安全墊。續抱可以，但請用紀律守住成果。",
            "pnl": pnl,
        }

    if pnl >= 0.08:
        if price <= safe_high:
            return {
                "file": "gaga_profit.png",
                "mode_label": "已持有模式",
                "state_label": "🐾 小賺遇承接區",
                "action_label": "續抱為主，可小量加碼",
                "headline": "軋軋：你目前小賺，而且價格已回到承接帶。以續抱為主，若真要加碼也只建議小量分批。",
                "pnl": pnl,
            }
        if price > neutral_high:
            return {
                "file": "gaga_profit.png",
                "mode_label": "已持有模式",
                "state_label": "🐾 小賺偏熱",
                "action_label": "續抱但不加碼",
                "headline": "軋軋：目前帳面獲利不錯，但價格有點熱。這時比較像續抱、不追價，而不是再加大部位。",
                "pnl": pnl,
            }
        return {
            "file": "gaga_profit.png",
            "mode_label": "已持有模式",
            "state_label": "🐾 小賺續抱",
            "action_label": "續抱觀察",
            "headline": "軋軋：現在屬舒服的小賺狀態，續抱觀察就好，不需要因為短線波動太焦慮。",
            "pnl": pnl,
        }

    if pnl > -0.05:
        if price <= safe_high:
            return {
                "file": "gaga_accumulate.png",
                "mode_label": "已持有模式",
                "state_label": "🐾 成本附近承接區",
                "action_label": "續抱，可小量調整",
                "headline": "軋軋：你接近成本，且股價落在承接區。這裡偏向續抱與觀察；若要調整，只建議小量分批。",
                "pnl": pnl,
            }
        if price > neutral_high:
            return {
                "file": "gaga_observe.png",
                "mode_label": "已持有模式",
                "state_label": "🐾 成本附近偏熱",
                "action_label": "先觀察，不急加碼",
                "headline": "軋軋：你接近成本，但價格位置不算便宜。先觀察，沒必要在偏熱區硬加碼。",
                "pnl": pnl,
            }
        return {
            "file": "gaga_observe.png",
            "mode_label": "已持有模式",
            "state_label": "🐾 成本附近震盪",
            "action_label": "續抱觀察",
            "headline": "軋軋：目前大致在成本附近震盪。重點不是每天算輸贏，而是看投資理由有沒有變。",
            "pnl": pnl,
        }

    if pnl > -0.15:
        if price <= safe_high:
            return {
                "file": "gaga_uneasy.png",
                "mode_label": "已持有模式",
                "state_label": "🐾 小套可觀察",
                "action_label": "可觀察，不急重壓攤平",
                "headline": "軋軋：你是小幅套牢，但價格已回到承接帶。可以觀察，但不建議為了回本就重壓攤平。",
                "pnl": pnl,
            }
        return {
            "file": "gaga_uneasy.png",
            "mode_label": "已持有模式",
            "state_label": "🐾 小套觀察",
            "action_label": "不急攤平",
            "headline": "軋軋：目前是小套狀態，先穩住，不要把情緒性的攤平當成策略。",
            "pnl": pnl,
        }

    if price <= safe_high:
        return {
            "file": "gaga_loss.png",
            "mode_label": "已持有模式",
            "state_label": "🐾 深套但回承接區",
            "action_label": "先檢查理由，再決定",
            "headline": "軋軋：你目前深套，但股價回到承接區附近。這不等於可以盲目攤平，先確認基本面與你的資金規劃。",
            "pnl": pnl,
        }

    return {
        "file": "gaga_loss.png",
        "mode_label": "已持有模式",
        "state_label": "🐾 深套壓力",
        "action_label": "嚴控風險",
        "headline": "軋軋：目前是深套壓力區，先做風險管理，不要只把『回本』當成決策核心。",
        "pnl": pnl,
    }


def classify_price_zone(price: float, zones: dict):
    safe_low, safe_high = zones["較安全分批區"]
    neutral_low, neutral_high = zones["中性觀察區"]
    chase_low, _ = zones["高風險追價區"]

    if price < safe_low:
        return {
            "level": "⚠️ 跌破承接區下緣",
            "action": "先檢查基本面，不把跌深直接當便宜",
            "detail": f"目前股價低於 {safe_low:.2f}。這不是第四個『更安全區』；先確認營收、EPS、毛利率與趨勢是否破壞。"
        }
    if price <= safe_high:
        return {
            "level": "🟢 低風險承接區",
            "action": "可分批，不重壓",
            "detail": f"目前位於 {safe_low:.2f}～{safe_high:.2f} 的相對低風險承接帶。"
        }
    if price <= neutral_high:
        return {
            "level": "🟡 中風險觀察區",
            "action": "持有可觀察，新資金等回檔",
            "detail": f"目前位於 {neutral_low:.2f}～{neutral_high:.2f} 的中風險區。"
        }
    return {
        "level": "🔴 高風險追價區",
        "action": "不追價",
        "detail": f"目前高於 {chase_low:.2f}，安全邊際偏薄；若又伴隨爆量、長上影或過熱，風險更高。"
    }

# =========================================================
# Data
# =========================================================

@st.cache_data(ttl=900, show_spinner=False)
def resolve_ticker(stock_id: str):
    sid = stock_id.strip().upper().replace(".TW", "").replace(".TWO", "")
    best = None
    for ticker in [f"{sid}.TW", f"{sid}.TWO"]:
        try:
            hist = yf.Ticker(ticker).history(period="1y", auto_adjust=False)
            if hist is not None and len(hist.dropna()) >= 60:
                last_dt = pd.Timestamp(hist.index[-1]).tz_localize(None)
                if best is None or last_dt > best[2]:
                    best = (ticker, hist, last_dt)
        except Exception:
            pass
    if not best:
        raise ValueError("找不到有效行情，請確認台股代號。")
    return best[0]

@st.cache_data(ttl=900, show_spinner=False)
def load_price_history(ticker: str, period="5y"):
    hist = yf.Ticker(ticker).history(period=period, auto_adjust=False)
    if hist is None or hist.empty:
        raise ValueError("Yahoo Finance 暫時無行情資料。")
    hist = hist.copy()
    hist.index = pd.to_datetime(hist.index).tz_localize(None)
    return hist.dropna(subset=["Close"])

@st.cache_data(ttl=3600, show_spinner=False)
def load_yahoo_info(ticker: str):
    try:
        return yf.Ticker(ticker).info or {}
    except Exception:
        return {}

@st.cache_data(ttl=3600, show_spinner=False)
def load_finmind(dataset: str, stock_id: str, start_date: str, token: str = ""):
    """FinMind v4：單一股票資料查詢。"""
    url = "https://api.finmindtrade.com/api/v4/data"
    params = {
        "dataset": dataset,
        "data_id": stock_id,
        "start_date": start_date,
    }
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    r = requests.get(url, params=params, headers=headers, timeout=20)
    r.raise_for_status()

    payload = r.json()
    status = payload.get("status", 200)
    if status != 200:
        raise RuntimeError(payload.get("msg") or f"FinMind API status={status}")

    rows = payload.get("data", [])
    if not rows:
        raise RuntimeError("FinMind 沒有回傳資料，可能是 API 額度、代號或資料更新問題。")

    return pd.DataFrame(rows)

@st.cache_data(ttl=3600, show_spinner=False)
def load_month_revenue(stock_id: str, token: str = ""):
    df = load_finmind(
        "TaiwanStockMonthRevenue",
        stock_id,
        (date.today() - timedelta(days=1200)).isoformat(),
        token,
    )

    if "date" not in df.columns or "revenue" not in df.columns:
        raise RuntimeError(
            "FinMind 月營收欄位格式不符預期。"
            f"目前欄位：{', '.join(map(str, df.columns))}"
        )

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["revenue"] = pd.to_numeric(df["revenue"], errors="coerce")
    df = df.dropna(subset=["date", "revenue"]).sort_values("date")

    if len(df) < 13:
        raise RuntimeError("月營收資料少於 13 個月，無法計算 YoY 與成長加速度。")

    return df

# =========================================================
# Technical
# =========================================================

def rsi(series: pd.Series, n=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(n).mean()
    loss = -delta.clip(upper=0).rolling(n).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)

def calc_technical(hist: pd.DataFrame):
    df = hist.copy()
    c = df["Close"]
    ret = c.pct_change()

    for n in [13, 40, 63, 150, 1000]:
        df[f"MA{n}"] = c.rolling(n).mean()

    df["RSI14"] = rsi(c, 14)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - df["Close"].shift(1)).abs(),
        (df["Low"] - df["Close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    df["ATR14"] = tr.rolling(14).mean()
    df["AVG_VOL20"] = df["Volume"].replace(0, np.nan).rolling(20).mean()
    df["VOL20"] = ret.rolling(20).std() * math.sqrt(252)

    x = df.iloc[-1]
    p = float(x["Close"])
    high52 = float(c.tail(252).max())

    vol_ratio = safe_float(x["Volume"] / x["AVG_VOL20"]) if safe_float(x["AVG_VOL20"]) else None
    upper_shadow_ratio = 0.0
    intraday_range = 0.0
    if x["High"] > x["Low"]:
        upper_shadow_ratio = float((x["High"] - max(x["Open"], x["Close"])) / (x["High"] - x["Low"]))
        intraday_range = float((x["High"] - x["Low"]) / x["Close"])

    return {
        "price": p,
        "ma13": safe_float(x["MA13"]),
        "ma40": safe_float(x["MA40"]),
        "ma63": safe_float(x["MA63"]),
        "ma150": safe_float(x["MA150"]),
        "ma1000": safe_float(x["MA1000"]),
        "rsi14": safe_float(x["RSI14"]),
        "atr14": safe_float(x["ATR14"]),
        "vol20": safe_float(x["VOL20"]),
        "volume_ratio": vol_ratio,
        "drawdown_52w": p / high52 - 1,
        "upper_shadow_ratio": upper_shadow_ratio,
        "intraday_range": intraday_range,
        "support_40": safe_float(df["Low"].tail(40).min()),
        "support_63": safe_float(df["Low"].tail(63).min()),
        "resistance_40": safe_float(df["High"].tail(40).max()),
        "resistance_63": safe_float(df["High"].tail(63).max()),
    }, df

# =========================================================
# Revenue growth
# =========================================================

def calc_revenue_features(rev: pd.DataFrame):
    if rev is None or rev.empty or len(rev) < 13:
        return {}

    x = rev.copy()

    # 優先使用真正的營收年月，而不是公告日，避免 YoY 月份錯位。
    if "revenue_year" in x.columns and "revenue_month" in x.columns:
        x["revenue_year"] = pd.to_numeric(x["revenue_year"], errors="coerce")
        x["revenue_month"] = pd.to_numeric(x["revenue_month"], errors="coerce")
        x = x.dropna(subset=["revenue_year", "revenue_month", "revenue"])
        x["period"] = pd.to_datetime(
            dict(
                year=x["revenue_year"].astype(int),
                month=x["revenue_month"].astype(int),
                day=1,
            ),
            errors="coerce",
        )
        x = x.dropna(subset=["period"]).sort_values("period")
        x = x.drop_duplicates(subset=["period"], keep="last")
        x["chart_date"] = x["period"]
    else:
        x = x.sort_values("date").drop_duplicates(subset=["date"], keep="last")
        x["chart_date"] = x["date"]

    if len(x) < 13:
        return {}

    x["yoy"] = x["revenue"] / x["revenue"].shift(12) - 1
    x["mom"] = x["revenue"] / x["revenue"].shift(1) - 1

    yoy3 = x["yoy"].tail(3).dropna()
    yoy6 = x["yoy"].tail(6).dropna()
    yoy12 = x["yoy"].tail(12).dropna()

    avg3 = yoy3.mean() if len(yoy3) else np.nan
    avg6 = yoy6.mean() if len(yoy6) else np.nan
    avg12 = yoy12.mean() if len(yoy12) else np.nan

    # 成長加速度：近 3 月平均 YoY - 近 12 月平均 YoY
    acceleration = avg3 - avg12 if not np.isnan(avg3) and not np.isnan(avg12) else np.nan

    recent_rev = x["revenue"].tail(3).mean()
    prior_rev = x["revenue"].iloc[-15:-3].mean() if len(x) >= 15 else np.nan

    return {
        "latest_yoy": safe_float(x.iloc[-1]["yoy"]),
        "latest_mom": safe_float(x.iloc[-1]["mom"]),
        "avg_yoy_3m": safe_float(avg3),
        "avg_yoy_6m": safe_float(avg6),
        "avg_yoy_12m": safe_float(avg12),
        "acceleration": safe_float(acceleration),
        "platform_shift": safe_float(recent_rev / prior_rev - 1) if prior_rev and not np.isnan(prior_rev) else None,
        "positive_yoy_6m": int((x["yoy"].tail(6) > 0).sum()),
        "revenue_df": x,
    }

# =========================================================
# Scores
# =========================================================

def evaluate_scores(tech, info, revf):
    fundamental = 50.0
    pm = safe_float(info.get("profitMargins"))
    roe = safe_float(info.get("returnOnEquity"))
    debt = safe_float(info.get("debtToEquity"))

    if pm is not None:
        fundamental += 15 if pm > 0.18 else 8 if pm > 0.08 else 3 if pm > 0 else -18
    if roe is not None:
        fundamental += 12 if roe > 0.18 else 6 if roe > 0.10 else -10 if roe < 0 else 0
    if debt is not None:
        fundamental += 5 if debt < 50 else -8 if debt > 150 else 0
    fundamental = clamp(fundamental)

    growth = 45.0
    y = revf.get("latest_yoy")
    acc = revf.get("acceleration")
    platform = revf.get("platform_shift")
    if y is not None:
        growth += 18 if y > 0.80 else 14 if y > 0.50 else 10 if y > 0.25 else 5 if y > 0.10 else -15 if y < -0.20 else -8 if y < 0 else 0
    if acc is not None:
        growth += 14 if acc > 0.20 else 8 if acc > 0.08 else -10 if acc < -0.15 else 0
    if platform is not None:
        growth += 12 if platform > 0.35 else 6 if platform > 0.15 else 0
    if revf.get("positive_yoy_6m", 0) >= 5:
        growth += 5
    growth = clamp(growth)

    valuation = 55.0
    pe = safe_float(info.get("forwardPE")) or safe_float(info.get("trailingPE"))
    pb = safe_float(info.get("priceToBook"))
    growth_ref = max([x for x in [y, revf.get("avg_yoy_3m")] if x is not None] or [0])

    if pe and pe > 0:
        valuation += 20 if pe < 15 else 12 if pe < 25 else 5 if pe < 35 else -5 if pe < 50 else -15 if pe < 70 else -25
        if growth_ref > 0.50 and pe < 70:
            valuation += 8
        if growth_ref > 0.80 and pe < 90:
            valuation += 5
    else:
        valuation -= 5

    if pb is not None:
        valuation += 5 if pb < 2 else -8 if pb > 10 else 0
    valuation = clamp(valuation)

    technical = 55.0
    p = tech["price"]
    # 五條均線總權重維持 30，避免因新增 MA13 讓技術分數整體膨脹。
    # MA13 = 短線、MA40/63 = 波段、MA150 = 中長線、MA1000 = 超長期趨勢代理。
    for ma, add in [
        (tech["ma13"], 3),
        (tech["ma40"], 4),
        (tech["ma63"], 6),
        (tech["ma150"], 7),
        (tech["ma1000"], 10),
    ]:
        if ma:
            technical += add if p >= ma else -add

    if tech["drawdown_52w"] > -0.03:
        technical -= 8
    elif -0.20 <= tech["drawdown_52w"] <= -0.08:
        technical += 6

    if tech["rsi14"] and tech["rsi14"] > 78:
        technical -= 12
    elif tech["rsi14"] and 42 <= tech["rsi14"] <= 65:
        technical += 5

    if tech["volume_ratio"] and tech["volume_ratio"] > 2.5:
        technical -= 8
    if tech["upper_shadow_ratio"] > 0.45 and tech["volume_ratio"] and tech["volume_ratio"] > 1.8:
        technical -= 15
    if tech["intraday_range"] > 0.08:
        technical -= 7
    technical = clamp(technical)

    return {
        "基本面": round(fundamental, 1),
        "成長動能": round(growth, 1),
        "估值安全": round(valuation, 1),
        "籌碼技術": round(technical, 1),
    }

# =========================================================
# V4 valuation-aware price zones
# =========================================================

def valuation_price_factor(info, revf):
    """
    Translate valuation + growth into a price adjustment factor.
    This is NOT a target-price model.
    It asks: at current fundamentals, how much discount/premium should
    we demand before calling a price 'comfortable'?
    """
    pe = safe_float(info.get("forwardPE")) or safe_float(info.get("trailingPE"))
    y = revf.get("avg_yoy_3m") or revf.get("latest_yoy") or 0.0

    # Neutral factor = 1.00
    factor = 1.00

    # PE penalty / comfort
    if pe:
        if pe >= 80:
            factor -= 0.18
        elif pe >= 60:
            factor -= 0.13
        elif pe >= 45:
            factor -= 0.08
        elif pe >= 35:
            factor -= 0.04
        elif pe <= 15:
            factor += 0.06
        elif pe <= 25:
            factor += 0.03

    # Growth can justify part, but not all, of a high valuation.
    if y >= 0.80:
        factor += 0.08
    elif y >= 0.50:
        factor += 0.05
    elif y >= 0.25:
        factor += 0.02
    elif y < 0:
        factor -= 0.06

    # Acceleration
    acc = revf.get("acceleration")
    if acc is not None:
        if acc >= 0.20:
            factor += 0.03
        elif acc <= -0.15:
            factor -= 0.05

    return clamp(factor, 0.72, 1.10)

def compute_price_zones_v4(tech, info, revf, scores):
    """
    Three zones are now based on:
    1) Technical structure
    2) Valuation comfort
    3) Revenue growth / acceleration
    4) Current volatility (ATR)
    """
    p = tech["price"]
    atr = tech["atr14"] or p * 0.03

    ma40 = tech["ma40"] or p
    ma63 = tech["ma63"] or p
    ma150 = tech["ma150"] or ma63

    # A technical "fair area" rather than a single line.
    technical_anchor = np.median([
        x for x in [ma40, ma63, ma150, tech["support_40"], tech["support_63"]]
        if x is not None
    ])

    vf = valuation_price_factor(info, revf)

    # Growth quality modifies how much of valuation premium we accept.
    growth_score = scores["成長動能"]
    fundamental_score = scores["基本面"]

    quality_factor = 1.0
    if growth_score >= 80 and fundamental_score >= 65:
        quality_factor += 0.03
    elif growth_score < 50:
        quality_factor -= 0.04

    adjusted_anchor = technical_anchor * vf * quality_factor

    # Safety band uses both adjusted value anchor and volatility.
    safe_mid = min(p, adjusted_anchor)

    # Lower edge: one to two ATR below the safe anchor, but do not make it absurdly deep.
    safe_low = max(
        min([x for x in [tech["support_63"], ma150, safe_mid - 1.5 * atr] if x is not None]),
        p * 0.55
    )

    # Upper edge of "comfortable" area.
    safe_high = min(
        p,
        max(
            safe_low,
            min(safe_mid + 0.5 * atr, ma40, ma63 if ma63 < p else ma40)
        )
    )

    # Neutral zone upper boundary:
    # technical resistance + valuation/growth tolerance
    resistance = max([x for x in [tech["resistance_40"], tech["resistance_63"], ma40 + 1.2 * atr] if x is not None])

    valuation_tolerance = p
    if scores["估值安全"] >= 65 and growth_score >= 65:
        valuation_tolerance = p + 1.0 * atr
    elif scores["估值安全"] < 45:
        valuation_tolerance = max(p, ma40 + 0.5 * atr)

    neutral_high = max(safe_high + 0.5 * atr, min(resistance, valuation_tolerance + 1.5 * atr))
    chase_start = max(neutral_high, ma40 + 1.5 * atr)

    return {
        "較安全分批區": (round(safe_low, 2), round(safe_high, 2)),
        "中性觀察區": (round(safe_high, 2), round(chase_start, 2)),
        "高風險追價區": (round(chase_start, 2), None),
        "valuation_factor": round(vf, 3),
        "technical_anchor": round(float(technical_anchor), 2),
        "adjusted_anchor": round(float(adjusted_anchor), 2),
    }

# =========================================================
# Decision engine
# =========================================================

@dataclass
class Decision:
    action: str
    risk_level: str
    one_liner: str
    reasons: list[str]
    warnings: list[str]
    zones: dict
    invalidation_rules: list[str]
    scores: dict

def build_decision(tech, info, revf, holding_status, user_cost=None):
    scores = evaluate_scores(tech, info, revf)
    zones = compute_price_zones_v4(tech, info, revf, scores)

    reasons, warnings = [], []

    if scores["成長動能"] >= 75:
        reasons.append("營收成長動能強，近期可能已進入新成長階段。")
    if revf.get("acceleration") is not None and revf["acceleration"] > 0.20:
        reasons.append("近3月營收年增率明顯高於過去12月平均，成長正在脫離舊慣性。")
    if revf.get("platform_shift") is not None and revf["platform_shift"] > 0.25:
        reasons.append("近期月營收均值明顯高於舊平台，營運級距可能已上移。")
    if scores["估值安全"] < 45:
        warnings.append("估值安全邊際偏低，即使公司成長很快，也要求更大的價格折價。")
    elif scores["估值安全"] >= 65:
        reasons.append("目前估值相對不緊繃，安全價區間可容許較小折價。")

    if tech["upper_shadow_ratio"] > 0.45 and tech["volume_ratio"] and tech["volume_ratio"] > 1.8:
        warnings.append("爆量長上影：盤中追價後遭遇明顯賣壓。")
    if tech["volume_ratio"] and tech["volume_ratio"] > 2.5:
        warnings.append("成交量遠高於20日均量，籌碼正在劇烈換手。")
    if tech["rsi14"] and tech["rsi14"] > 78:
        warnings.append("RSI 過熱，短線追價風險偏高。")

    f, g, v, t = scores["基本面"], scores["成長動能"], scores["估值安全"], scores["籌碼技術"]

    if holding_status == "未持有":
        if f >= 65 and g >= 70 and v >= 55 and t >= 55:
            action = "✅ 可分批建立"
            one_liner = "基本面與成長健康，估值與籌碼也未明顯失衡；較適合分批建立。"
        elif f >= 60 and g >= 70 and (v < 50 or t < 50):
            action = "⏳ 等整理，不追"
            one_liner = "公司可能很好，但目前價格沒有足夠安全邊際；等回到合理承接區再考慮。"
        elif g >= 75 and f < 55:
            action = "🧪 小部位觀察"
            one_liner = "營收很快，但獲利品質未完全確認，只適合小部位。"
        else:
            action = "👀 先觀察"
            one_liner = "目前條件不足以支持積極進場。"
    else:
        if f >= 60 and g >= 65 and t >= 45:
            action = "🟢 續抱為主"
            one_liner = "核心投資理由仍在；短線波動不必直接等同於基本面反轉。"
        elif f >= 60 and g >= 65 and t < 45:
            action = "🟡 續抱但停止加碼"
            one_liner = "基本面仍強，但短線籌碼風險偏高；先守、不追。"
        elif g < 50 and f < 55:
            action = "🟠 考慮減碼"
            one_liner = "成長與基本面同步轉弱，應把重點轉向保護資本。"
        else:
            action = "🟡 續抱觀察"
            one_liner = "尚未出現明確出場訊號，但需等待後續數據確認。"

    if user_cost and user_cost > 0:
        pnl = tech["price"] / user_cost - 1
        if pnl > 1:
            reasons.append(f"相對成本約有 {pnl*100:.0f}% 帳面空間，可用部位管理取代情緒化出場。")
        elif pnl < -0.2:
            warnings.append(f"相對成本約虧損 {abs(pnl)*100:.0f}%，更應依基本面而不是回本心態決策。")

    risk_count = sum([
        v < 45,
        t < 45,
        bool(tech["volume_ratio"] and tech["volume_ratio"] > 2.5),
        bool(tech["rsi14"] and tech["rsi14"] > 78),
        g < 50
    ])
    risk_level = "低" if risk_count <= 1 else "中" if risk_count <= 3 else "高"

    invalidation_rules = [
        "月營收年增率連續 2 個月明顯下滑，而且不是單純高基期。",
        "EPS 成長明顯落後營收，或毛利率連續 2 季下滑。",
        "爆量跌破近期大量低點，反彈又站不回。",
        "跌破 MA63 後無法收復，且成交量同步放大。",
        "估值仍高，但營收／EPS 成長率已明顯降速。"
    ]

    return Decision(action, risk_level, one_liner, reasons, warnings, zones, invalidation_rules, scores)

# =========================================================
# Charts
# =========================================================

def price_chart(df, zones):
    x = df.tail(300).copy()
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=x.index, open=x["Open"], high=x["High"], low=x["Low"], close=x["Close"], name="K線"
    ))

    for n in [13, 40, 63, 150, 1000]:
        col = f"MA{n}"
        if col in x.columns:
            fig.add_trace(go.Scatter(x=x.index, y=x[col], mode="lines", name=col))

    lo, hi = zones["較安全分批區"]
    _, hi2 = zones["中性觀察區"]
    fig.add_hrect(y0=lo, y1=hi, fillcolor="#22c55e", opacity=0.22, line_width=0, annotation_text="低風險承接區")
    fig.add_hrect(y0=hi, y1=hi2, fillcolor="#eab308", opacity=0.20, line_width=0, annotation_text="中風險觀察區")

    fig.update_layout(
        height=580,
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
        margin=dict(l=10, r=10, t=35, b=10),
        legend_orientation="h",
    )
    return fig

def revenue_chart(revf):
    x = revf["revenue_df"].tail(30).copy()
    fig = go.Figure()
    fig.add_trace(go.Bar(x=x["chart_date"], y=x["revenue"], name="月營收"))
    fig.add_trace(go.Scatter(
        x=x["chart_date"], y=x["yoy"]*100, mode="lines+markers", name="YoY %", yaxis="y2"
    ))
    fig.update_layout(
        height=420,
        yaxis=dict(title="營收"),
        yaxis2=dict(title="YoY %", overlaying="y", side="right"),
        hovermode="x unified",
        margin=dict(l=10, r=10, t=35, b=10),
        legend_orientation="h",
    )
    return fig

# =========================================================
# UI
# =========================================================

st.title("🐾 軋軋個股分析 V4.14")
st.caption("手機優先：軋軋情境判讀＋MA13 / MA40 / MA63 / MA150 / MA1000 技術架構。")

show_navigation()

with st.sidebar:
    st.header("資料設定")
    token = st.text_input("FinMind Token（選填）", type="password", key="finmind_token")
    st.caption("不填也會嘗試匿名抓資料；若被限流，可使用免費 Token。")

# 手機優先：股票代號與持有狀態放同一列
input_col, status_col = st.columns([1.65, 1.0], gap="small")
with input_col:
    sid = st.text_input(
        "股票代號",
        value="3450",
        placeholder="例如 3450",
        label_visibility="visible",
    )
with status_col:
    holding_status = st.radio(
        "持有狀態",
        ["未持有", "已持有"],
        horizontal=True,
        label_visibility="visible",
    )

cost = None
if holding_status == "已持有":
    cost = st.number_input(
        "持有成本（選填）",
        min_value=0.0,
        value=0.0,
        step=0.5,
        placeholder="例如 320",
    )
    if cost <= 0:
        cost = None

analyze = st.button("開始分析", type="primary", use_container_width=True)

if analyze:
    sid = sid.strip().replace(".TW", "").replace(".TWO", "")
    if not sid.isdigit():
        st.error("請輸入數字股票代號。")
        st.stop()

    try:
        with st.spinner("正在分析行情、營收、估值與風險…"):
            ticker = resolve_ticker(sid)
            hist = load_price_history(ticker)
            info = load_yahoo_info(ticker)
            tech, tech_df = calc_technical(hist)

            revenue_error = None
            try:
                rev = load_month_revenue(sid, token)
                revf = calc_revenue_features(rev)
                if not revf:
                    revenue_error = "月營收資料不足，無法完成 YoY / 成長加速度計算。"
            except Exception as e:
                revf = {}
                revenue_error = str(e)

            decision = build_decision(tech, info, revf, holding_status, cost)

        name = info.get("longName") or info.get("shortName") or sid
        st.subheader(f"{name}｜{sid}｜{ticker}")

        current_zone = classify_price_zone(tech["price"], decision.zones)
        mascot_ctx = mascot_for_context(
            tech["price"], decision.zones, holding_status, cost
        )
        mascot_path = ASSET_DIR / mascot_ctx["file"]

        # 手機優先：主摘要改成 Streamlit 原生元件，避免 HTML / 程式碼外露。
        img_col, info_col = st.columns([1.1, 1.4], gap="small")

        with img_col:
            if mascot_path.exists():
                st.image(str(mascot_path), use_container_width=True)
            else:
                st.caption("軋軋")

        with info_col:
            st.caption(mascot_ctx["mode_label"])
            st.markdown(f"### {mascot_ctx['state_label']}")
            st.markdown(f"**所在區間：** {current_zone['level']}")
            st.markdown(f"**怎麼做：** {mascot_ctx['action_label']}")
            st.markdown(f"**現在股價：** {fmt_price(tech['price'])}")

            if holding_status == "已持有" and cost:
                st.markdown(f"**持有成本：** {fmt_price(cost)}")
                st.markdown(f"**目前報酬：** {fmt_pct(mascot_ctx['pnl'])}")

        st.info(mascot_ctx["headline"])
        st.caption(f"區間補充：{current_zone['detail']}")
        st.caption(f"模型補充：{decision.one_liner}")

        st.markdown("## 三個價格風險區間")
        safe_lo, safe_hi = decision.zones["較安全分批區"]
        neutral_lo, neutral_hi = decision.zones["中性觀察區"]
        chase_lo, _ = decision.zones["高風險追價區"]

        z1, z2, z3 = st.columns(3, gap="small")
        with z1:
            st.markdown(
                f"""
                <div class="risk-card risk-low">
                  <div class="risk-title">🟢 低風險承接區</div>
                  <div class="risk-price">{safe_lo:.2f} ～ {safe_hi:.2f}</div>
                  <div class="risk-action">可分批建立／加碼，不一次重壓</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with z2:
            st.markdown(
                f"""
                <div class="risk-card risk-mid">
                  <div class="risk-title">🟡 中風險觀察區</div>
                  <div class="risk-price">{neutral_lo:.2f} ～ {neutral_hi:.2f}</div>
                  <div class="risk-action">已持有可觀察；新資金等回檔</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with z3:
            st.markdown(
                f"""
                <div class="risk-card risk-high">
                  <div class="risk-title">🔴 高風險追價區</div>
                  <div class="risk-price">{chase_lo:.2f} 以上</div>
                  <div class="risk-action">不追價；持有者看基本面與籌碼</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.caption("三區為相對風險帶，不是目標價。估值越貴、成長越降速，低風險承接區會自動下修；高成長只能部分抵銷高估值。")

        if tech["price"] < safe_lo:
            st.warning(
                f"目前股價低於低風險承接區下緣 {safe_lo:.2f}。"
                "跌得更低不代表更安全；這通常要先排除基本面轉弱、趨勢破壞或市場重新定價。"
            )

        st.subheader("🌊 風險河流圖")
        st.caption(
            "K 線＋MA13 / MA40 / MA63 / MA150 / MA1000；"
            "綠色帶為低風險承接區，黃色帶為中風險觀察區；風險帶為本次分析的價格區間，並非歷史每日重算。"
        )
        st.plotly_chart(
            price_chart(tech_df, decision.zones),
            use_container_width=True,
            key=f"risk_river_{sid}",
        )

        with st.expander("看 V4 三區怎麼算"):
            st.write(f"技術錨點：約 **{decision.zones['technical_anchor']:.2f}**")
            st.write(f"估值/成長調整因子：**{decision.zones['valuation_factor']:.3f}**")
            st.write(f"調整後價值錨點：約 **{decision.zones['adjusted_anchor']:.2f}**")
            st.write(
                "邏輯：均線統一為 MA13 / MA40 / MA63 / MA150 / MA1000。"
                "價格風險區仍以 MA40/63/150 與 40/63 日支撐形成主要技術錨點；"
                "MA13 用來看短線節奏，MA1000 用作約 200 週尺度的超長期趨勢代理。"
                "再依目前 P/E、營收成長率、成長加速度與 ATR 調整價格區間。"
            )

        st.markdown("## 為什麼系統這樣判斷")
        left, right = st.columns(2)
        with left:
            st.markdown("### ✅ 正面理由")
            if decision.reasons:
                for x in decision.reasons:
                    st.write(f"• {x}")
            else:
                st.write("• 暫無特別突出的結構性優勢。")
        with right:
            st.markdown("### ⚠️ 主要風險")
            if decision.warnings:
                for x in decision.warnings:
                    st.write(f"• {x}")
            else:
                st.write("• 暫無明顯高風險警報。")

        with st.expander("什麼情況代表行情可能真的轉壞？", expanded=False):
            for i, rule in enumerate(decision.invalidation_rules, start=1):
                st.write(f"{i}. {rule}")

        with st.expander("查看營收與成長加速度"):
            if revf:
                r1, r2, r3, r4 = st.columns(4)
                r1.metric("最新營收 YoY", fmt_pct(revf.get("latest_yoy")))
                r2.metric("近3月平均 YoY", fmt_pct(revf.get("avg_yoy_3m")))
                r3.metric("成長加速度", fmt_pct(revf.get("acceleration")))
                r4.metric("新營收平台幅度", fmt_pct(revf.get("platform_shift")))
                st.plotly_chart(revenue_chart(revf), use_container_width=True)
            else:
                st.warning("目前未取得足夠月營收資料，因此成長加速度無法計算。")
                if revenue_error:
                    st.caption(f"資料來源回覆：{revenue_error}")
                st.caption("本模型會抓約 3 年月營收；至少需要 13 個月才能計算 YoY。")

        with st.expander("認識軋軋", expanded=False):
            concept_path = ASSET_DIR / "gaga_concept.png"
            st.caption("支援未持有 / 已持有雙模式，並會依成本位置切換軋軋的狀態與行動提醒。")
            if concept_path.exists():
                st.image(str(concept_path), caption="軋軋・投資風險狀態設定", use_container_width=True)

        with st.expander("查看模型依據（進階）"):
            a, b, c, d = st.columns(4)
            a.metric("Trailing P/E", fmt_num(safe_float(info.get("trailingPE")), 1))
            b.metric("Forward P/E", fmt_num(safe_float(info.get("forwardPE")), 1))
            c.metric("P/B", fmt_num(safe_float(info.get("priceToBook")), 1))
            d.metric("ROE", fmt_pct(safe_float(info.get("returnOnEquity"))))

            st.dataframe(
                pd.DataFrame({
                    "面向": list(decision.scores.keys()),
                    "分數": list(decision.scores.values())
                }),
                hide_index=True,
                use_container_width=True
            )

        st.markdown("---")
        st.caption(
            "資料來源：Yahoo Finance / yfinance 與 FinMind。免費資料可能延遲、缺漏或修正。"
            " V4 價位區間是相對風險模型，不是合理價保證，也不構成投資建議。"
        )

    except Exception as e:
        st.error(f"分析失敗：{e}")
        st.caption("免費資料來源偶爾會限流，可稍後重試。")

# Market-wide financing monitor belongs below the individual-stock analysis.
from margin_monitor.view import render_margin_monitor
render_margin_monitor()
