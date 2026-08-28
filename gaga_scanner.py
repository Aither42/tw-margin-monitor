from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import streamlit as st
import yfinance as yf

FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"


def safe_float(x):
    try:
        if x is None or pd.isna(x):
            return None
        return float(x)
    except Exception:
        return None


def clamp(x, lo=0.0, hi=100.0):
    return float(max(lo, min(hi, x)))


def _finmind_get(params: dict, token: str = "", timeout: int = 25) -> pd.DataFrame:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    r = requests.get(FINMIND_URL, params=params, headers=headers, timeout=timeout)
    r.raise_for_status()
    payload = r.json()
    if payload.get("status", 200) != 200:
        raise RuntimeError(payload.get("msg") or f"FinMind status={payload.get('status')}")
    return pd.DataFrame(payload.get("data", []))


@st.cache_data(ttl=86400, show_spinner=False)
def load_taiwan_stock_universe(token: str = "") -> pd.DataFrame:
    df = _finmind_get({"dataset": "TaiwanStockInfo"}, token=token)
    if df.empty:
        raise RuntimeError("FinMind TaiwanStockInfo 沒有回傳資料。")

    required = {"stock_id", "stock_name", "type", "date", "industry_category"}
    missing = required - set(df.columns)
    if missing:
        raise RuntimeError(f"TaiwanStockInfo 缺少欄位：{sorted(missing)}")

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.sort_values(["stock_id", "date"]).drop_duplicates("stock_id", keep="last")

    # 上市 / 上櫃普通股票為主；排除 ETF / ETN，並保留常見 4 碼股票代號。
    df = df[df["type"].isin(["twse", "tpex"])]
    df = df[df["stock_id"].astype(str).str.fullmatch(r"\d{4}")]
    industry = df["industry_category"].fillna("").astype(str)
    df = df[~industry.str.contains("ETF|ETN", case=False, regex=True)]

    df["ticker"] = np.where(
        df["type"].eq("twse"),
        df["stock_id"].astype(str) + ".TW",
        df["stock_id"].astype(str) + ".TWO",
    )
    df["market"] = df["type"].map({"twse": "上市", "tpex": "上櫃"})
    return df[
        ["stock_id", "stock_name", "market", "industry_category", "ticker"]
    ].sort_values("stock_id").reset_index(drop=True)


def _extract_downloaded_frame(raw: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()

    if isinstance(raw.columns, pd.MultiIndex):
        lv0 = raw.columns.get_level_values(0)
        lv1 = raw.columns.get_level_values(1)
        if ticker in lv0:
            df = raw[ticker].copy()
        elif ticker in lv1:
            df = raw.xs(ticker, axis=1, level=1).copy()
        else:
            return pd.DataFrame()
    else:
        df = raw.copy()

    if "Close" not in df.columns:
        return pd.DataFrame()

    df = df.dropna(subset=["Close"])
    try:
        df.index = pd.to_datetime(df.index).tz_localize(None)
    except Exception:
        df.index = pd.to_datetime(df.index)
    return df


def _quick_metrics(df: pd.DataFrame) -> dict | None:
    if df is None or len(df) < 165:
        return None

    x = df.copy()
    close = x["Close"].astype(float)
    high = x["High"].astype(float)
    low = x["Low"].astype(float)

    ma40 = close.rolling(40).mean().iloc[-1]
    ma63 = close.rolling(63).mean().iloc[-1]
    ma150 = close.rolling(150).mean().iloc[-1]

    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(14).mean().iloc[-1]

    p = float(close.iloc[-1])
    if any(pd.isna(v) for v in [ma40, ma63, ma150, atr]) or p <= 0:
        return None

    support40 = float(low.tail(40).min())
    support63 = float(low.tail(63).min())

    # 第一階段只做寬鬆技術初篩，目的是不要漏掉太多可能進承接區的股票。
    near_upper = p <= max(ma40, ma63) + 0.75 * atr
    not_broken_too_far = p >= min(support63, ma150) - 1.75 * atr
    candidate = bool(near_upper and not_broken_too_far)

    proximity = min(abs(p - ma40), abs(p - ma63)) / p

    return {
        "quick_candidate": candidate,
        "quick_rank": float(proximity),
        "quick_price": p,
        "quick_ma40": float(ma40),
        "quick_ma63": float(ma63),
        "quick_ma150": float(ma150),
        "quick_atr": float(atr),
        "quick_support40": support40,
        "quick_support63": support63,
        "quick_date": pd.Timestamp(x.index[-1]).date().isoformat(),
    }


def quick_screen_universe(
    universe: pd.DataFrame,
    batch_size: int = 80,
    period: str = "1y",
    progress_callback=None,
) -> pd.DataFrame:
    rows = []
    tickers = universe["ticker"].tolist()
    total_batches = max(1, math.ceil(len(tickers) / batch_size))

    for batch_i, start in enumerate(range(0, len(tickers), batch_size), start=1):
        batch = tickers[start:start + batch_size]

        try:
            raw = yf.download(
                tickers=batch,
                period=period,
                auto_adjust=False,
                group_by="ticker",
                threads=True,
                progress=False,
            )
        except Exception:
            raw = pd.DataFrame()

        meta = universe.set_index("ticker")
        for ticker in batch:
            try:
                frame = _extract_downloaded_frame(raw, ticker)
                m = _quick_metrics(frame)
                if not m or not m["quick_candidate"]:
                    continue
                r = meta.loc[ticker].to_dict()
                r["ticker"] = ticker
                r.update(m)
                rows.append(r)
            except Exception:
                continue

        if progress_callback:
            progress_callback(batch_i / total_batches)

    if not rows:
        return pd.DataFrame()

    out = pd.DataFrame(rows)
    return out.sort_values(["quick_rank", "stock_id"]).reset_index(drop=True)


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
        upper_shadow_ratio = float(
            (x["High"] - max(x["Open"], x["Close"])) /
            (x["High"] - x["Low"])
        )
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
        "market_date": pd.Timestamp(df.index[-1]).date().isoformat(),
    }


def calc_revenue_features(rev: pd.DataFrame):
    if rev is None or rev.empty or len(rev) < 13:
        return {}

    x = rev.copy()
    if "revenue_year" in x.columns and "revenue_month" in x.columns:
        x["revenue_year"] = pd.to_numeric(x["revenue_year"], errors="coerce")
        x["revenue_month"] = pd.to_numeric(x["revenue_month"], errors="coerce")
        x["revenue"] = pd.to_numeric(x["revenue"], errors="coerce")
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
    else:
        x["date"] = pd.to_datetime(x["date"], errors="coerce")
        x["revenue"] = pd.to_numeric(x["revenue"], errors="coerce")
        x = x.dropna(subset=["date", "revenue"]).sort_values("date")
        x = x.drop_duplicates(subset=["date"], keep="last")

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
        "platform_shift": (
            safe_float(recent_rev / prior_rev - 1)
            if prior_rev and not np.isnan(prior_rev)
            else None
        ),
        "positive_yoy_6m": int((x["yoy"].tail(6) > 0).sum()),
    }


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
    growth_ref = max(
        [x for x in [y, revf.get("avg_yoy_3m")] if x is not None] or [0]
    )

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


def valuation_price_factor(info, revf):
    pe = safe_float(info.get("forwardPE")) or safe_float(info.get("trailingPE"))
    y = revf.get("avg_yoy_3m") or revf.get("latest_yoy") or 0.0
    factor = 1.00

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

    if y >= 0.80:
        factor += 0.08
    elif y >= 0.50:
        factor += 0.05
    elif y >= 0.25:
        factor += 0.02
    elif y < 0:
        factor -= 0.06

    acc = revf.get("acceleration")
    if acc is not None:
        if acc >= 0.20:
            factor += 0.03
        elif acc <= -0.15:
            factor -= 0.05

    return clamp(factor, 0.72, 1.10)


def compute_price_zones_v4(tech, info, revf, scores):
    p = tech["price"]
    atr = tech["atr14"] or p * 0.03

    ma40 = tech["ma40"] or p
    ma63 = tech["ma63"] or p
    ma150 = tech["ma150"] or ma63

    technical_anchor = np.median([
        x for x in [ma40, ma63, ma150, tech["support_40"], tech["support_63"]]
        if x is not None
    ])

    vf = valuation_price_factor(info, revf)
    growth_score = scores["成長動能"]
    fundamental_score = scores["基本面"]

    quality_factor = 1.0
    if growth_score >= 80 and fundamental_score >= 65:
        quality_factor += 0.03
    elif growth_score < 50:
        quality_factor -= 0.04

    adjusted_anchor = technical_anchor * vf * quality_factor
    safe_mid = min(p, adjusted_anchor)

    safe_low = max(
        min([
            x for x in [tech["support_63"], ma150, safe_mid - 1.5 * atr]
            if x is not None
        ]),
        p * 0.55,
    )

    safe_high = min(
        p,
        max(
            safe_low,
            min(safe_mid + 0.5 * atr, ma40, ma63 if ma63 < p else ma40),
        ),
    )

    resistance = max([
        x for x in [
            tech["resistance_40"],
            tech["resistance_63"],
            ma40 + 1.2 * atr,
        ]
        if x is not None
    ])

    valuation_tolerance = p
    if scores["估值安全"] >= 65 and growth_score >= 65:
        valuation_tolerance = p + 1.0 * atr
    elif scores["估值安全"] < 45:
        valuation_tolerance = max(p, ma40 + 0.5 * atr)

    neutral_high = max(
        safe_high + 0.5 * atr,
        min(resistance, valuation_tolerance + 1.5 * atr),
    )
    chase_start = max(neutral_high, ma40 + 1.5 * atr)

    return {
        "較安全分批區": (round(safe_low, 2), round(safe_high, 2)),
        "中性觀察區": (round(safe_high, 2), round(chase_start, 2)),
        "高風險追價區": (round(chase_start, 2), None),
        "valuation_factor": round(vf, 3),
        "technical_anchor": round(float(technical_anchor), 2),
        "adjusted_anchor": round(float(adjusted_anchor), 2),
    }


def classify_zone(price: float, zones: dict) -> str:
    low, high = zones["較安全分批區"]
    neutral_high = zones["中性觀察區"][1]
    if price < low:
        return "跌破承接區"
    if price <= high:
        return "低風險承接區"
    if price <= neutral_high:
        return "中風險觀察區"
    return "高風險追價區"


def _load_full_history(ticker: str) -> pd.DataFrame:
    hist = yf.Ticker(ticker).history(period="5y", auto_adjust=False)
    if hist is None or hist.empty:
        raise RuntimeError("Yahoo Finance 無 5 年行情")
    hist = hist.dropna(subset=["Close"]).copy()
    try:
        hist.index = pd.to_datetime(hist.index).tz_localize(None)
    except Exception:
        hist.index = pd.to_datetime(hist.index)
    return hist


def _load_info(ticker: str) -> dict:
    try:
        return yf.Ticker(ticker).info or {}
    except Exception:
        return {}


def _load_revenue(stock_id: str, token: str = "") -> pd.DataFrame:
    start_date = (date.today() - timedelta(days=1200)).isoformat()
    return _finmind_get(
        {
            "dataset": "TaiwanStockMonthRevenue",
            "data_id": stock_id,
            "start_date": start_date,
        },
        token=token,
    )


def confirm_candidate(row: pd.Series, token: str = "") -> dict:
    ticker = row["ticker"]
    sid = str(row["stock_id"])

    hist = _load_full_history(ticker)
    tech = calc_technical(hist)

    info = _load_info(ticker)

    revenue_ok = True
    revenue_error = ""
    try:
        rev = _load_revenue(sid, token)
        revf = calc_revenue_features(rev)
        if not revf:
            revenue_ok = False
            revenue_error = "月營收資料不足"
    except Exception as e:
        revf = {}
        revenue_ok = False
        revenue_error = str(e)[:120]

    scores = evaluate_scores(tech, info, revf)
    zones = compute_price_zones_v4(tech, info, revf, scores)
    safe_low, safe_high = zones["較安全分批區"]
    is_low = bool(safe_low <= tech["price"] <= safe_high)

    return {
        "scan_date": tech["market_date"],
        "stock_id": sid,
        "stock_name": row["stock_name"],
        "market": row["market"],
        "industry_category": row["industry_category"],
        "ticker": ticker,
        "price": round(tech["price"], 2),
        "safe_low": safe_low,
        "safe_high": safe_high,
        "zone": classify_zone(tech["price"], zones),
        "is_low_risk": is_low,
        "ma13": None if tech["ma13"] is None else round(tech["ma13"], 2),
        "ma40": None if tech["ma40"] is None else round(tech["ma40"], 2),
        "ma63": None if tech["ma63"] is None else round(tech["ma63"], 2),
        "ma150": None if tech["ma150"] is None else round(tech["ma150"], 2),
        "ma1000": None if tech["ma1000"] is None else round(tech["ma1000"], 2),
        "revenue_yoy": revf.get("latest_yoy"),
        "revenue_acceleration": revf.get("acceleration"),
        "fundamental_score": scores["基本面"],
        "growth_score": scores["成長動能"],
        "valuation_score": scores["估值安全"],
        "technical_score": scores["籌碼技術"],
        "revenue_ok": revenue_ok,
        "data_status": "完整" if revenue_ok else f"月營收部分缺漏：{revenue_error}",
        "checked_at": datetime.now().isoformat(timespec="seconds"),
    }


def history_path(app_dir: Path) -> Path:
    p = app_dir / "data"
    p.mkdir(parents=True, exist_ok=True)
    return p / "low_risk_scan_history.csv"


def load_history(app_dir: Path) -> pd.DataFrame:
    p = history_path(app_dir)
    if not p.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(p, dtype={"stock_id": str})
        if "scan_date" in df.columns:
            df["scan_date"] = pd.to_datetime(df["scan_date"], errors="coerce")
        return df
    except Exception:
        return pd.DataFrame()


def add_transition_labels(current: pd.DataFrame, history_before: pd.DataFrame) -> pd.DataFrame:
    if current.empty:
        return current

    out = current.copy()
    labels = []
    streaks = []

    hist = history_before.copy()
    if not hist.empty and "scan_date" in hist.columns:
        hist["scan_date"] = pd.to_datetime(hist["scan_date"], errors="coerce")

    for _, row in out.iterrows():
        sid = str(row["stock_id"])
        cur_date = pd.to_datetime(row["scan_date"], errors="coerce")
        cur_low = bool(row["is_low_risk"])

        prev = pd.DataFrame()
        if not hist.empty:
            prev = hist[
                (hist["stock_id"].astype(str) == sid) &
                (hist["scan_date"] < cur_date)
            ].sort_values("scan_date")

        if prev.empty:
            label = "✨ 首次確認" if cur_low else "—"
            streak = 1 if cur_low else 0
        else:
            prev_low = bool(prev.iloc[-1]["is_low_risk"])
            if cur_low and not prev_low:
                label = "🆕 今日新進"
            elif cur_low and prev_low:
                label = "🟢 持續低風險"
            elif (not cur_low) and prev_low:
                label = "↗️ 離開低風險"
            else:
                label = "—"

            streak = 0
            if cur_low:
                streak = 1
                for v in reversed(prev["is_low_risk"].tolist()):
                    if bool(v):
                        streak += 1
                    else:
                        break

        labels.append(label)
        streaks.append(streak)

    out["daily_status"] = labels
    out["low_risk_streak"] = streaks
    return out


def save_history(app_dir: Path, current: pd.DataFrame) -> None:
    if current.empty:
        return

    p = history_path(app_dir)
    old = load_history(app_dir)
    new = current.copy()

    # Don't persist presentation-only labels.
    new = new.drop(columns=["daily_status", "low_risk_streak"], errors="ignore")
    new["stock_id"] = new["stock_id"].astype(str)
    new["scan_date"] = pd.to_datetime(new["scan_date"], errors="coerce")

    if not old.empty:
        old["stock_id"] = old["stock_id"].astype(str)
        old["scan_date"] = pd.to_datetime(old["scan_date"], errors="coerce")

        keys = set(zip(new["stock_id"], new["scan_date"].dt.date))
        keep = [
            (sid, dt.date() if not pd.isna(dt) else None) not in keys
            for sid, dt in zip(old["stock_id"], old["scan_date"])
        ]
        old = old.loc[keep]
        merged = pd.concat([old, new], ignore_index=True, sort=False)
    else:
        merged = new

    merged = merged.sort_values(["scan_date", "stock_id"])
    merged.to_csv(p, index=False, encoding="utf-8-sig")


def latest_saved_low_risk(app_dir: Path) -> tuple[str | None, pd.DataFrame]:
    hist = load_history(app_dir)
    if hist.empty:
        return None, pd.DataFrame()

    hist = hist.dropna(subset=["scan_date"])
    if hist.empty:
        return None, pd.DataFrame()

    latest = hist["scan_date"].max()
    latest_rows = hist[hist["scan_date"] == latest].copy()
    low = latest_rows[latest_rows["is_low_risk"].astype(bool)].copy()

    # Rebuild labels against older history for display.
    older = hist[hist["scan_date"] < latest]
    low["scan_date"] = latest
    low = add_transition_labels(low, older)

    return latest.date().isoformat(), low
