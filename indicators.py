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
        return "🟩 偏低風險"
    if score < 60:
        return "🟡 中等風險"
    if score < 80:
        return "🟠 偏高風險"
    return "🔴 極高風險"


def _scale(series: pd.Series, low: float, high: float, points: float) -> pd.Series:
    """Linearly map a metric to risk points and cap both ends."""
    return ((series - low) / (high - low) * points).clip(0, points).fillna(0)


def _weekly_index_risk(
    frame: pd.DataFrame,
    value_column: str,
    volume_column: str,
    label: str,
) -> pd.DataFrame:
    source = frame[["date", value_column, volume_column]].dropna().sort_values("date").copy()
    source["daily_volume_ratio"] = source[volume_column] / source[volume_column].shift(1).rolling(
        20, min_periods=5
    ).mean()
    source["week_end"] = source["date"].map(
        lambda value: value + dt.timedelta(days=(4 - value.weekday()) % 7)
    )
    weekly_price = (
        source.groupby("week_end", as_index=False).tail(1)
        .drop(columns=["date", volume_column])
        .rename(columns={"week_end": "date", value_column: "raw_value"})
    )
    # Compare average daily volume so holidays and an unfinished current week do
    # not look artificially quiet merely because they contain fewer sessions.
    weekly_volume = source.groupby("week_end", as_index=False)[volume_column].mean()
    weekly = (
        weekly_price.merge(weekly_volume, left_on="date", right_on="week_end", how="left")
        .drop(columns="week_end")
        .rename(columns={volume_column: "weekly_volume"})
        .set_index("date")
    )
    price = weekly["raw_value"]
    volume = weekly["weekly_volume"]
    weekly_return = price.pct_change()
    weekly["ma30"] = price.rolling(30, min_periods=8).mean()
    weekly["ma5"] = price.rolling(5, min_periods=3).mean()
    weekly["ma30_divergence"] = price / weekly["ma30"] - 1
    weekly["weekly_return"] = weekly_return
    prior_volume_average = volume.shift(1).rolling(10, min_periods=4).mean()
    weekly["weekly_volume_ratio"] = (volume / prior_volume_average).replace(
        [float("inf"), float("-inf")], pd.NA
    )
    # Use the stronger of the whole-week and latest-session signals so a sudden
    # one-day selloff is not diluted by quieter sessions earlier in the week.
    weekly["volume_ratio"] = weekly[["weekly_volume_ratio", "daily_volume_ratio"]].max(
        axis=1, skipna=True
    )

    overheat = _scale(weekly["ma30_divergence"], 0.03, 0.20, 25)
    breakdown = _scale(-weekly["ma30_divergence"], 0.00, 0.12, 25)
    volume_adjusted_loss = (-weekly_return).clip(lower=0) * weekly["volume_ratio"].fillna(1)
    sell_pressure = _scale(volume_adjusted_loss, 0.01, 0.10, 35)
    weak_rally = weekly_return.clip(lower=0) * (1 - weekly["volume_ratio"]).clip(lower=0)
    divergence = _scale(weak_rally, 0.005, 0.04, 15)
    base_risk = overheat + breakdown + sell_pressure + divergence

    # The fast five-week line is deliberately activated only in a high-risk
    # regime. Falling below it adds aftershock risk; reclaiming it grants relief.
    high_risk = (base_risk >= 60) | (sell_pressure >= 20)
    below_ma5 = _scale((weekly["ma5"] - price) / weekly["ma5"], 0, 0.08, 25)
    above_ma5 = _scale((price - weekly["ma5"]) / weekly["ma5"], 0, 0.05, 10)
    weekly["risk"] = (base_risk + below_ma5.where(high_risk, 0) - above_ma5.where(high_risk, 0)).clip(0, 100)
    weekly["five_week_trigger"] = high_risk
    weekly["volume_signal"] = [
        "量增下跌" if change < 0 and ratio >= 1.1
        else "量縮上漲" if change > 0 and ratio < 0.9
        else "量縮下跌" if change < 0 and ratio < 0.9
        else "量價齊揚" if change > 0 and ratio >= 1.1
        else "量價中性"
        for change, ratio in zip(weekly_return.fillna(0), weekly["volume_ratio"].fillna(1))
    ]
    weekly["series"] = label
    return weekly.reset_index()


def _margin_risk(margin: pd.DataFrame, taiex_weekly: pd.DataFrame) -> pd.DataFrame:
    financing = (
        margin[["date", "margin_balance"]]
        .dropna()
        .sort_values("date")
        .drop_duplicates("date", keep="last")
        .rename(columns={"margin_balance": "raw_value"})
        .set_index("date")
    )
    balance = financing["raw_value"]
    rolling_low = balance.rolling(26, min_periods=4).min()
    rolling_high = balance.rolling(26, min_periods=4).max()
    range_size = (rolling_high - rolling_low).replace(0, pd.NA)
    balance_position = (balance - rolling_low) / range_size
    growth_4w = balance.pct_change(4)

    financing["risk"] = (
        (balance_position.fillna(0.5) * 50)
        + _scale(growth_4w, -0.03, 0.09, 35)
    )

    index = taiex_weekly.set_index("date")["raw_value"].pct_change(4)
    aligned_index = index.reindex(financing.index, method="ffill")
    divergence = (
        (-aligned_index).clip(lower=0).fillna(0) * 100
        + growth_4w.clip(lower=0).fillna(0) * 100
    )
    financing["risk"] = (financing["risk"] + divergence.clip(0, 15)).clip(0, 100)
    financing["series"] = "融資風險"
    return financing.reset_index()


def build_risk_river(
    taiex: pd.DataFrame,
    tpex: pd.DataFrame,
    margin: pd.DataFrame,
) -> pd.DataFrame:
    """Build three comparable 0–100 weekly residual-risk series."""
    if taiex.empty:
        raise ValueError("taiex data is required")

    listed = _weekly_index_risk(taiex, "taiex", "taiex_volume", "上市風險")
    frames = [listed]
    if not tpex.empty:
        frames.append(_weekly_index_risk(tpex, "tpex", "tpex_volume", "上櫃風險"))
    if not margin.empty:
        frames.append(_margin_risk(margin, listed))

    result = pd.concat(frames, ignore_index=True).sort_values(["date", "series"])
    result["risk"] = result["risk"].round(1)
    return result.reset_index(drop=True)


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
