"""Test 7: resume — scene1/2 done, scene3 failed; rerun retries only scene3."""
from __future__ import annotations
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.core import config
from app.core.project_manager import ProjectManager
from pipeline_steps_p2 import step_visuals

config.ensure_dirs()
PID = "test_p2_resume"
pm = ProjectManager()
pm.create_project(PID)
sm = pm.state_manager(PID)
sm.create_project(PID)
script = {"title": "r", "description": "r", "tags": ["t"], "keywords": [],
          "target_duration_seconds": 30, "bgm_style": "calm_ambient",
          "scenes": [
              {"scene_id": 1, "narration": "One.", "visual_direction": "Lake.",
               "estimated_duration_seconds": 8},
              {"scene_id": 2, "narration": "Two.", "visual_direction": "Hill.",
               "estimated_duration_seconds": 8},
              {"scene_id": 3, "narration": "Three.", "visual_direction": "Sky.",
               "estimated_duration_seconds": 8}]}
pm.script_path(PID).write_text(json.dumps(script), encoding="utf-8")
# Simulate: scenes 1-2 completed, scene 3 failed.
from app.visuals import visual_engine
from app.visuals.test_provider import TestImageProvider
from app.core.cache_manager import CacheManager
cache = CacheManager(config.CACHE_DIR)
prov = TestImageProvider()
for sc in script["scenes"][:2]:
    visual_engine.generate_scene_image(PID, sc, script, pm.visuals_dir(PID), cache, prov)
sm.save({**sm.load(), "data": {**sm.load()["data"],
         "visuals": {"scene_001": "COMPLETED", "scene_002": "COMPLETED",
                     "scene_003": "FAILED"}}})
before = sorted(p.stat().st_mtime for p in pm.visuals_dir(PID).glob("*.png"))
res = step_visuals(pm, sm, script, provider=prov)
assert set(res) == {1, 2, 3}
after = sorted(p.stat().st_mtime for p in pm.visuals_dir(PID).glob("*.png"))
assert (pm.visuals_dir(PID) / "scene_001.png").stat().st_mtime == before[0]
assert (pm.visuals_dir(PID) / "scene_002.png").stat().st_mtime == before[1]
assert sm.load()["data"]["visuals"]["scene_003"] == "COMPLETED"
assert "VISUAL_GENERATION" in sm.load()["completed_steps"]
print("P2-RESUME: PASS (scenes 1-2 skipped, scene 3 retried)")
