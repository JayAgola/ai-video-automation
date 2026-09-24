"""Deterministic TEST research provider. Fake metadata, clearly labelled.

No internet needed. NEVER presented as real YouTube data.
"""
from __future__ import annotations

import hashlib
from typing import Any

TEST_LABEL = "TEST DATA — NOT REAL YOUTUBE DATA"

TOPIC_POOL = [
    ("Why Your Brain Gets Louder at Night", "overthinking at night", "night anxiety"),
    ("Marcus Aurelius on Overthinking", "stoicism overthinking", "stoic habits"),
    ("Stop People Pleasing With One Question", "people pleasing psychology", "boundaries"),
    ("The 5-Minute Discipline Reset", "discipline psychology", "procrastination"),
    ("Confidence Is a Skill, Not a Trait", "confidence psychology", "self esteem"),
    ("Emotional Control in 3 Breaths", "emotional control psychology", "calm mind"),
    ("Attention Is Your Rarest Currency", "attention focus psychology", "deep work"),
    ("Handling Criticism Like a Stoic", "handling criticism stoicism", "resilience"),
    ("Loneliness vs Being Alone", "loneliness psychology", "solitude"),
    ("Procrastination Is Fear in Disguise", "procrastination psychology", "action"),
    ("Social Anxiety Shrinks With Exposure", "social anxiety psychology", "courage"),
    ("Control Your Reactions, Own Your Day", "controlling reactions stoicism", "anger"),
]


class TestResearchProvider:
    name = "test"
    test_data = True

    def health(self) -> dict[str, Any]:
        return {"ok": True, "provider": "test", "status": "AVAILABLE",
                "note": TEST_LABEL}

    def search(self, query: str, max_results: int = 25, region: str = "US",
               language: str = "en") -> list[dict[str, Any]]:
        seed = int(hashlib.sha256(query.encode()).hexdigest()[:8], 16)
        out: list[dict[str, Any]] = []
        for i in range(min(max_results, 12)):
            title, kw1, kw2 = TOPIC_POOL[(seed + i * 3) % len(TOPIC_POOL)]
            vid = "test_{:08x}{:02d}".format(seed % 0xFFFFFFFF, i)
            views = 50000 + ((seed >> (i % 8)) % 900000)
            out.append({
                "video_id": vid, "title": "{} — {}".format(title, query.title()),
                "channel_title": "Test Channel {}".format((seed + i) % 5),
                "published_at": "2026-0{}-1{}T10:00:00Z".format((i % 8) + 1, i % 9),
                "view_count": views, "like_count": views // 25,
                "comment_count": views // 300,
                "duration_sec": 420 + i * 37,
                "channel_subscribers": None, "query": query, "source": "test",
                "test_data": True, "test_label": TEST_LABEL,
                "description_snippet": "Deterministic fixture about {} and {}.".format(kw1, kw2),
            })
        return out
