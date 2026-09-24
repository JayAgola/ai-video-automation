"""Offline validation: state/cache/resume/script-validation without Ollama/TTS net."""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ok = True
# 1. state manager crash-safe + resume logic
from app.core.project_manager import ProjectManager
from app.core import config
config.ensure_dirs()
pm = ProjectManager()
pm.create_project("verify_offline")
sm = pm.state_manager("verify_offline")
sm.create_project("verify_offline")
sm.mark_started("SCRIPT"); sm.mark_completed("SCRIPT")
sm.mark_started("TTS"); sm.mark_completed("TTS")
sm.mark_started("BGM"); sm.mark_completed("BGM")
sm.mark_started("MIX"); sm.mark_failed("MIX", "simulated")
r = sm.resume()
assert r["_next_step"] == "MIX", r
assert set(("SCRIPT", "TTS", "BGM")) <= set(r["completed_steps"])
print("state/resume: PASS")
# 2. cache key includes voice
from app.core.cache_manager import CacheManager
cm = CacheManager(config.CACHE_DIR)
assert cm.audio_key("hello", "v1") != cm.audio_key("hello", "v2")
assert cm.audio_key("hello", "v1") == cm.audio_key("hello", "v1")
print("cache keys: PASS")
# 3. script validation + repair
from app.script import script_engine
good = {"title": "T", "description": "D", "tags": ["a"], "keywords": ["k"],
        "target_duration_seconds": 210, "bgm_style": "calm_ambient",
        "scenes": [{"scene_id": 1, "narration": "Hi there.",
                    "visual_direction": "Calm lake.", "estimated_duration_seconds": 20}]}
script_engine.validate_script(good)
print("script validation: PASS")
repaired = script_engine.extract_json('```json\n{"a": 1}\n```')
assert repaired == '{"a": 1}', repaired
print("json repair: PASS")
# 4. idempotent project creation
p1 = pm.create_project("verify_offline")
p2 = pm.create_project("verify_offline")
assert p1 == p2
print("idempotent project: PASS")
# 5. imports incl. pipeline entrypoint
import pipeline, pipeline_main, pipeline_steps
print("imports: PASS")
print("OFFLINE VERIFY: ALL PASS")
