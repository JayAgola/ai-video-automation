"""TTS engine: edge-tts + SHA-256 cache, configurable voice, bounded retries."""
from __future__ import annotations

import asyncio
from pathlib import Path

from app.audio.duration import get_audio_duration
from app.core import config
from app.core.cache_manager import CacheManager
from app.core.logger import log

try:
    import edge_tts
except ImportError:  # surfaced clearly at call time
    edge_tts = None  # type: ignore


async def _synthesize(text: str, voice: str, out_path: Path) -> None:
    communicate = edge_tts.Communicate(text, voice)  # type: ignore[union-attr]
    await communicate.save(str(out_path))


def synthesize_narration(text: str, voice: str | None = None,
                         cache: CacheManager | None = None,
                         dest: Path | str | None = None,
                         max_retries: int = 2) -> tuple[Path, float, bool]:
    """Returns (audio_path, duration_sec, cache_hit). Raises on failure after retries."""
    if edge_tts is None:
        raise RuntimeError("edge-tts not installed. Run: pip install -r requirements.txt")
    voice = voice or config.TTS_VOICE
    cache = cache or CacheManager(config.CACHE_DIR)
    text = text.strip()
    if not text:
        raise ValueError("Empty narration text")

    cached = cache.get_audio(text, voice)
    if cached is not None:
        if dest is not None:
            dest = Path(dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.resolve() != cached.resolve():
                import shutil
                shutil.copyfile(str(cached), str(dest))
        return cached, get_audio_duration(cached), True

    last_err = ""
    for attempt in range(1, max_retries + 2):
        try:
            tmp = cache.cache_dir / "audio" / f"tmp_{cache.audio_key(text, voice)[:16]}.mp3"
            asyncio.run(_synthesize(text, voice, tmp))
            if not tmp.exists() or tmp.stat().st_size == 0:
                raise RuntimeError("edge-tts produced empty file")
            final = cache.put_audio(text, voice, tmp)
            try:
                tmp.unlink()
            except OSError:
                pass
            if dest is not None:
                dest = Path(dest)
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.resolve() != final.resolve():
                    import shutil
                    shutil.copyfile(str(final), str(dest))
                    return dest, get_audio_duration(dest), False
            return final, get_audio_duration(final), False
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            log("ERROR", f"TTS attempt {attempt} failed: {last_err[:300]}")
    raise RuntimeError(f"TTS failed after retries: {last_err[:500]}")
