"""Audio duration utility (mutagen primary, ffprobe/pydub fallback)."""
from __future__ import annotations

from pathlib import Path


def get_audio_duration(path: Path | str) -> float:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Audio not found: {p}")
    # 1) mutagen (pure python, no ffmpeg needed)
    try:
        from mutagen import File as MutagenFile
        audio = MutagenFile(str(p))
        if audio is not None and getattr(audio, "info", None) and audio.info.length:
            return float(audio.info.length)
    except Exception:
        pass
    # 2) ffprobe
    try:
        import subprocess, json
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", str(p)],
            capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:
        pass
    # 3) pydub (needs ffmpeg)
    try:
        from pydub import AudioSegment
        return len(AudioSegment.from_file(str(p))) / 1000.0
    except Exception as e:
        raise RuntimeError(f"Cannot determine duration of {p}: {e}")
