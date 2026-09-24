"""BGM manager: find/select/prep royalty-free tracks. Never downloads anything."""
from __future__ import annotations

import hashlib
import random
import shutil
import subprocess
from pathlib import Path

from app.audio.duration import get_audio_duration
from app.core import config
from app.core.logger import log

SUPPORTED_EXTS = {".mp3", ".wav", ".ogg", ".m4a"}


def list_tracks(bgm_dir: Path | str | None = None) -> list[Path]:
    d = Path(bgm_dir) if bgm_dir else config.BGM_DIR
    if not d.exists():
        return []
    return sorted(p for p in d.iterdir()
                  if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS)


def select_track(bgm_style: str = "", deterministic: bool = True,
                 seed: str = "default",
                 bgm_dir: Path | str | None = None) -> Path:
    """Deterministic selection by default (hash of seed+style) for reproducibility."""
    tracks = list_tracks(bgm_dir)
    if not tracks:
        raise FileNotFoundError(
            f"No BGM tracks found in {bgm_dir or config.BGM_DIR}. "
            "Place royalty-free MP3 files in assets/bgm/ (do NOT use YouTube rips).")
    if deterministic:
        h = int(hashlib.sha256(f"{seed}||{bgm_style}".encode()).hexdigest(), 16)
        track = tracks[h % len(tracks)]
    else:
        track = random.choice(tracks)
    log("BGM", f"Selected {track.name} (style={bgm_style or 'any'})")
    return track


def _ffmpeg_loop_trim(src: Path, dest: Path, target_sec: float) -> bool:
    try:
        cmd = ["ffmpeg", "-y", "-v", "error",
               "-stream_loop", "-1", "-i", str(src),
               "-t", f"{target_sec:.2f}", "-c:a", "libmp3lame", "-b:a", "192k",
               str(dest)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        return r.returncode == 0 and dest.exists()
    except Exception:
        return False


def _pydub_loop_trim(src: Path, dest: Path, target_sec: float) -> None:
    from pydub import AudioSegment
    audio = AudioSegment.from_file(str(src))
    target_ms = int(target_sec * 1000)
    if len(audio) < target_ms:
        loops = target_ms // max(len(audio), 1) + 1
        audio = audio * loops
    (audio[:target_ms]).export(str(dest), format="mp3", bitrate="192k")


def prepare_bgm(track: Path, dest: Path, target_sec: float) -> tuple[Path, float]:
    """Loop or trim track to target_sec without altering the original. Returns (dest, duration)."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if target_sec <= 0:
        raise ValueError("target_sec must be > 0")
    src_dur = get_audio_duration(track)
    # Near-equal duration: plain copy (avoid re-encode).
    if abs(src_dur - target_sec) < 0.5:
        if not dest.exists():
            shutil.copyfile(str(track), str(dest))
        log("BGM", f"Prepared {dest.name} ({target_sec:.1f}s, copied)")
        return dest, get_audio_duration(dest)
    ok = _ffmpeg_loop_trim(track, dest, target_sec)
    if not ok:
        _pydub_loop_trim(track, dest, target_sec)  # fallback
    log("BGM", f"Prepared {dest.name} ({target_sec:.1f}s)")
    return dest, get_audio_duration(dest)
