"""Part 3 tests A: provider/cache/normalize/metrics/topics/ranking."""
from __future__ import annotations
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import os
os.environ.setdefault("TEST_RESEARCH_MODE", "true")
os.environ.setdefault("RESEARCH_PROVIDER", "test")
from app.core import config
from app.core.cache_manager import CacheManager
from app.core.project_manager import ProjectManager
from app.research import research_engine as re
from app.research import trend_discovery as td
from app.research import topic_scorer as ts
from app.research import topic_generator as tg
from app.research.test_provider import TestResearchProvider

config.ensure_dirs()
PID = "test_p3_all"
pm = ProjectManager()
pm.create_project(PID)
sm = pm.state_manager(PID)
sm.create_project(PID)
cache = CacheManager(config.CACHE_DIR)
prov = TestResearchProvider()

h = re.research_health("test")
assert h["ok"] and h["status"] == "AVAILABLE", h
print("T1 provider health: PASS")

raw1, hit1 = re.cached_search(prov, "stoicism anxiety", cache, 10, "US", "en", force=True)
assert hit1 is False and len(raw1) > 0
raw2, hit2 = re.cached_search(prov, "stoicism anxiety", cache, 10, "US", "en")
assert hit2 is True and raw1 == raw2
print("T2 cache MISS/HIT: PASS ({} records)".format(len(raw1)))

n = td.normalize(raw1[0])
assert set(("video_id", "title", "view_count", "query", "source")) <= set(n)
print("T3 normalization: PASS")

m1 = td.metrics(n)
assert m1 == td.metrics(td.normalize(raw1[0]))
assert all(0 <= m1[k] <= 100 for k in ("trend_score", "freshness_score", "engagement_score"))
print("T4 metrics: PASS {}".format({k: m1[k] for k in
      ("trend_score", "freshness_score", "engagement_score")}))


class FakeClient:
    def generate(self, prompt, options=None):
        from app.llm.ollama_client import OllamaResult
        items = [{"topic_id": "t{}".format(i), "topic": "Original Topic {}".format(i),
                  "core_question": "Q{}".format(i), "audience_problem": "P",
                  "angle": "practical steps", "why_now": "rising",
                  "search_keywords": ["overthinking", "stoicism"],
                  "content_gap": "practical steps", "estimated_competition": "MEDIUM",
                  "originality_notes": "own wording"} for i in range(5)]
        return OllamaResult(ok=True, text=json.dumps(items))


trends = td.discover_trends([td.normalize(r) for r in raw1])
summary = tg.build_summary(trends, trends["top_patterns"], config.CHANNEL_NICHE)
cands = tg.generate_candidates(summary, trends, trends["top_patterns"], FakeClient(), 5)
assert len(cands) == 5 and all("topic" in c for c in cands)
print("T5 topic generation: PASS")

kw = {"trend_score": 60, "freshness_score": 60, "engagement_score": 60}
base = dict(cands[0], competition={"score": 40},
            originality={"source_similarity_warning": False},
            search_intent=60, content_gap_score=70)
assert ts.score_candidate(base, kw) == ts.score_candidate(dict(base), dict(kw))
print("T6 ranking deterministic: PASS")
print("P3-A: ALL PASS")
