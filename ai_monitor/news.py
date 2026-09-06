from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import quote_plus

import feedparser
import pandas as pd
import requests

from .config import DEFAULT_SOURCE_WEIGHT, SOURCE_WEIGHTS

USER_AGENT = "AI-Overheat-Monitor/1.0 (+https://github.com/)"


def _source_weight(source: str) -> float:
    s = (source or "").lower()
    for key, weight in SOURCE_WEIGHTS.items():
        if key in s:
            return weight
    return DEFAULT_SOURCE_WEIGHT


def _entry_datetime(entry) -> datetime:
    parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if parsed:
        return datetime(*parsed[:6], tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def _entry_source(entry) -> str:
    src = getattr(entry, "source", None)
    if isinstance(src, dict):
        return src.get("title", "Unknown")
    if src and hasattr(src, "title"):
        return src.title
    title = getattr(entry, "title", "")
    if " - " in title:
        return title.rsplit(" - ", 1)[-1]
    return "Unknown"


def fetch_google_news(query: str, days: int = 30, max_items: int = 20, language: str = "en-US") -> list[dict]:
    q = f"{query} when:{int(days)}d"
    url = (
        "https://news.google.com/rss/search?"
        f"q={quote_plus(q)}&hl={language}&gl=US&ceid=US:en"
    )
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=12)
    response.raise_for_status()
    feed = feedparser.parse(response.content)
    items: list[dict] = []
    for entry in feed.entries[:max_items]:
        source = _entry_source(entry)
        items.append(
            {
                "title": getattr(entry, "title", "").strip(),
                "summary": getattr(entry, "summary", "").strip(),
                "link": getattr(entry, "link", ""),
                "published": _entry_datetime(entry),
                "source": source,
                "source_weight": _source_weight(source),
                "query": query,
            }
        )
    return items


def fetch_pillar_news(pillar_key: str, queries: Iterable[str], days: int, max_items_per_query: int) -> pd.DataFrame:
    rows: list[dict] = []
    for query in queries:
        try:
            rows.extend(fetch_google_news(query, days=days, max_items=max_items_per_query))
        except Exception as exc:  # network failures should not kill the app
            rows.append(
                {
                    "title": f"[抓取失敗] {query}",
                    "summary": str(exc),
                    "link": "",
                    "published": datetime.now(timezone.utc),
                    "source": "system",
                    "source_weight": 0.0,
                    "query": query,
                    "error": True,
                }
            )

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    if "error" not in df.columns:
        df["error"] = False
    df["error"] = df["error"].fillna(False).astype(bool)
    df["pillar"] = pillar_key
    # 同標題去重，保留較高品質來源。
    df = df.sort_values(["source_weight", "published"], ascending=[False, False])
    df = df.drop_duplicates(subset=["title"], keep="first")
    return df.sort_values("published", ascending=False).reset_index(drop=True)
