"""Tests 6+7: BGM detection + mix. Needs one MP3 in assets/bgm/ and ffmpeg (or pydub)."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def run() -> bool:
    from app.audio.audio_mixer import mix_voice_bgm
    from app.audio.bgm_manager import list_tracks, prepare_bgm, select_track
    from app.audio.duration import get_audio_duration
    from app.audio.tts_engine import synthesize_narration
    from app.core import config
    config.ensure_dirs()
    tracks = list_tracks()
    print("bgm tracks:", [t.name for t in tracks])
    if not tracks:
        print("BGM TEST: FAIL — place one royalty-free MP3 in assets/bgm/")
        return False
    try:
        voice, _, _ = synthesize_narration("This is a mix test.", cache=None)
        bgm_dest = Path("projects/test_bgm/audio/background_music.mp3")
        prepare_bgm(select_track(deterministic=True, seed="test_bgm"), bgm_dest,
                    get_audio_duration(voice))
        out = Path("projects/test_bgm/audio/mixed_audio.mp3")
        mix_voice_bgm(voice, bgm_dest, out)
        ok = out.exists() and get_audio_duration(out) > 0
        print("MIX TEST:", "PASS" if ok else "FAIL", str(out))
        return ok
    except Exception as e:
        print("BGM/MIX TEST: FAIL:", e)
        return False


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
