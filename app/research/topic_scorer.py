"""Deterministic topic scoring. Formula (documented, internal heuristic):

score = 0.25*trend + 0.20*freshness + 0.20*search_intent + 0.15*engagement
        + 0.10*content_gap + 0.10*originality - competition_penalty
competition_penalty = competition/10 (competition 0-100).

Does NOT predict views; ranks candidates for prioritization only.
"""
from __future__ import annotations

import re


def search_intent(text: str, keywords: list) -> float:
    hits = sum(1 for k in keywords if k.lower() in text.lower())
    return min(100.0, 25.0 * hits + 30.0)


def competition_for(records: list, topic_kw: list) -> dict:
    from app.research.trend_discovery import metrics
    if not records:
        return {"level": "LOW", "score": 15.0,
                "reason": "No comparable videos found (estimated low)."}
    rel = 0
    big = 0
    for r in records:
        m = metrics(r)
        overlap = len(set(topic_kw) & set(m["keywords"]))
        if overlap >= 2:
            rel += 1
            if r["view_count"] > 500000:
                big += 1
    score = min(100.0, rel * 12.0 + big * 8.0)
    level = "LOW" if score < 35 else ("MEDIUM" if score < 65 else "HIGH")
    return {"level": level, "score": round(score, 1),
            "reason": "{} related videos, {} high-view; estimated {}.".format(rel, big, level.lower())}


def originality_check(topic: str, source_titles: list) -> dict:
    tt = set(re.findall(r"[a-z]{4,}", topic.lower()))
    warn = False
    for s in source_titles:
        st = set(re.findall(r"[a-z]{4,}", s.lower()))
        if tt and len(tt & st) / max(len(tt), 1) > 0.8:
            warn = True
            break
    return {"status": "PASS" if not warn else "REVIEW",
            "source_similarity_warning": warn}


def score_candidate(cand: dict, agg_metrics: dict) -> dict:
    comp = cand.get("competition", {})
    comps = {
        "trend": float(agg_metrics.get("trend_score", 50)),
        "freshness": float(agg_metrics.get("freshness_score", 50)),
        "search_intent": float(cand.get("search_intent", 60)),
        "engagement": float(agg_metrics.get("engagement_score", 50)),
        "content_gap": float(cand.get("content_gap_score", 70)),
        "originality": 95.0 if not cand.get("originality", {}).get(
            "source_similarity_warning", False) else 45.0,
        "competition": float(comp.get("score", 40)),
    }
    score = (0.25 * comps["trend"] + 0.20 * comps["freshness"]
             + 0.20 * comps["search_intent"] + 0.15 * comps["engagement"]
             + 0.10 * comps["content_gap"] + 0.10 * comps["originality"]
             - comps["competition"] / 10.0)
    return {"score": round(max(score, 0.0), 1), "components": comps}
