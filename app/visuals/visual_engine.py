"""Visual engine: consumes script.json visual_prompt/visual_direction, cache-first generation.

Caption/narration text NEVER enters the image prompt. Captions are rendered
later by the scene renderer (app.video.caption_overlay) as video text.

Sequential (one image job at a time) for RTX 3050. Per-scene state preserved.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from app.core import config
from app.core.cache_manager import CacheManager
from app.core.logger import log
from app.visuals import image_cache as icache


def scene_caption(scene: dict) -> str:
    """Renderer-stage caption: narration/caption text, never for image gen."""
    try:
        from app.script.script_engine import normalize_scene
        return str(normalize_scene(scene).get("caption_text", "") or "")
    except Exception:
        return str(scene.get("caption_text") or scene.get("narration", "") or "")


def scene_visual_description(scene: dict) -> str:
    """Visual-only scene description (legacy visual_direction supported)."""
    try:
        from app.script.script_engine import normalize_scene
        scene = normalize_scene(scene)
    except Exception:
        pass
    return str(scene.get("visual_prompt") or scene.get("visual_direction") or "").strip()


# Quoted 'Text: ...' / "quoted words" fragments the LLM used to emit as
# on-screen typography instructions. Strip them: image must be text-free.
_TEXT_INSTRUCTION_RE = re.compile(
    r"(?i)\btext\s*:\s*(['\"])(?P<t>.*?)(\1)|"
    r"(?i)\b(caption|subtitle|quote|on-screen text|typography)\s*:\s*(['\"])(?P<t2>.*?)\5"
)


def sanitize_visual_description(text: str) -> str:
    """Remove embedded text/typography instructions; keep scene description."""
    t = str(text or "")
    t = _TEXT_INSTRUCTION_RE.sub("", t)
    # Drop dangling markers like "Text:" with no quotes.
    t = re.sub(r"(?i)\btext\s*:\s*", "", t)
    t = re.sub(r"\s{2,}", " ", t).strip(" ,;:-")
    return t


def build_prompt(scene: dict, script: dict | None = None) -> str:
    """Visual-only prompt: scene description + style. NEVER narration/caption."""
    direction = sanitize_visual_description(scene_visual_description(scene))
    narration = ""
    try:
        from app.script.script_engine import normalize_scene
        narration = str(normalize_scene(scene).get("narration_text", "") or "")
    except Exception:
        narration = str(scene.get("narration", "") or "")
    caption = scene_caption(scene)
    # Defensive: if description somehow equals narration/caption, it carries no
    # visual signal; fall back to a neutral scene so the image stays text-free.
    if direction and narration and direction.strip() == narration.strip():
        direction = ""
    if direction and caption and direction.strip() == caption.strip():
        direction = ""
    style = (script or {}).get("visual_style", "")
    parts = ["16:9 cinematic frame, high detail"]
    if style:
        parts.append(f"Style: {style}")
    parts.append(direction or "calm abstract cinematic landscape, no text")
    prompt = ", ".join(p for p in parts if p)
    # Absolute guard: narration/caption sentences must not leak into the image prompt.
    for forbidden in {narration.strip(), caption.strip()}:
        if forbidden and len(forbidden) > 20 and forbidden in prompt:
            raise ValueError("Visual prompt must not contain narration/caption text.")
    return prompt


def negative_prompt() -> str:
    """Global negative prompt: no text/typography in generated images."""
    return config.VISUAL_NEGATIVE_PROMPT


def get_provider(name: str | None = None):
    from app.visuals.comfyui_provider import ComfyUIProvider
    from app.visuals.test_provider import TestImageProvider
    name = (name or ("test" if config.TEST_VISUAL_MODE or
                     config.VISUAL_PROVIDER == "test" else config.VISUAL_PROVIDER))
    if name == "comfyui":
        return ComfyUIProvider(config.COMFYUI_BASE_URL, config.COMFYUI_MODEL)
    if name == "test":
        return TestImageProvider()
    raise ValueError(f"VISUAL PROVIDER NOT CONFIGURED: unknown provider '{name}'. "
                     "Set VISUAL_PROVIDER=test|comfyui or TEST_VISUAL_MODE=true.")


def provider_health(name: str | None = None) -> dict[str, Any]:
    try:
        return get_provider(name).health()
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Part 2.2: HYBRID VISUAL SOURCES (stock / local / AI) with deterministic
# fallback. Reuses the existing provider abstraction and image cache; the AI
# path below is the unchanged Part 2 implementation and stays the last resort.
# ---------------------------------------------------------------------------
AI_VISUAL_TYPES = {"abstract", "cartoon", "fictional", "surreal", "conceptual"}
VALID_PREFERENCES = {"auto", "stock", "ai", "local"}
VALID_VISUAL_TYPES = {"person", "animal", "landscape", "object", "place", "room",
                      "abstract", "cartoon", "fictional", "unknown"}


def scene_visual_type(scene: dict) -> str:
    t = str((scene or {}).get("visual_type") or "unknown").strip().lower()
    return t if t in VALID_VISUAL_TYPES else "unknown"


def scene_source_preference(scene: dict) -> str:
    p = str((scene or {}).get("visual_source_preference") or "auto").strip().lower()
    return p if p in VALID_PREFERENCES else "auto"


def scene_stock_query(scene: dict) -> str:
    """Stock search terms. NEVER the narration/caption (Part 2 rule)."""
    q = str((scene or {}).get("stock_search_query") or "").strip()
    if q:
        return q
    # Deterministic fallback: content words of the VISUAL description only.
    try:
        from app.visuals.stock_providers import query_tokens
        words = query_tokens(scene_visual_description(scene))
    except Exception:
        words = []
    return " ".join(words[:5])


def source_plan(scene: dict, mode: str | None = None) -> list[str]:
    """Ordered, deterministic source chain for one scene (no loops, no API
    fan-out: each source is tried at most once, in order)."""
    mode = (mode or config.VISUAL_SOURCE_MODE or "auto").strip().lower()
    pref = scene_source_preference(scene)
    vtype = scene_visual_type(scene)
    if mode == "ai":
        return ["ai"]
    if mode == "local":
        return ["local", "pexels", "pixabay", "ai"]
    if mode == "stock":
        return ["pexels", "pixabay", "ai"]
    # AUTO: explicit scene preference wins, else visual_type decides.
    if pref == "local":
        return ["local", "pexels", "pixabay", "ai"]
    if pref == "stock":
        return ["pexels", "pixabay", "ai"]
    if pref == "ai":
        return ["ai", "pexels", "pixabay"]
    return (["ai", "pexels", "pixabay"] if vtype in AI_VISUAL_TYPES
            else ["pexels", "pixabay", "ai"])


def _stock_providers() -> list:
    from app.visuals.stock_providers import (LocalStockProvider, PexelsProvider,
                                             PixabayProvider)
    return [LocalStockProvider(), PexelsProvider(), PixabayProvider()]


def _used_asset_ids(state: dict) -> set:
    """Asset ids already burned into this project (duplicate avoidance)."""
    used = set()
    for k, v in ((state or {}).get("data") or {}).items():
        if k.startswith("visual_meta_") and isinstance(v, dict):
            if v.get("provider") and v.get("asset_id"):
                used.add("{}:{}".format(v["provider"], v["asset_id"]))
    return used


def scene_seed(project_id: str, scene_id: int, base_seed: int | None = None) -> int:
    base = config.VISUAL_SEED if base_seed is None else base_seed
    h = hashlib.sha256(f"{project_id}||{scene_id}||{base}".encode()).hexdigest()
    return int(h[:8], 16) % (2 ** 31)


def _resolve_stock(pid: str, scene: dict, visuals_dir: Path, cache: CacheManager,
                   provider, sid: int, width: int, height: int,
                   used: set) -> tuple[Path, dict, bool]:
    """Search + score + download via ONE stock provider (cached, deterministic)."""
    from app.visuals import stock_providers as sp
    query = scene_stock_query(scene)
    media_type = str((scene or {}).get("stock_media") or "photo").strip().lower()
    if media_type not in ("photo", "video"):
        media_type = "photo"
    if media_type == "video" and not config.STOCK_ALLOW_VIDEO:
        media_type = "photo"
    settings = {"project_id": pid, "scene_id": sid}
    skey = sp.search_cache_key(provider.name, query, media_type,
                               config.STOCK_MAX_RESULTS, width, height,
                               config.STOCK_SAFESEARCH)
    cands = sp.cached_json(skey, lambda: provider.search(
        query, media_type, config.STOCK_MAX_RESULTS, width, height, settings))
    # Resume-hardening: a legacy/corrupt cache entry might hold the RAW
    # provider response (dict) instead of the candidate list. The parse
    # functions below guarantee only raw dicts with the right shape pass;
    # anything else raises StockError and falls back cleanly.
    if not isinstance(cands, list):
        log("VISUAL", "Scene {}: {} cache entry wrong shape ({}) -> re-search".format(
            sid, provider.name, type(cands).__name__))
        cands = provider.search(query, media_type, config.STOCK_MAX_RESULTS,
                                width, height, settings)
        if isinstance(cands, list):
            try:
                from app.visuals.stock_providers import _cache as _scache
                import json as _json
                _scache().put_bytes("stock", skey, ".json",
                                    _json.dumps(cands, sort_keys=True).encode("utf-8"))
            except Exception:
                pass
    best = sp.choose_candidate(cands, width, height, query, media_type, used,
                               media_pref=config.STOCK_MEDIA_PREFERENCE)
    if best is None:
        raise sp.StockError(f"{provider.name}: no acceptable candidate for '{query}'.")
    akey = sp.asset_cache_key(provider.name, str(best.get("asset_id", "")),
                              str(best.get("media_type", "photo")), width, height)
    suffix = ".mp4" if best.get("media_type") == "video" else ".png"
    dest = visuals_dir / f"scene_{sid:03d}{suffix}"
    cached = cache.get("stock", akey, suffix)
    hit = False
    if cached is None and dest.exists() and dest.stat().st_size > 0:
        cache.put("stock", akey, suffix, dest)
        cached = dest
    if cached is not None:
        if Path(cached).resolve() != dest.resolve():
            import shutil as _sh
            _sh.copyfile(str(cached), str(dest))
        hit = True
    else:
        provider.fetch(best, dest, width, height, settings)
        cache.put("stock", akey, suffix, dest)
    meta = {"scene_id": sid, "source": "stock", "provider": provider.name,
            "asset_id": str(best.get("asset_id", "")),
            "media_type": str(best.get("media_type")),
            "source_url": best.get("source_url", ""), "creator": best.get("creator", ""),
            "license": best.get("license", ""), "query": query,
            "asset_metadata": sp.base_metadata(provider.name, best, pid, sid, query,
                                               str(best.get("media_type"))),
            "visual_prompt": scene_visual_description(scene),
            "caption_text": scene_caption(scene),
            "path": str(dest), "width": width, "height": height,
            "cache_version": config.STOCK_CACHE_VERSION, "cache_hit": hit,
            "visual_type": scene_visual_type(scene),
            "visual_source_preference": scene_source_preference(scene)}
    if not hit:
        (visuals_dir / f"scene_{sid:03d}.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8")
    log("VISUAL", f"Scene {sid}: stock {provider.name} {best.get('media_type')} "
                  f"(asset {best.get('asset_id')}, {'HIT' if hit else 'downloaded'})")
    return dest, meta, hit


def generate_scene_image(project_id: str, scene: dict, script: dict | None,
                         visuals_dir: Path, cache: CacheManager,
                         provider=None, width: int | None = None,
                         height: int | None = None,
                         stock_providers: list | None = None,
                         state: dict | None = None) -> tuple[Path, dict, bool]:
    """Returns (visual_path, metadata, cache_hit). Raises on total failure.

    Hybrid Part 2.2: resolves the scene's source chain (local/stock per
    `source_plan`) FIRST and only falls back to the unchanged Part 2 AI path.
    """
    provider = provider or get_provider()
    width = width or config.IMAGE_WIDTH
    height = height or config.IMAGE_HEIGHT
    sid = int(scene["scene_id"])
    order = {"local": 0, "pexels": 1, "pixabay": 2}
    provs = list(stock_providers) if stock_providers else _stock_providers()
    used = _used_asset_ids(state or {})
    plan = source_plan(scene)
    vtype = scene_visual_type(scene)
    pref = scene_source_preference(scene)
    squery = scene_stock_query(scene)
    log("VISUAL", "Scene {} type={} preference={} stock_query={} selected_source={}".format(
        sid, vtype, pref, squery, (plan[0] if plan else "none")))
    last_error: Exception | None = None
    for src in plan:                      # each source tried at most once -> no loops
        if src == "ai":
            try:
                return _generate_ai_image(project_id, scene, script, visuals_dir,
                                          cache, provider, sid, width, height)
            except Exception as e:
                last_error = e
                log("VISUAL", "Scene {}: AI unavailable -> next source ({})".format(
                    sid, type(e).__name__))
            continue
        idx = order.get(src)
        if idx is None or idx >= len(provs) or provs[idx] is None:
            continue
        try:
            return _resolve_stock(project_id, scene, visuals_dir, cache,
                                  provs[idx], sid, width, height, used)
        except Exception as e:
            last_error = e
            log("VISUAL", "Scene {}: {} unavailable -> next source ({})".format(
                sid, src, type(e).__name__))
    if last_error is not None:
        raise last_error
    raise RuntimeError("No visual source available (empty source plan).")


def _generate_ai_image(project_id: str, scene: dict, script: dict | None,
                       visuals_dir: Path, cache: CacheManager, provider,
                       sid: int, width: int, height: int) -> tuple[Path, dict, bool]:
    """Unchanged Part 2 AI path (extracted verbatim; the last-resort source)."""
    prompt = build_prompt(scene, script)
    neg = negative_prompt()
    model = getattr(provider, "model", "") if provider.name == "comfyui" else "test-placeholder"
    seed = scene_seed(project_id, sid)
    key = icache.image_settings_key(prompt, provider.name, model, width, height, seed,
                                    {"negative_prompt": neg})
    cached = icache.get_cached_image(cache, key)
    dest = visuals_dir / f"scene_{sid:03d}.png"
    meta = {"scene_id": sid, "prompt": prompt, "negative_prompt": neg,
            "visual_prompt": scene_visual_description(scene),
            "caption_text": scene_caption(scene),
            "provider": provider.name,
            "model": model, "width": width, "height": height, "seed": seed,
            "cache_key": key, "cache_version": config.VISUAL_CACHE_VERSION,
            "path": str(dest)}
    if cached is not None and dest.exists() and dest.stat().st_size > 0:
        log("VISUAL", f"Scene {sid}: CACHE HIT (project file exists)")
        return dest, meta, True
    if cached is not None:
        icache.copy_from_cache(cached, dest)
        log("VISUAL", f"Scene {sid}: CACHE HIT -> {dest.name}")
        return dest, meta, True
    log("VISUAL", f"Scene {sid}: CACHE MISS, generating via {provider.name} ...")
    result = provider.generate_image(prompt, dest, width, height,
                                     {"seed": seed, "project_id": project_id,
                                      "scene_id": sid, "negative_prompt": neg})
    meta.update({k: v for k, v in result.items() if k in
                 ("width", "height", "seed", "path", "test_mode")})
    if provider.name == "test":
        meta["test_mode"] = True
    icache.put_cached_image(cache, key, dest)
    (visuals_dir / f"scene_{sid:03d}.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8")
    return dest, meta, False
