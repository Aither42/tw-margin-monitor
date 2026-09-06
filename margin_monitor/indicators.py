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
        return "🟢 偏低風險"
    if score < 60:
        return "🟡 中等風險"
    if score < 80:
        return "🟠 偏高風險"
    return "🔴 極高風險"


def _scale(series: pd.Series, low: float, high: float, points: float) -> pd.Series:
    """Linearly map a metric to risk points and cap both ends."""
    return ((series - low) / (high - low) * points).clip(0, points).fillna(0)


def _daily_index_risk(frame: pd.DataFrame, value_column: str, label: str, calendar) -> pd.DataFrame:
    daily = (frame[['date', value_column]].sort_values('date')
             .drop_duplicates('date', keep='last').set_index('date')
             .reindex(calendar).rename(columns={value_column: 'raw_value'}))
    daily.index.name = 'date'
    price = daily['raw_value']
    daily_return = price.pct_change(fill_method=None)
    moving_average = price.rolling(100, min_periods=20).mean()
    stretch = price / moving_average - 1
    momentum_12w = price.pct_change(60, fill_method=None)
    annualized_volatility = daily_return.rolling(20, min_periods=20).std() * (252**0.5)

    daily["risk"] = (
        _scale(stretch, -0.05, 0.15, 40)
        + _scale(momentum_12w, -0.05, 0.20, 30)
        + _scale(annualized_volatility, 0.10, 0.45, 30)
    ).clip(0, 100)
    valid = price.notna() & momentum_12w.notna() & annualized_volatility.notna()
    daily.loc[~valid, 'risk'] = float('nan')
    daily['series'] = label
    return daily.reset_index()


def _daily_market_margin_risk(
    margin: pd.DataFrame,
    taiex: pd.DataFrame,
    tpex: pd.DataFrame,
    label: str = "全市場融資壓力",
    calendar=None,
) -> pd.DataFrame:
    """Daily combined TWSE+TPEx financing risk, preserving the V3 logic.

    Amounts are combined in NT$ thousands.  The price leg used by the divergence
    component is the 20-trading-day return of TAIEX and TPEx, weighted each day
    by where the combined financing balance actually sits.
    """
    needed = [
        "date",
        "margin_balance",
        "twse_margin_balance",
        "tpex_margin_balance",
        "twse_margin_weight",
        "tpex_margin_weight",
    ]
    financing = (
        margin[needed]
        .dropna(subset=["date", "margin_balance"])
        .sort_values("date")
        .drop_duplicates("date", keep="last")
        .set_index("date")
    )
    if calendar is not None:
        financing = financing.reindex(calendar)
    financing.index.name = 'date'
    balance = financing["margin_balance"]

    # 130 trading days approximates 26 weeks; 20 trading days approximates 4 weeks.
    rolling_low = balance.rolling(130, min_periods=20).min()
    rolling_high = balance.rolling(130, min_periods=20).max()
    range_size = (rolling_high - rolling_low).replace(0, pd.NA)
    balance_position = (balance - rolling_low) / range_size
    growth_20d = balance.pct_change(20, fill_method=None)

    financing["risk"] = (
        balance_position.fillna(0.5) * 50
        + _scale(growth_20d, -0.03, 0.09, 35)
    )

    taiex_return = (
        taiex[["date", "taiex"]]
        .dropna()
        .sort_values("date")
        .drop_duplicates("date", keep="last")
        .set_index("date")["taiex"]
        .reindex(financing.index)
        .pct_change(20, fill_method=None)
    )
    tpex_return = (
        tpex[["date", "tpex"]]
        .dropna()
        .sort_values("date")
        .drop_duplicates("date", keep="last")
        .set_index("date")["tpex"]
        .reindex(financing.index)
        .pct_change(20, fill_method=None)
    )

    market_return_20d = (
        taiex_return * financing["twse_margin_weight"]
        + tpex_return * financing["tpex_margin_weight"]
    )

    # This component is truly a divergence: it activates only when the combined
    # market return is negative AND financing has increased over the same window.
    divergence_mask = (market_return_20d < 0) & (growth_20d > 0)
    divergence = (
        (-market_return_20d).clip(lower=0).fillna(0) * 100
        + growth_20d.clip(lower=0).fillna(0) * 100
    ).where(divergence_mask, 0.0)

    financing["risk"] = (financing["risk"] + divergence.clip(0, 15)).clip(0, 100)
    valid = balance.notna() & growth_20d.notna() & market_return_20d.notna() & rolling_low.notna()
    financing.loc[~valid, 'risk'] = float('nan')
    financing["market_return_20d"] = market_return_20d
    financing["margin_growth_20d"] = growth_20d
    financing["raw_value"] = balance / 100_000  # NT$ thousands -> NT$ 100 million (億元)
    financing["series"] = label
    return financing.reset_index()


def build_risk_river(
    taiex: pd.DataFrame,
    tpex: pd.DataFrame,
    margin: pd.DataFrame,
) -> pd.DataFrame:
    """Daily observations on a common trading calendar; missing dates stay NaN."""
    if taiex.empty:
        raise ValueError("taiex data is required")

    calendar = pd.DatetimeIndex(sorted(set(taiex['date']) | set(tpex.get('date', [])) | set(margin.get('date', []))), name='date')
    frames = [_daily_index_risk(taiex, "taiex", "上市風險", calendar)]
    if not tpex.empty:
        frames.append(_daily_index_risk(tpex, "tpex", "上櫃風險", calendar))
    if not margin.empty and not tpex.empty:
        frames.append(_daily_market_margin_risk(margin, taiex, tpex, calendar=calendar))

    result = pd.concat(frames, ignore_index=True).sort_values(["date", "series"])
    result["risk"] = result["risk"].round(1)
    return result.reset_index(drop=True)


def calculate_risk(taiex: pd.DataFrame, margin: pd.DataFrame) -> dict:
    """Legacy V3 helper retained for compatibility with older callers/tests."""
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
    if not margin.empty and "margin_balance" in margin.columns:
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
