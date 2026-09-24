"""End-to-end Part 1 pipeline on a tiny 2-scene script (exercises orchestrator,
TTS, BGM, MIX, state, resume). No Ollama needed (SCRIPT pre-seeded)."""
from __future__ import annotations
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core import config
from app.core.project_manager import ProjectManager
from pipeline_main import run

PID = "test_e2e"
config.ensure_dirs()
pm = ProjectManager()
pm.create_project(PID)
sm = pm.state_manager(PID)
sm.create_project(PID)  # fresh state
script = {
    "title": "E2E test video", "description": "Pipeline end to end check.",
    "tags": ["test", "automation"], "keywords": ["e2e"],
    "target_duration_seconds": 30, "bgm_style": "calm_ambient",
    "scenes": [
        {"scene_id": 1, "narration": "Hello and welcome to this end to end test.",
         "visual_direction": "Bright studio background.", "estimated_duration_seconds": 10},
        {"scene_id": 2, "narration": "The pipeline mixes voiceover with soft music.",
         "visual_direction": "Sound waves over a calm lake.", "estimated_duration_seconds": 10},
    ],
}
pm.script_path(PID).write_text(json.dumps(script, indent=2), encoding="utf-8")
sm.update({"topic": "e2e"})
sm.mark_completed("SCRIPT")
rc = run(PID, "e2e")
state = sm.load()
audio = pm.audio_dir(PID)
expected = ["scene_001.mp3", "scene_002.mp3", "voiceover.mp3",
            "background_music.mp3", "mixed_audio.mp3"]
missing = [f for f in expected if not (audio / f).exists()]
ok = rc == 0 and not missing and state["status"] == "COMPLETED"
print("E2E:", "PASS" if ok else f"FAIL rc={rc} missing={missing} status={state['status']}")
# Resume: second run must be a no-op success.
rc2 = run(PID, "e2e")
print("E2E-RESUME:", "PASS" if rc2 == 0 else f"FAIL rc={rc2}")
raise SystemExit(0 if (ok and rc2 == 0) else 1)
