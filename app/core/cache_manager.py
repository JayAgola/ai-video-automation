"""SHA-256 asset cache. Audio mandatory in Part 1; images/chunks/research ready."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from app.core.logger import log


class CacheManager:
    def __init__(self, cache_dir: Path | str):
        self.cache_dir = Path(cache_dir)
        # "stock" = Part 2.2 stock search results + downloaded stock media.
        for sub in ("audio", "images", "chunks", "research", "stock"):
            (self.cache_dir / sub).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def hash_key(payload: str | dict, settings: dict[str, Any] | None = None) -> str:
        """Cache key includes generation settings (e.g. voice) so voice change => new key."""
        if isinstance(payload, dict):
            payload = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        settings_str = json.dumps(settings or {}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(f"{payload}||{settings_str}".encode("utf-8")).hexdigest()

    def _path(self, category: str, key: str, ext: str) -> Path:
        return self.cache_dir / category / f"{key}{ext}"

    def get(self, category: str, key: str, ext: str) -> Path | None:
        p = self._path(category, key, ext)
        if p.exists() and p.stat().st_size > 0:
            log("CACHE", f"{category} cache HIT {p.name}")
            return p
        log("CACHE", f"{category} cache MISS {key[:12]}...")
        return None

    def put(self, category: str, key: str, ext: str, src: Path | str) -> Path:
        dest = self._path(category, key, ext)
        if dest.exists():
            return dest
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        shutil.copyfile(str(src), str(tmp))
        tmp.replace(dest)
        log("CACHE", f"{category} cached -> {dest.name}")
        return dest

    # Raw-bytes convenience (Part 2.2 stock downloads / cached search JSON).
    # Same directory + key scheme as every other asset: no second cache system.
    def get_bytes(self, category: str, key: str, ext: str) -> bytes | None:
        p = self._path(category, key, ext)
        if p.exists() and p.stat().st_size > 0:
            log("CACHE", f"{category} cache HIT {p.name}")
            return p.read_bytes()
        log("CACHE", f"{category} cache MISS {key[:12]}...")
        return None

    def put_bytes(self, category: str, key: str, ext: str, data: bytes) -> Path:
        dest = self._path(category, key, ext)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and dest.stat().st_size > 0:
            return dest
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(dest)
        log("CACHE", f"{category} cached -> {dest.name}")
        return dest

    def has(self, category: str, key: str, ext: str) -> bool:
        p = self._path(category, key, ext)
        return p.exists() and p.stat().st_size > 0

    def mtime(self, category: str, key: str, ext: str) -> float:
        p = self._path(category, key, ext)
        return p.stat().st_mtime if p.exists() else 0.0

    # Audio convenience
    def audio_key(self, text: str, voice: str) -> str:
        return self.hash_key(text, {"voice": voice, "engine": "edge-tts"})

    def get_audio(self, text: str, voice: str, ext: str = ".mp3") -> Path | None:
        return self.get("audio", self.audio_key(text, voice), ext)

    def put_audio(self, text: str, voice: str, src: Path | str, ext: str = ".mp3") -> Path:
        return self.put("audio", self.audio_key(text, voice), ext, src)
