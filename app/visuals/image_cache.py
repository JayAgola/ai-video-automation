"""SHA-256 image cache built on the existing CacheManager (no second cache system)."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from app.core.cache_manager import CacheManager
from app.core.logger import log


def image_settings_key(prompt: str, provider: str, model: str, width: int,
                       height: int, seed: int, extra: dict[str, Any] | None = None) -> str:
    from app.core import config
    settings: dict[str, Any] = {"provider": provider, "model": model,
                                "width": width, "height": height, "seed": seed,
                                # v2: prompts are visual-only + global no-text negative.
                                # Old keys (v1 text-embedded prompts) never match again.
                                "visual_cache_version": config.VISUAL_CACHE_VERSION,
                                "negative_prompt": config.VISUAL_NEGATIVE_PROMPT}
    if extra:
        settings.update(extra)
    return CacheManager.hash_key(prompt, settings)


def get_cached_image(cache: CacheManager, key: str, ext: str = ".png") -> Path | None:
    return cache.get("images", key, ext)


def put_cached_image(cache: CacheManager, key: str, src: Path | str,
                     ext: str = ".png") -> Path:
    dest = cache.put("images", key, ext, src)
    log("CACHE", f"image {key[:12]}... -> {dest.name}")
    return dest


def copy_from_cache(cached: Path, dest: Path | str) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(cached), str(dest))
    return dest
