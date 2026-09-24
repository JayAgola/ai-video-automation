"""Part 3 tests B: gap/originality/SEO/resume/api-fail + full P3 E2E."""
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
from app.core.project_manager import ProjectManager
from app.research import topic_scorer as ts
from app.research import seo_engine as seo
from app.research.test_provider import TestResearchProvider, TEST_LABEL
from pipeline_steps_p3 import step_research, step_topics
from pipeline_steps_p3b import step_ranking
from pipeline_steps_p3c import step_select, step_seo
from test_p3_a import FakeClient

config.ensure_dirs()
PID = "test_p3_all"
pm = ProjectManager()
sm = pm.state_manager(PID)
prov = TestResearchProvider()

tr = step_research(pm, sm, ["stoicism anxiety", "discipline psychology"], force=True, provider=prov)
cd = step_topics(pm, sm, tr, FakeClient(), 5)
rk = step_ranking(pm, sm, cd, tr)
assert all(c.get("content_gap") for c in rk)
print("T7 content gap: PASS")

copy = ts.originality_check("Exact Same Words Here Alpha Beta Gamma Delta",
                            ["Exact Same Words Here Alpha Beta Gamma Delta"])
assert copy["source_similarity_warning"] is True
print("T8 originality guard: PASS")

sel = rk[0]
kws = sel.get("search_keywords", ["overthinking"])
pkg = seo.generate_seo(sel["topic"], kws, config.TARGET_AUDIENCE, sel.get("angle", ""))
assert 3 <= len(pkg["title_options"]) <= 5 and pkg["description"] and pkg["tags"] and pkg["hashtags"]
assert "score" in seo.score_title(pkg["title_options"][0], kws)
assert len(seo.thumbnail_concepts(sel["topic"], kws)["thumbnail_concepts"]) == 3
print("T9 SEO: PASS")

sel2 = step_select(pm, sm, rk, 0)
step_seo(pm, sm, sel2)
before = (pm.project_path(PID) / "research" / "trends.json").stat().st_mtime
step_research(pm, sm, ["stoicism anxiety"])
assert (pm.project_path(PID) / "research" / "trends.json").stat().st_mtime == before
print("T10 resume: PASS")

from app.research import research_engine as re
yh = re.research_health("youtube")
assert yh["ok"] is False, yh
from app.research.youtube_provider import YouTubeProvider
try:
    YouTubeProvider(api_key="", enabled=False).search("x")
    raise AssertionError("should have raised")
except RuntimeError as e:
    assert "unavailable" in str(e).lower() or "manual" in str(e).lower()
print("T11 API failure graceful: PASS ({})".format(yh.get("status")))
assert TEST_LABEL in TestResearchProvider().search("q")[0].get("test_label", "")
rp = pm.project_path(PID) / "research" / "research_report.md"
assert rp.exists()
print("T12 P3 E2E (research->topics->rank->select->seo+report): PASS")
print("P3-B: ALL PASS")
