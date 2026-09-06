from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
import re

import numpy as np
import pandas as pd

from .config import COOLING_TERMS, FINANCING_TERMS, PILLARS, RISK_BANDS, RISK_TERMS


@dataclass
class ArticleScore:
    risk_score: float
    evidence: str
    risk_hits: list[str]
    cooling_hits: list[str]


def _find_terms(text: str, mapping: dict[int, list[str]]) -> list[tuple[int, str]]:
    text = text.lower()
    found: list[tuple[int, str]] = []
    for points, terms in mapping.items():
        for term in terms:
            if term in text:
                found.append((points, term))
    return found


def score_article(title: str, summary: str, pillar: str) -> ArticleScore:
    text = f"{title} {summary}".lower()
    risk_hits = _find_terms(text, RISK_TERMS)
    cooling_hits = _find_terms(text, COOLING_TERMS)

    score = 35.0
    score += sum(points for points, _ in risk_hits)
    score -= sum(points for points, _ in cooling_hits)

    if pillar == "financing":
        score += sum(points for points, _ in _find_terms(text, FINANCING_TERMS))

    score = float(np.clip(score, 0, 100))
    evidence_parts = []
    if risk_hits:
        evidence_parts.append("風險: " + ", ".join(term for _, term in risk_hits[:4]))
    if cooling_hits:
        evidence_parts.append("需求/缺貨: " + ", ".join(term for _, term in cooling_hits[:4]))
    if not evidence_parts:
        evidence_parts.append("未命中強訊號詞")

    return ArticleScore(
        risk_score=score,
        evidence="；".join(evidence_parts),
        risk_hits=[term for _, term in risk_hits],
        cooling_hits=[term for _, term in cooling_hits],
    )


def enrich_news(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    scores = [score_article(r.title, r.summary, r.pillar) for r in out.itertuples()]
    out["risk_score"] = [s.risk_score for s in scores]
    out["evidence"] = [s.evidence for s in scores]
    out["risk_hits"] = [s.risk_hits for s in scores]
    out["cooling_hits"] = [s.cooling_hits for s in scores]
    return out


def _recency_weight(dt, half_life_days: float = 10.0) -> float:
    if pd.isna(dt):
        return 0.3
    if getattr(dt, "tzinfo", None) is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400)
    return max(0.15, math.exp(-math.log(2) * age_days / half_life_days))


def pillar_score(df: pd.DataFrame, pillar_key: str) -> tuple[float, float, int]:
    if df.empty:
        return 35.0, 0.0, 0
    errors = df.get("error", pd.Series(False, index=df.index)).fillna(False).astype(bool)
    clean = df[(df["pillar"] == pillar_key) & (~errors)].copy()
    if clean.empty:
        return 35.0, 0.0, 0

    clean["recency_weight"] = clean["published"].apply(_recency_weight)
    clean["combined_weight"] = clean["recency_weight"] * clean["source_weight"].clip(lower=0.25)
    denom = clean["combined_weight"].sum()
    score = float((clean["risk_score"] * clean["combined_weight"]).sum() / denom) if denom else 35.0

    # 覆蓋度 + 來源品質，作為信心分數。
    article_coverage = min(1.0, len(clean) / 20.0)
    source_quality = float(clean["source_weight"].mean())
    confidence = 100 * (0.6 * article_coverage + 0.4 * source_quality)
    return float(np.clip(score, 0, 100)), float(np.clip(confidence, 0, 100)), len(clean)


def risk_band(score: float) -> str:
    s = int(round(score))
    for lo, hi, label in RISK_BANDS:
        if lo <= s <= hi:
            return label
    return RISK_BANDS[-1][2]


def compute_hard_flags(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []
    text = (df["title"].fillna("") + " " + df["summary"].fillna("")).str.lower()

    def count_matches(patterns: list[str], companies: list[str] | None = None) -> tuple[int, list[str]]:
        mask = pd.Series(False, index=df.index)
        for p in patterns:
            mask = mask | text.str.contains(re.escape(p), regex=True)
        if companies:
            company_mask = pd.Series(False, index=df.index)
            for c in companies:
                company_mask = company_mask | text.str.contains(re.escape(c.lower()), regex=True)
            mask = mask & company_mask
        hits = df.loc[mask, "title"].drop_duplicates().head(4).tolist()
        return int(mask.sum()), hits

    rules = [
        (
            "Hyperscaler 下修 AI Capex",
            ["cut capex", "cuts capex", "capex cut", "slows capex", "capital spending cut"],
            ["microsoft", "alphabet", "google", "amazon", "meta", "oracle"],
            2,
        ),
        (
            "AI 核心供應商下修需求展望",
            ["lowers guidance", "cuts guidance", "guidance cut", "demand slowdown", "weaker demand"],
            ["nvidia", "broadcom", "tsmc"],
            2,
        ),
        (
            "HBM / CoWoS 由缺轉鬆",
            ["oversupply", "capacity exceeds demand", "supply catches up", "inventory correction", "underutilization"],
            ["hbm", "cowos", "sk hynix", "micron", "samsung", "tsmc"],
            1,
        ),
        (
            "Lumentum + Coherent 同步轉弱",
            ["lowers guidance", "cuts guidance", "demand slowdown", "inventory correction", "weaker demand"],
            ["lumentum", "coherent"],
            2,
        ),
        (
            "GPU 交期 / 租賃價格快速下降",
            ["lead time shrinks", "lead times shrink", "rental price decline", "gpu rental prices fall", "price cut"],
            ["gpu", "nvidia", "coreweave"],
            1,
        ),
        (
            "AI 基建融資壓力或專案取消",
            ["default", "refinancing stress", "funding shortfall", "cancelled project", "canceled project", "liquidity crunch"],
            None,
            1,
        ),
    ]

    flags = []
    for name, patterns, companies, threshold in rules:
        count, headlines = count_matches(patterns, companies)
        flags.append(
            {
                "name": name,
                "active": count >= threshold,
                "count": count,
                "threshold": threshold,
                "headlines": headlines,
            }
        )
    return flags


def aggregate_score(pillar_scores: dict[str, float], market_heat: float | None = None, hard_flags: list[dict] | None = None) -> float:
    weighted = 0.0
    total_weight = 0.0
    for key, cfg in PILLARS.items():
        if key == "market" and market_heat is not None:
            s = market_heat
        else:
            s = pillar_scores.get(key, 35.0)
        weighted += s * cfg["weight"]
        total_weight += cfg["weight"]
    score = weighted / total_weight if total_weight else 35.0

    # 3 個以上硬紅旗，最低升到橘燈區；5 個以上則至少紅燈。
    if hard_flags:
        active = sum(1 for f in hard_flags if f["active"])
        if active >= 5:
            score = max(score, 76.0)
        elif active >= 3:
            score = max(score, 62.0)
    return float(np.clip(score, 0, 100))
