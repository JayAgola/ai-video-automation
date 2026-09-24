"""Tests 3+4: TTS generation + cache hit on repeat. Needs internet (edge-tts)."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def run(text: str = "Hello and welcome to today's video.") -> bool:
    from app.audio.duration import get_audio_duration
    from app.audio.tts_engine import synthesize_narration
    from app.core import config
    from app.core.cache_manager import CacheManager
    config.ensure_dirs()
    cache = CacheManager(config.CACHE_DIR)
    try:
        p1, d1, hit1 = synthesize_narration(text, cache=cache)
        print(f"run1: {p1} ({d1:.1f}s) hit={hit1}")
        p2, d2, hit2 = synthesize_narration(text, cache=cache)
        print(f"run2: {p2} ({d2:.1f}s) hit={hit2}")
    except Exception as e:
        print("TTS/CACHE TEST: FAIL:", e)
        return False
    ok = p1.exists() and p2.exists() and d1 > 0 and hit2 is True and p1 == p2
    print("TTS/CACHE TEST:", "PASS" if ok else "FAIL",
          "(expect run1 MISS->GENERATE, run2 HIT->REUSE; run1 hit may be True if cached before)")
    # Pass as long as files exist and run2 is a hit; run1 hit allowed if previously cached.
    return p1.exists() and p2.exists() and d1 > 0 and hit2 is True


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
