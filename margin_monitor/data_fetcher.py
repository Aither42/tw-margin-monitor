"""Official market-data clients for the Taiwan risk-river dashboard."""

from __future__ import annotations

import datetime as dt
import re
import time
import json
import sqlite3
import threading
from pathlib import Path
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from io import StringIO
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from .config import (
    DEFAULT_WEEKS,
    HTTP_TIMEOUT,
    MAX_WORKERS,
    REQUEST_HEADERS,
    TPEX_INDEX_URL,
    TPEX_MARGIN_URL,
    TPEX_MARGIN_JSON_URL,
    TWSE_INDEX_URL,
    TWSE_MARGIN_URL,
)

_REQUEST_LOCK = threading.Lock()
_LAST_REQUEST = {}
_BLOCKED_UNTIL = {}


def _pace(url):
    """Limit requests per host, including retries, to avoid bursts."""
    host = urlparse(url).netloc
    with _REQUEST_LOCK:
        remaining = _BLOCKED_UNTIL.get(host, 0) - time.monotonic()
        if remaining > 0:
            raise RateLimitedError(f'{host} 暫停請求，約 {int(remaining)+1} 秒後再按更新補抓')
        delay = 1.0 - (time.monotonic() - _LAST_REQUEST.get(host, 0))
        if delay > 0:
            time.sleep(delay)
        _LAST_REQUEST[host] = time.monotonic()


class MarketDataError(RuntimeError):
    """Raised when the dashboard cannot obtain its minimum required data."""


class RateLimitedError(MarketDataError):
    """Stop the batch instead of repeatedly hitting a blocked official service."""


def _check_throttle(response, url):
    if response.status_code in (403, 428, 429):
        try:
            pause = max(180, int(response.headers.get('Retry-After', '180')))
        except ValueError:
            pause = 180
        with _REQUEST_LOCK:
            _BLOCKED_UNTIL[urlparse(url).netloc] = time.monotonic() + pause
        raise RateLimitedError(f'官方 HTTP {response.status_code} 限制存取，本輪暫停；{pause} 秒後可再按更新接續')


def _number(value: object) -> float:
    if value is None:
        raise ValueError("missing numeric value")
    text = str(value).replace(",", "").replace("+", "").strip()
    if text in {"", "--", "---", "nan", "None"}:
        raise ValueError(f"invalid numeric value: {value}")
    return float(text)


def _roc_date(value: str) -> pd.Timestamp:
    year, month, day = (int(part) for part in value.split("/"))
    return pd.Timestamp(year=year + 1911, month=month, day=day)


def _roc_date_text(day: dt.date) -> str:
    return f"{day.year - 1911:03d}/{day.month:02d}/{day.day:02d}"


def _get_json(url: str, params: dict[str, str]) -> dict:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            _pace(url)
            response = requests.get(
                url,
                params=params,
                headers=REQUEST_HEADERS,
                timeout=HTTP_TIMEOUT,
            )
            _check_throttle(response, url)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise MarketDataError("官方回應不是資料物件")
            if str(payload.get("stat", "OK")).lower() not in {"ok", ""}:
                raise MarketDataError(str(payload.get("stat")))
            return payload
        except RateLimitedError:
            raise
        except (requests.RequestException, ValueError, MarketDataError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.4 * (2**attempt))
    raise MarketDataError(f"官方資料請求失敗：{last_error}")


def _get_text(url: str, params: dict[str, str]) -> str:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            _pace(url)
            response = requests.get(
                url,
                params=params,
                headers=REQUEST_HEADERS,
                timeout=HTTP_TIMEOUT,
            )
            _check_throttle(response, url)
            response.raise_for_status()
            if not response.encoding or response.encoding.lower() == "iso-8859-1":
                response.encoding = response.apparent_encoding or "utf-8"
            return response.text
        except requests.RequestException as exc:
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
            date_value = str(row[0]).strip()
            parsed_date = (
                _roc_date(date_value)
                if re.match(r"^\d{2,3}/", date_value)
                else pd.Timestamp(date_value)
            )
            records.append(
                {
                    "date": parsed_date,
                    "tpex": _number(row[4]),
                    "tpex_change": _number(row[5]),
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


def _fetch_twse_margin_day(day: dt.date) -> dict:
    """Fetch TWSE market-wide margin financing amount balance in NT$ thousands."""
    payload = _get_json(
        TWSE_MARGIN_URL,
        {
            "date": day.strftime("%Y%m%d"),
            "selectType": "MS",
            "response": "json",
        },
    )
    _validate_date(payload.get("date"), day)
    tables = payload.get("tables", [])
    rows = tables[0].get("data", []) if tables else []
    margin_row = next(
        (
            row
            for row in rows
            if row
            and "融資" in str(row[0])
            and ("金額" in str(row[0]) or "金(" in str(row[0]))
        ),
        None,
    )
    if not margin_row or len(margin_row) < 2:
        raise MarketDataError(f"{day:%Y-%m-%d} 無上市融資金額資料")

    # The official summary row is: previous balance, buy, sell,
    # cash repayment, current balance.  The last numeric cell is the balance.
    numeric_cells: list[float] = []
    for cell in margin_row[1:]:
        try:
            numeric_cells.append(_number(cell))
        except ValueError:
            continue
    if not numeric_cells or numeric_cells[-1] <= 0:
        raise MarketDataError(f"{day:%Y-%m-%d} 上市融資金額格式異常")

    return {
        "date": pd.Timestamp(day),
        "margin_balance": numeric_cells[-1],  # NT$ thousands
    }


def _extract_tpex_margin_amount(html: str) -> float:
    """Return TPEx market-wide current margin financing balance in NT$ thousands."""
    try:
        tables = pd.read_html(StringIO(html), displayed_only=False)
    except (ValueError, ImportError) as exc:
        raise MarketDataError(f"上櫃融資表格解析失敗：{exc}") from exc

    for table in tables:
        if table.empty:
            continue
        for _, row in table.iterrows():
            cells = [str(value).strip() for value in row.tolist()]
            label = " ".join(cells)
            if "融資金" not in label:
                continue
            if "仟元" not in label and "千元" not in label:
                continue

            numeric_cells: list[float] = []
            for cell in cells:
                try:
                    numeric_cells.append(_number(cell))
                except ValueError:
                    continue
            if numeric_cells:
                # TPEx summary uses the same five amount columns; last is balance.
                return float(numeric_cells[-1])

    raise MarketDataError("上櫃融資表格找不到『融資金(仟元)』餘額")


def _fetch_tpex_margin_day(day: dt.date) -> dict:
    try:
        payload = _get_json(TPEX_MARGIN_JSON_URL, {"date": day.strftime("%Y/%m/%d"), "response": "json"})
        _validate_date(payload.get("date"), day)
        for table in payload.get("tables", []):
            for row in table.get("summary", []):
                if len(row) >= 7 and "融資金" in str(row[1]) and ("仟元" in str(row[1]) or "千元" in str(row[1])):
                    current = _number(row[6])
                    if current > 0:
                        return {"date": pd.Timestamp(day), "margin_balance": current}
        raise MarketDataError("上櫃 JSON 缺少融資金額合計")
    except RateLimitedError:
        raise
    except (MarketDataError, ValueError, TypeError, IndexError):
        return _fetch_tpex_margin_html(day)


def _validate_date(value, day):
    text = str(value).replace("/", "").replace("-", "")
    if text != day.strftime("%Y%m%d"):
        raise MarketDataError(f"回傳日期 {value} 與請求 {day} 不同，拒絕存入")


def _fetch_tpex_margin_html(day: dt.date) -> dict:
    html = _get_text(
        TPEX_MARGIN_URL,
        {
            "d": _roc_date_text(day),
            "l": "zh-tw",
            "o": "htm",
            "s": "0",
        },
    )
    match = re.search(r"資料日期\s*[:：]\s*(\d{2,3}/\d{1,2}/\d{1,2})", html)
    if not match or _roc_date(match.group(1)).date() != day:
        raise MarketDataError(f"{day} 上櫃 HTML 無相符資料日期")
    current = _extract_tpex_margin_amount(html)
    if current <= 0:
        raise MarketDataError("上櫃融資金額不正確")
    return {
        "date": pd.Timestamp(day),
        "margin_balance": current,  # NT$ thousands
    }


def _fetch_daily_history(fetcher, days: list[dt.date]) -> tuple[list[dict], list[str]]:
    records: list[dict] = []
    warnings: list[str] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetcher, day): day for day in days}
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


def _finalize_margin(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    result = frame.sort_values("date").copy()
    result["margin_daily_change"] = result["margin_balance"].diff().fillna(0)
    return result.reset_index(drop=True)


def _combine_margin_amounts(
    twse_margin: pd.DataFrame,
    tpex_margin: pd.DataFrame,
) -> pd.DataFrame:
    """Combine TWSE and TPEx financing balances by date without silent undercounting.

    Both official sources report financing amount balances in NT$ thousands.
    Only dates available from BOTH markets are kept.  This prevents a temporary
    source failure from being misread as a sudden collapse in total financing.
    """
    if twse_margin.empty or tpex_margin.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "margin_balance",
                "twse_margin_balance",
                "tpex_margin_balance",
                "twse_margin_weight",
                "tpex_margin_weight",
                "margin_daily_change",
            ]
        )

    twse = twse_margin[["date", "margin_balance"]].rename(
        columns={"margin_balance": "twse_margin_balance"}
    )
    tpex = tpex_margin[["date", "margin_balance"]].rename(
        columns={"margin_balance": "tpex_margin_balance"}
    )
    combined = pd.merge(twse, tpex, on="date", how="inner").sort_values("date")
    combined["margin_balance"] = (
        combined["twse_margin_balance"] + combined["tpex_margin_balance"]
    )
    valid_total = combined["margin_balance"].replace(0, pd.NA)
    combined["twse_margin_weight"] = combined["twse_margin_balance"] / valid_total
    combined["tpex_margin_weight"] = combined["tpex_margin_balance"] / valid_total
    combined["margin_daily_change"] = combined["margin_balance"].diff().fillna(0)
    return combined.reset_index(drop=True)


class HistoryStore:
    """Successful observations survive reruns; failed requests never erase rows."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS observations (source TEXT, day TEXT, payload TEXT, PRIMARY KEY(source,day))")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def save(self, source, records):
        rows = []
        for record in records:
            item = dict(record)
            item['date'] = str(pd.Timestamp(item['date']).date())
            rows.append((source, item['date'], json.dumps(item)))
        with self.connect() as db:
            db.executemany("INSERT OR REPLACE INTO observations VALUES (?,?,?)", rows)

    def read(self, source, column, start, end):
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM observations WHERE source=? AND day>=? AND day<=? ORDER BY day", (source, str(start), str(end))).fetchall()
        records = [json.loads(row[0]) for row in rows]
        for row in records:
            row['date'] = pd.Timestamp(row['date'])
        return _frame(records, column)


def _repair_margin(fetcher, days, store, source, progress=None):
    """Refresh the latest five dates and retry each remaining gap in a second pass."""
    if not days:
        return {}, 0
    existing = store.read(source, 'margin_balance', min(days), max(days))
    known = set(existing['date'].dt.date) if not existing.empty else set()
    pending = sorted((set(days) - known) | set(days[-5:]), reverse=True)
    failures = {}
    total = len(pending)
    for round_number in range(2):
        if not pending:
            break
        if round_number:
            time.sleep(1)
        limited = False
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(fetcher, day): day for day in pending}
            for count, future in enumerate(as_completed(futures), 1):
                day = futures[future]
                try:
                    row = future.result()
                    if pd.Timestamp(row['date']).date() != day or not pd.notna(row['margin_balance']) or row['margin_balance'] <= 0:
                        raise MarketDataError('日期或融資金額驗證失敗')
                    store.save(source, [row])
                    failures.pop(day, None)
                except RateLimitedError as exc:
                    failures[day] = str(exc)
                    limited = True
                except (MarketDataError, ValueError, TypeError, KeyError, requests.RequestException) as exc:
                    failures[day] = str(exc)
                if progress:
                    progress(f"{source}：第 {round_number+1} 輪 {count}/{len(pending)}，未完成 {len(failures)}；成功資料已保存")
        if limited:
            break
        pending = list(failures)
    return failures, total


def get_market_data(weeks=DEFAULT_WEEKS, *, cache_path=None, today=None, progress=None):
    if not 8 <= weeks <= 52:
        raise ValueError('weeks must be between 8 and 52')
    now = dt.datetime.now(ZoneInfo('Asia/Taipei'))
    end = today or now.date()
    display_cutoff = pd.Timestamp(end - dt.timedelta(weeks=weeks))
    # Additional history warms up 100/60/20-day price and 130-day financing windows.
    start = end - dt.timedelta(weeks=weeks + 32)
    path = cache_path or Path(__file__).resolve().parents[1] / 'data' / 'margin_monitor' / 'history.sqlite3'
    store = HistoryStore(path)
    warnings = []
    frames = {}
    for source, column, fetcher in [('twse_index', 'taiex', _fetch_twse_month), ('tpex_index', 'tpex', _fetch_tpex_month)]:
        if progress:
            progress(f'核對 {source} 每月交易日資料…')
        for month in _month_starts(start, end):
            try:
                rows = fetcher(month)
                if not rows:
                    # An empty current month before the first session is normal.
                    if month == end.replace(day=1) and end.day <= 3:
                        continue
                    raise MarketDataError('回應無指數資料')
                rows = [r for r in rows if pd.Timestamp(r['date']).year == month.year and pd.Timestamp(r['date']).month == month.month and pd.Timestamp(r['date']).date() <= end]
                if not rows:
                    raise MarketDataError('回應日期與查詢月份不同')
                store.save(source, rows)
            except (MarketDataError, ValueError) as exc:
                warnings.append(f'{source} {month:%Y-%m} 更新失敗，保留已存資料：{exc}')
        frames[column] = store.read(source, column, start, end)
    taiex, tpex = frames['taiex'], frames['tpex']
    if taiex.empty:
        raise MarketDataError('無法取得加權指數，且沒有可用歷史快取。')
    # A failed index month on one market must not remove those dates from the audit.
    days = sorted(set(taiex['date'].dt.date) | (set(tpex['date'].dt.date) if not tpex.empty else set()))
    failure_maps = {}
    for source, fetcher in [('twse_margin', _fetch_twse_margin_day), ('tpex_margin', _fetch_tpex_margin_day)]:
        failures, _ = _repair_margin(fetcher, days, store, source, progress)
        failure_maps[source] = failures
    twse_margin = store.read('twse_margin', 'margin_balance', start, end)
    tpex_margin = store.read('tpex_margin', 'margin_balance', start, end)
    margin = _combine_margin_amounts(twse_margin, tpex_margin)
    audit = pd.DataFrame({'date': pd.to_datetime(days)})
    for label, frame in [('上市指數', taiex), ('上櫃指數', tpex), ('上市融資', twse_margin), ('上櫃融資', tpex_margin)]:
        audit[label] = audit['date'].isin(frame['date'])
    audit['完整'] = audit[['上市指數', '上櫃指數', '上市融資', '上櫃融資']].all(axis=1)
    def reason(row):
        if row['完整']:
            return '完整'
        text = []
        for label, source in [('上市融資', 'twse_margin'), ('上櫃融資', 'tpex_margin')]:
            if not row[label]:
                text.append(f"{label}：{failure_maps[source].get(row['date'].date(), '待補抓')}")
        if not row['上市指數'] or not row['上櫃指數']:
            text.append('指數日期缺漏，下次重新整理再核對月份')
        return '；'.join(text)
    audit['狀態'] = audit.apply(reason, axis=1)
    missing = int((~audit['完整']).sum())
    if missing:
        warnings.append(f'歷史範圍有 {missing} 個交易日資料未齊，缺日保留空值，下次更新繼續補抓。')
    for source, failures in failure_maps.items():
        if failures:
            warnings.append(f'{source} 本次有 {len(failures)} 日未能刷新；已有資料仍保留，詳見缺日清單。')
    return dict(update_time=now.strftime('%Y-%m-%d %H:%M:%S'), weeks=weeks,
                display_cutoff=display_cutoff, taiex=taiex, tpex=tpex, margin=margin,
                twse_margin=twse_margin, tpex_margin=tpex_margin, warnings=warnings,
                audit=audit, calendar=pd.DatetimeIndex(audit['date']))
