"""Part 2 tests: visuals + chunks + concat + resume + full E2E (TEST mode)."""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import os
os.environ.setdefault("TEST_VISUAL_MODE", "true")

from app.core import config
from app.core.cache_manager import CacheManager
from app.core.project_manager import ProjectManager


def _seed_audio(pid: str, script: dict) -> None:
    """Seed 2 short scene MP3s using cached TTS (no regen if cached)."""
    from app.audio.tts_engine import synthesize_narration
    pm = ProjectManager()
    pm.create_project(pid)
    cache = CacheManager(config.CACHE_DIR)
    for sc in script["scenes"]:
        dest = pm.audio_dir(pid) / "scene_{:03d}.mp3".format(int(sc["scene_id"]))
        if not dest.exists():
            synthesize_narration(sc["narration"], cache=cache, dest=dest)


def _script2() -> dict:
    return {
        "title": "P2 test", "description": "Part 2 test.", "tags": ["t"],
        "keywords": ["t"], "target_duration_seconds": 30, "bgm_style": "calm_ambient",
        "scenes": [
            {"scene_id": 1, "narration": "First test scene for video rendering.",
             "visual_direction": "Sunrise over calm mountains.", "estimated_duration_seconds": 10},
            {"scene_id": 2, "narration": "Second test scene for video rendering.",
             "visual_direction": "River flowing through a forest.", "estimated_duration_seconds": 10},
        ],
    }
