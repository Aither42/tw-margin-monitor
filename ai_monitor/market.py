from __future__ import annotations

import math

import numpy as np
import pandas as pd
import yfinance as yf


def _rsi(series: pd.Series, period: int = 14) -> float:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = -delta.clip(upper=0).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    value = rsi.iloc[-1] if len(rsi) else np.nan
    return float(value) if pd.notna(value) else np.nan


def fetch_ticker_metrics(tickers: dict[str, str], period: str = "1y") -> pd.DataFrame:
    rows = []
    for ticker, name in tickers.items():
        try:
            hist = yf.Ticker(ticker).history(period=period, auto_adjust=True)
            if hist.empty or len(hist) < 30:
                continue
            close = hist["Close"].dropna()
            current = float(close.iloc[-1])
            ret20 = (current / float(close.iloc[-21]) - 1) * 100 if len(close) >= 21 else np.nan
            ret60 = (current / float(close.iloc[-61]) - 1) * 100 if len(close) >= 61 else np.nan
            high252 = float(close.tail(252).max())
            dist_high = (current / high252 - 1) * 100 if high252 else np.nan
            ma50 = float(close.tail(50).mean()) if len(close) >= 50 else np.nan
            above_ma50 = bool(current > ma50) if not math.isnan(ma50) else False
            rows.append(
                {
                    "ticker": ticker,
                    "name": name,
                    "price": current,
                    "return_20d_pct": ret20,
                    "return_60d_pct": ret60,
                    "dist_52w_high_pct": dist_high,
                    "above_ma50": above_ma50,
                    "rsi14": _rsi(close),
                }
            )
        except Exception:
            continue
    return pd.DataFrame(rows)


def market_heat_score(df: pd.DataFrame) -> float:
    if df.empty:
        return 35.0
    score = 30.0
    avg20 = df["return_20d_pct"].dropna().mean()
    avg60 = df["return_60d_pct"].dropna().mean()
    near_high = df["dist_52w_high_pct"].dropna().median()
    breadth = df["above_ma50"].mean() if "above_ma50" in df else 0.5
    avg_rsi = df["rsi14"].dropna().mean()

    if pd.notna(avg20):
        if avg20 > 10:
            score += 10
        if avg20 > 20:
            score += 10
        if avg20 < -10:
            score -= 8
    if pd.notna(avg60):
        if avg60 > 25:
            score += 10
        if avg60 > 40:
            score += 10
    if pd.notna(near_high) and near_high > -5:
        score += 10
    if breadth > 0.70:
        score += 10
    if pd.notna(avg_rsi) and avg_rsi > 70:
        score += 10
    return float(np.clip(score, 0, 100))
