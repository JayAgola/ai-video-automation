"""One-command video builder: topic -> full MP4 with voice + assets/bgm BGM.

Usage:
  python make_video.py --project video_001 --topic "How to stop overthinking"
  python make_video.py --project video_002 --topic "My topic" --fresh

What it does (in order, one command):
  1. Checks ffmpeg/ffprobe, Ollama model, and assets/bgm/*.mp3 presence.
  2. If ComfyUI is unreachable it falls back to test placeholders so a real
     watchable MP4 is still produced (your current .env points to ComfyUI
     which is offline -> that was the "test mode" surprise).
  3. Runs the full pipeline: SCRIPT -> TTS -> BGM -> MIX -> VISUALS ->
     CHUNKS -> FINAL (final is re-muxed with mixed voice+BGM audio).
  4. Prints the final MP4 path + duration + which BGM was used + test_mode flag.

Flags:
  --fresh        delete the project folder first (full rebuild from scratch).
  --force-final  rebuild only the final mux (keeps chunks, fixes old no-BGM finals).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app.audio.bgm_manager import list_tracks  # noqa: E402
from app.core import config  # noqa: E402
from app.core.project_manager import ProjectManager  # noqa: E402


def check_ffmpeg() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise SystemExit(f"MISSING {tool}: install ffmpeg and add it to PATH.")
    print("ffmpeg/ffprobe OK", flush=True)


def check_bgm() -> Path:
    config.ensure_dirs()
    tracks = list_tracks()
    if not tracks:
        raise SystemExit("NO BGM: put at least one royalty-free .mp3 in assets/bgm/ then retry.")
    print(f"BGM tracks found ({len(tracks)}): " + ", ".join(t.name for t in tracks), flush=True)
    return tracks[0]


def check_ollama() -> None:
    import requests

    from app.core import config as _cfg

    try:
        r = requests.get(f"{_cfg.OLLAMA_BASE_URL}/api/tags", timeout=8)
        r.raise_for_status()
        models = [m.get("name", "") for m in r.json().get("models", [])]
    except Exception as e:
        raise SystemExit(f"Ollama OFFLINE: {type(e).__name__}: {e}. Start Ollama first.")
    want = _cfg.OLLAMA_TEXT_MODEL
    if not any(m == want or m.startswith(want + ":") or want.startswith(m) for m in models):
        raise SystemExit(f"Ollama model missing: '{want}' not installed. "
                         f"Run: ollama pull {want}. Available: {models}")
    print(f"Ollama OK: {want}", flush=True)


def pick_visual_mode(force_test: bool) -> bool:
    """Return True if we must run placeholder visuals. Never crashes the run."""
    if force_test:
        print("VISUALS: forced --test-visuals -> placeholders (TEST MODE).", flush=True)
        return True
    try:
        from app.visuals import visual_engine
        h = visual_engine.provider_health()
        if h.get("ok"):
            print(f"VISUALS: {h.get('provider')} AVAILABLE -> real AI images.")
            return False
        print(f"VISUALS: ComfyUI unreachable ({h.get('error', '')[:120]})")
        print("VISUALS: falling back to placeholders so the video still builds (TEST MODE).")
        return True
    except Exception as e:
        print(f"VISUALS: health check failed ({e}); using placeholders (TEST MODE).")
        return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="One-command video builder (voice + BGM).")
    ap.add_argument("--project", default="video_001")
    ap.add_argument("--topic", default="How to stop overthinking")
    ap.add_argument("--fresh", action="store_true", help="delete project dir first, full rebuild")
    ap.add_argument("--force-final", action="store_true",
                    help="rebuild final mux only (fixes old finals without BGM)")
    ap.add_argument("--test-visuals", action="store_true",
                    help="force placeholder images (skip ComfyUI)")
    args = ap.parse_args(argv)

    check_ffmpeg()
    check_bgm()
    check_ollama()
    use_test = pick_visual_mode(args.test_visuals)

    if args.fresh:
        pp = ProjectManager().project_path(args.project)
        if pp.exists():
            shutil.rmtree(pp)
            print(f"Project reset: deleted {pp}")

    from pipeline_main import run as run_pipeline

    # Patch config for this process only (no .env edit needed).
    if use_test:
        config.VISUAL_PROVIDER = "test"
        config.TEST_VISUAL_MODE = True

    rc = run_pipeline(args.project, args.topic,
                      force_visuals=args.fresh, force_chunks=args.fresh,
                      force_final=(args.fresh or args.force_final))
    if rc != 0:
        print("BUILD FAILED: see logs/pipeline.log. Fix the error above and re-run this same command.")
        return rc

    pm = ProjectManager()
    state = pm.load_project(args.project)
    data = state.get("data", {})
    final = Path(data.get("final_video_path", pm.final_video_path(args.project)))
    if not final.exists():
        # tolerate relative paths stored in state
        final = ROOT / str(final)
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration,size", "-of", "default=noprint_wrappers=1",
                        str(final)], capture_output=True, text=True)
    print("=" * 60)
    print(f"DONE: {final} ({final.stat().st_size / 1e6:.1f} MB)")
    print(f"duration: {data.get('final_video_duration', '?')}s | "
          f"audio: {data.get('final_audio', '?')} | BGM track: {data.get('bgm_track', '?')}")
    test_flags = [v for k, v in data.items()
                  if k.startswith("visual_meta_") and isinstance(v, dict) and v.get("test_mode")]
    print(f"visuals: {'TEST-MODE placeholders' if test_flags else 'real AI images'} "
          f"({len(test_flags)} test scenes)" if test_flags else
          "visuals: real AI images (ComfyUI)")
    print("ffprobe:", r.stdout.strip().replace("\n", " "))
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
