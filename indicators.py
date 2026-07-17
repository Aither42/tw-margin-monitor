"""Transparent, deterministic risk indicators for the dashboard."""

from __future__ import annotations

import datetime as dt

import pandas as pd


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def risk_level(score: float) -> str:
    if score < 20:
        return "🟢 低風險"
    if score < 40:
        return "🟡 留意"
    if score < 60:
        return "🟠 偏高"
    if score < 80:
        return "🔴 高風險"
    return "⚫ 極高風險"


def calculate_risk(taiex: pd.DataFrame, margin: pd.DataFrame) -> dict:
    """Calculate a 0–100 monitoring score from four observable components.

    The score is a market-pressure indicator, not a broker-reported maintenance
    ratio and not a prediction of future returns.
    """
    if taiex.empty:
        raise ValueError("taiex data is required")

    index = taiex.sort_values("date").dropna(subset=["taiex"])
    latest_index = float(index.iloc[-1]["taiex"])
    previous_index = float(index.iloc[-2]["taiex"]) if len(index) > 1 else latest_index
    daily_return = (latest_index / previous_index - 1) * 100 if previous_index else 0.0

    recent_12w = index[index["date"] >= index.iloc[-1]["date"] - dt.timedelta(days=84)]
    peak = float(recent_12w["taiex"].max())
    drawdown = (latest_index / peak - 1) * 100 if peak else 0.0
    drawdown_points = _clamp(-drawdown / 15 * 30, 0, 30)
    daily_points = _clamp(-daily_return / 3 * 15, 0, 15)

    margin_change_4w = 0.0
    index_change_4w = 0.0
    leverage_points = 0.0
    divergence_points = 0.0
    if not margin.empty:
        financing = margin.sort_values("date").dropna(subset=["margin_balance"])
        latest_margin = float(financing.iloc[-1]["margin_balance"])
        baseline_row = financing[
            financing["date"] <= financing.iloc[-1]["date"] - dt.timedelta(days=28)
        ]
        baseline_margin = float(
            (baseline_row.iloc[-1] if not baseline_row.empty else financing.iloc[0])[
                "margin_balance"
            ]
        )
        margin_change_4w = (
            (latest_margin / baseline_margin - 1) * 100 if baseline_margin else 0.0
        )
        leverage_points = _clamp((margin_change_4w + 2) / 10 * 30, 0, 30)

        index_baseline_rows = index[
            index["date"] <= index.iloc[-1]["date"] - dt.timedelta(days=28)
        ]
        index_baseline = float(
            (index_baseline_rows.iloc[-1] if not index_baseline_rows.empty else index.iloc[0])[
                "taiex"
            ]
        )
        index_change_4w = (
            (latest_index / index_baseline - 1) * 100 if index_baseline else 0.0
        )
        if margin_change_4w > 0 and index_change_4w < 0:
            divergence_points = _clamp(
                margin_change_4w * 2.5 + (-index_change_4w) * 1.5,
                0,
                25,
            )

    components = {
        "融資增幅": round(leverage_points, 1),
        "價跌資增背離": round(divergence_points, 1),
        "12週回落": round(drawdown_points, 1),
        "單日跌幅": round(daily_points, 1),
    }
    score = round(sum(components.values()), 1)
    return {
        "score": score,
        "level": risk_level(score),
        "components": components,
        "daily_return": round(daily_return, 2),
        "drawdown_12w": round(drawdown, 2),
        "margin_change_4w": round(margin_change_4w, 2),
        "index_change_4w": round(index_change_4w, 2),
    }
