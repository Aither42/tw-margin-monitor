"""Official market-data clients for the Taiwan margin risk dashboard."""

from __future__ import annotations

import datetime as dt
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from config import (
    DEFAULT_WEEKS,
    HTTP_TIMEOUT,
    MAX_WORKERS,
    REQUEST_HEADERS,
    TPEX_INDEX_URL,
    TWSE_INDEX_URL,
    TWSE_MARGIN_URL,
)


class MarketDataError(RuntimeError):
    """Raised when the dashboard cannot obtain its minimum required data."""


def _number(value: object) -> float:
    if value is None:
        raise ValueError("missing numeric value")
    text = str(value).replace(",", "").replace("+", "").strip()
    if text in {"", "--", "---"}:
        raise ValueError(f"invalid numeric value: {value}")
    return float(text)


def _roc_date(value: str) -> pd.Timestamp:
    year, month, day = (int(part) for part in value.split("/"))
    return pd.Timestamp(year=year + 1911, month=month, day=day)


def _get_json(url: str, params: dict[str, str]) -> dict:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.get(
                url,
                params=params,
                headers=REQUEST_HEADERS,
                timeout=HTTP_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
            if str(payload.get("stat", "OK")).lower() not in {"ok", ""}:
                raise MarketDataError(str(payload.get("stat")))
            return payload
        except (requests.RequestException, ValueError, MarketDataError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.4 * (2**attempt))
    raise MarketDataError(f"官方資料請求失敗：{last_error}")


def _month_starts(start: dt.date, end: dt.date) -> list[dt.date]:
    current = start.replace(day=1)
    months: list[dt.date] = []
    while current <= end:
        months.append(current)
        current = (current + dt.timedelta(days=32)).replace(day=1)
    return months


def _fetch_twse_month(month: dt.date) -> list[dict]:
    payload = _get_json(
        TWSE_INDEX_URL,
        {"date": month.strftime("%Y%m01"), "response": "json"},
    )
    records = []
    for row in payload.get("data", []):
        try:
            records.append(
                {
                    "date": _roc_date(row[0]),
                    "taiex": _number(row[4]),
                    "taiex_change": _number(row[5]),
                    "taiex_volume": _number(row[1]),
                }
            )
        except (IndexError, TypeError, ValueError):
            continue
    return records


def _fetch_tpex_month(month: dt.date) -> list[dict]:
    payload = _get_json(
        TPEX_INDEX_URL,
        {"date": month.strftime("%Y/%m/01"), "response": "json"},
    )
    tables = payload.get("tables", [])
    records = []
    for row in tables[0].get("data", []) if tables else []:
        try:
            records.append(
                {
                    "date": _roc_date(row[0]),
                    "tpex": _number(row[4]),
                    "tpex_change": _number(row[5]),
                    "tpex_volume": _number(row[1]),
                }
            )
        except (IndexError, TypeError, ValueError):
            continue
    return records


def _fetch_months(fetcher, months: list[dt.date]) -> tuple[list[dict], list[str]]:
    records: list[dict] = []
    warnings: list[str] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetcher, month): month for month in months}
        for future in as_completed(futures):
            month = futures[future]
            try:
                records.extend(future.result())
            except MarketDataError as exc:
                warnings.append(f"{month:%Y-%m}：{exc}")
    return records, warnings


def _fetch_margin_day(day: dt.date) -> dict:
    payload = _get_json(
        TWSE_MARGIN_URL,
        {
            "date": day.strftime("%Y%m%d"),
            "selectType": "MS",
            "response": "json",
        },
    )
    tables = payload.get("tables", [])
    rows = tables[0].get("data", []) if tables else []
    margin_row = next((row for row in rows if row and row[0] == "融資金額(仟元)"), None)
    if not margin_row:
        raise MarketDataError(f"{day:%Y-%m-%d} 無融資金額資料")

    previous = _number(margin_row[4]) / 100_000
    current = _number(margin_row[5]) / 100_000
    return {
        "date": pd.Timestamp(day),
        "margin_balance": current,
        "margin_daily_change": current - previous,
    }


def _weekly_trading_days(index_data: pd.DataFrame, weeks: int) -> list[dt.date]:
    weekly = (
        index_data.sort_values("date")
        .groupby(pd.Grouper(key="date", freq="W-FRI"), group_keys=False)
        .tail(1)
        .tail(weeks + 1)
    )
    return [timestamp.date() for timestamp in weekly["date"]]


def _fetch_margin_history(days: list[dt.date]) -> tuple[list[dict], list[str]]:
    records: list[dict] = []
    warnings: list[str] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(_fetch_margin_day, day): day for day in days}
        for future in as_completed(futures):
            day = futures[future]
            try:
                records.append(future.result())
            except MarketDataError as exc:
                warnings.append(f"{day:%Y-%m-%d}：{exc}")
    return records, warnings


def _frame(records: list[dict], required_column: str) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=["date", required_column])
    return (
        pd.DataFrame(records)
        .drop_duplicates(subset="date", keep="last")
        .sort_values("date")
        .reset_index(drop=True)
    )


def get_market_data(weeks: int = DEFAULT_WEEKS) -> dict:
    """Return a best-effort V4 dataset built from official TWSE/TPEx APIs."""
    if not 8 <= weeks <= 52:
        raise ValueError("weeks must be between 8 and 52")

    now = dt.datetime.now(ZoneInfo("Asia/Taipei"))
    start = now.date() - dt.timedelta(weeks=weeks + 5)
    months = _month_starts(start, now.date())

    twse_records, twse_warnings = _fetch_months(_fetch_twse_month, months)
    taiex = _frame(twse_records, "taiex")
    if taiex.empty:
        raise MarketDataError("無法取得證交所加權指數資料，請稍後再試。")

    tpex_records, tpex_warnings = _fetch_months(_fetch_tpex_month, months)
    tpex = _frame(tpex_records, "tpex")

    weekly_days = _weekly_trading_days(taiex, weeks)
    margin_records, margin_warnings = _fetch_margin_history(weekly_days)
    margin = _frame(margin_records, "margin_balance")

    cutoff = pd.Timestamp(now.date() - dt.timedelta(weeks=weeks))
    taiex = taiex[taiex["date"] >= cutoff].reset_index(drop=True)
    tpex = tpex[tpex["date"] >= cutoff].reset_index(drop=True)
    margin = margin[margin["date"] >= cutoff].reset_index(drop=True)

    warnings: list[str] = []
    if twse_warnings:
        warnings.append(f"部分加權指數月份讀取失敗（{len(twse_warnings)} 個月）")
    if tpex_warnings or tpex.empty:
        warnings.append("部分或全部上櫃指數資料暫時無法取得")
    if margin_warnings:
        warnings.append(f"融資週資料缺少 {len(margin_warnings)} 筆")
    if margin.empty:
        warnings.append("融資餘額資料暫時無法取得")

    return {
        "update_time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "weeks": weeks,
        "taiex": taiex,
        "tpex": tpex,
        "margin": margin,
        "warnings": warnings,
    }
