"""Research engine part B: normalize + metrics + trends (imported by engine)."""
from __future__ import annotations
import datetime
import re

STOPWORDS = set("the a an and or of to in on for with at by how why what when is are do does".split())


def normalize(rec: dict) -> dict:
    return {
        "video_id": str(rec.get("video_id", "")),
        "title": str(rec.get("title", "")),
        "channel_title": str(rec.get("channel_title", "")),
        "published_at": str(rec.get("published_at", "")),
        "view_count": int(rec.get("view_count", 0) or 0),
        "like_count": int(rec.get("like_count", 0) or 0),
        "comment_count": int(rec.get("comment_count", 0) or 0),
        "duration_sec": int(rec.get("duration_sec", 0) or 0),
        "channel_subscribers": rec.get("channel_subscribers"),
        "query": str(rec.get("query", "")),
        "source": str(rec.get("source", "")),
        "test_data": bool(rec.get("test_data", False)),
    }


def _age_days(published_at: str) -> float:
    try:
        dt = datetime.datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        return max((now - dt).total_seconds() / 86400.0, 0.5)
    except Exception:
        return 365.0


def _keywords(title: str) -> list:
    return [w for w in re.findall(r"[a-z]{4,}", title.lower()) if w not in STOPWORDS]


def metrics(rec: dict) -> dict:
    views = rec["view_count"]
    age = _age_days(rec["published_at"])
    vpd = views / age
    views_day = min(100.0, 100.0 * vpd / 50000.0)
    likes = rec["like_count"] / max(views, 1)
    comments = rec["comment_count"] / max(views, 1)
    engagement = min(100.0, likes * 2000.0 + comments * 8000.0)
    freshness = max(0.0, 100.0 - age / 7.3)
    trend = 0.5 * min(100.0, 100.0 * views / 1000000.0) + 0.5 * views_day
    return {"views_per_day": round(vpd, 1),
            "trend_score": round(min(trend, 100.0), 1),
            "freshness_score": round(freshness, 1),
            "engagement_score": round(min(engagement, 100.0), 1),
            "keywords": _keywords(rec["title"])}


def discover_trends(records: list) -> dict:
    from collections import Counter
    kws = Counter()
    for r in records:
        kws.update(metrics(r)["keywords"])
    scored = sorted(records, key=lambda r: metrics(r)["trend_score"], reverse=True)[:5]
    return {"total": len(records),
            "top_keywords": [{"keyword": k, "mentions": c} for k, c in kws.most_common(15)],
            "top_patterns": [s["title"] for s in scored],
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
