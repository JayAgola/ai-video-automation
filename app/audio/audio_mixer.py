"""Mix voiceover + BGM (BGM ducked to BGM_VOLUME). Originals untouched."""
from __future__ import annotations

import subprocess
from pathlib import Path

from app.audio.duration import get_audio_duration
from app.core import config
from app.core.logger import log


def _ffmpeg_mix(voice: Path, bgm: Path, out: Path, bgm_volume: float) -> bool:
    try:
        cmd = ["ffmpeg", "-y", "-v", "error",
               "-i", str(voice), "-i", str(bgm),
               "-filter_complex",
               f"[1:a]volume={bgm_volume},atrim=0:{get_audio_duration(voice):.2f}[b];"
               "[0:a][b]amix=inputs=2:duration=first:dropout_transition=0[a]",
               "-map", "[a]", "-c:a", "libmp3lame", "-b:a", "192k", str(out)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        return r.returncode == 0 and out.exists()
    except Exception:
        return False


def _pydub_mix(voice: Path, bgm: Path, out: Path, bgm_volume: float) -> None:
    from pydub import AudioSegment
    v = AudioSegment.from_file(str(voice))
    b = AudioSegment.from_file(str(bgm))
    b = b - (20 if bgm_volume <= 0.11 else 10)  # ~0.10 -> -20dB, else -10dB
    if len(b) < len(v):
        b = (b * (len(v) // max(len(b), 1) + 1))[:len(v)]
    else:
        b = b[:len(v)]
    (v.overlay(b)).export(str(out), format="mp3", bitrate="192k")


def concat_voiceovers(files: list[Path], out: Path) -> Path:
    """Deterministic voiceover concat (ffmpeg concat demuxer; pydub fallback)."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        return out  # idempotent
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{f.resolve()}'\n" for f in files), encoding="utf-8")
    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
             "-i", str(lst), "-c", "copy", str(out)],
            capture_output=True, text=True, timeout=300)
        if r.returncode != 0 or not out.exists():
            raise RuntimeError(r.stderr[:500])
    except Exception:
        from pydub import AudioSegment
        combined = AudioSegment.empty()
        for f in files:
            combined += AudioSegment.from_file(str(f))
        combined.export(str(out), format="mp3", bitrate="192k")
    finally:
        try:
            lst.unlink()
        except OSError:
            pass
    return out


def mix_voice_bgm(voice_path: Path | str, bgm_path: Path | str,
                  out_path: Path | str,
                  bgm_volume: float | None = None) -> tuple[Path, float]:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    bgm_volume = config.BGM_VOLUME if bgm_volume is None else bgm_volume
    log("AUDIO", f"Mixing voice + BGM (bgm_volume={bgm_volume}) ...")
    if out_path.exists():  # idempotent
        log("AUDIO", f"Reuse existing mix -> {out_path}")
        return out_path, get_audio_duration(out_path)
    ok = _ffmpeg_mix(Path(voice_path), Path(bgm_path), out_path, bgm_volume)
    if not ok:
        _pydub_mix(Path(voice_path), Path(bgm_path), out_path, bgm_volume)
    dur = get_audio_duration(out_path)
    log("AUDIO", f"Mixed -> {out_path} ({dur:.1f}s)")
    return out_path, dur
