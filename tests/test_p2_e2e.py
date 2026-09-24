"""Test 8: full Part 2 E2E in TEST_VISUAL_MODE (Part1 steps + visuals + video)."""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path
os.environ["TEST_VISUAL_MODE"] = "true"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core import config
from app.core.project_manager import ProjectManager
from pipeline_main import run

PID = "test_p2_e2e"
config.ensure_dirs()
pm = ProjectManager()
pm.create_project(PID)
sm = pm.state_manager(PID)
sm.create_project(PID)
script = {"title": "P2 E2E", "description": "Full part2 e2e.", "tags": ["t"],
          "keywords": [], "target_duration_seconds": 30, "bgm_style": "calm_ambient",
          "scenes": [
              {"scene_id": 1, "narration": "Welcome to the end to end video test.",
               "visual_direction": "Sunrise over calm mountains.",
               "estimated_duration_seconds": 10},
              {"scene_id": 2, "narration": "Images, chunks and final video are rendered.",
               "visual_direction": "River flowing through a forest.",
               "estimated_duration_seconds": 10}]}
pm.script_path(PID).write_text(json.dumps(script), encoding="utf-8")
sm.update({"topic": "p2 e2e"})
sm.mark_completed("SCRIPT")
rc = run(PID, "p2 e2e")
state = sm.load()
final = pm.final_video_path(PID)
assert rc == 0, state.get("data", {}).get("last_error_FINAL_VIDEO")
assert final.exists() and final.stat().st_size > 0
assert state["status"] == "COMPLETED", state
assert all(s in state["completed_steps"] for s in
           ["SCRIPT", "TTS", "BGM", "MIX", "VISUAL_GENERATION", "SCENE_CHUNKS", "FINAL_VIDEO"])
rc2 = run(PID, "p2 e2e")
assert rc2 == 0
print("P2-E2E: PASS final={} ({:.1f}s) + resume no-op PASS".format(
    final, state["data"].get("final_video_duration", 0)))
