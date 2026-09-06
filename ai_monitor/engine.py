from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from .config import MARKET_TICKERS, PILLARS
from .market import fetch_ticker_metrics, market_heat_score
from .news import fetch_pillar_news
from .scoring import aggregate_score, compute_hard_flags, enrich_news, pillar_score, risk_band


def run_monitor(days: int = 30, max_items_per_query: int = 12, fetch_market: bool = True) -> dict:
    frames = []
    for key, cfg in PILLARS.items():
        if key == "market":
            continue
        frames.append(fetch_pillar_news(key, cfg["queries"], days=days, max_items_per_query=max_items_per_query))

    news = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    news = enrich_news(news) if not news.empty else news

    pillar_scores: dict[str, float] = {}
    pillar_confidence: dict[str, float] = {}
    pillar_counts: dict[str, int] = {}
    for key in PILLARS:
        if key == "market":
            continue
        score, confidence, count = pillar_score(news, key)
        pillar_scores[key] = score
        pillar_confidence[key] = confidence
        pillar_counts[key] = count

    market_df = fetch_ticker_metrics(MARKET_TICKERS) if fetch_market else pd.DataFrame()
    market_heat = market_heat_score(market_df) if fetch_market else 35.0
    pillar_scores["market"] = market_heat
    pillar_confidence["market"] = 75.0 if not market_df.empty else 0.0
    pillar_counts["market"] = len(market_df)

    flags = compute_hard_flags(news)
    total = aggregate_score(pillar_scores, market_heat=market_heat, hard_flags=flags)

    return {
        "timestamp": datetime.now(timezone.utc),
        "score": total,
        "band": risk_band(total),
        "pillar_scores": pillar_scores,
        "pillar_confidence": pillar_confidence,
        "pillar_counts": pillar_counts,
        "hard_flags": flags,
        "news": news,
        "market": market_df,
    }
