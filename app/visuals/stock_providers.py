"""Licensed stock media providers (Part 2.2 hybrid visual sources).

Implements the existing `StockProvider` protocol (app.visuals.image_provider) for
Pexels / Pixabay / local assets, plus a deterministic offline mock used by tests.

Rules honoured here:
  * Licensed/API sources only - no Google Images scraping, no Selenium/Playwright.
  * API keys come from config/env and are NEVER logged (redacted on every message).
  * Bounded, cached, retrying requests; HTTP 429 is treated as "stop calling this
    provider" instead of a retry storm (rate limits are respected).
  * Deterministic result ordering so reruns pick the same asset.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core import config
from app.core.cache_manager import CacheManager
from app.core.logger import log

PHOTO_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".webm", ".m4v")
MIN_KEY_LEN = 6


class StockError(RuntimeError):
    """Recoverable stock failure -> the caller falls back to the next source."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def redact(text: Any, *secrets: str) -> str:
    """Strip API keys from any string that could reach a log or exception."""
    t = str(text or "")
    for s in secrets:
        if s and len(str(s)) >= MIN_KEY_LEN:
            t = t.replace(str(s), "***")
    return t


def media_kind(name: str | Path) -> str:
    return "video" if str(name).lower().endswith(VIDEO_EXTS) else "photo"


def asset_cache_key(provider: str, asset_id: str, media_type: str,
                    width: int, height: int) -> str:
    """Stable key for a downloaded asset (reuses the existing CacheManager)."""
    return CacheManager.hash_key(f"{provider}||{asset_id}||{media_type}",
                                 {"width": width, "height": height,
                                  "stock_cache_version": config.STOCK_CACHE_VERSION})


def search_cache_key(provider: str, query: str, media_type: str, count: int,
                     width: int, height: int, safesearch: bool) -> str:
    return CacheManager.hash_key(f"{provider}||candidates||search", {
        "query": query.lower().strip(), "media_type": media_type, "count": count,
        "min_width": width, "min_height": height, "safesearch": safesearch,
        "orientation": "landscape", "stock_cache_version": config.STOCK_CACHE_VERSION})


def _api_cache_key(provider: str, query: str, media_type: str, count: int,
                   width: int, height: int, safesearch: bool) -> str:
    """Separate key for the RAW HTTP response cache.

    _resolve_stock caches the parsed candidate list under `search_cache_key`.
    Pexels._api / Pixabay._search_cached cache the raw API dict under THIS key.
    Keeping them apart prevents a raw dict being mistaken for a candidate list
    (AttributeError / TypeError on resume).
    """
    return CacheManager.hash_key(f"{provider}||raw_response||search", {
        "query": query.lower().strip(), "media_type": media_type, "count": count,
        "min_width": width, "min_height": height, "safesearch": safesearch,
        "orientation": "landscape", "stock_cache_version": config.STOCK_CACHE_VERSION})


def normalize_photo(src: Path | str, dest: Path | str, width: int, height: int) -> tuple[int, int]:
    """Cover-crop to the project's 16:9 frame (existing image normalization)."""
    from PIL import Image, ImageOps
    src, dest = Path(src), Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(str(src)) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        fitted = ImageOps.fit(im, (width, height), method=Image.LANCZOS, centering=(0.5, 0.5))
        fitted.save(str(dest), "PNG")
    return width, height


def base_metadata(provider: str, candidate: dict, project_id: str, scene_id: int,
                  query: str, media_type: str) -> dict[str, Any]:
    """Provenance record required for every downloaded stock asset."""
    return {
        "provider": provider,
        "asset_id": str(candidate.get("asset_id", "")),
        "media_type": media_type,
        "source_url": candidate.get("source_url", ""),
        "creator": candidate.get("creator", ""),
        "query": query,
        "license": candidate.get("license") or "provider-default (see source_url)",
        "downloaded_at": now_iso(),
        "project_id": project_id,
        "scene_id": int(scene_id),
    }


# ---------------------------------------------------------------- HTTP helpers
def _http_json(url: str, params: dict | None, headers: dict | None,
               provider: str, secret: str = "", timeout: int | None = None,
               retries: int | None = None) -> dict:
    """Bounded, redacting JSON GET. HTTP 429 stops immediately (rate limit)."""
    import requests
    timeout = timeout or config.STOCK_TIMEOUT
    retries = config.STOCK_MAX_RETRIES if retries is None else retries
    last = ""
    for attempt in range(max(0, retries) + 1):
        try:
            r = requests.get(url, params=params, headers=headers or {}, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (401, 403):
                raise StockError(redact(f"{provider}: authentication failed (HTTP "
                                        f"{r.status_code}) - check the API key.", secret))
            if r.status_code == 429:
                raise StockError(f"{provider}: rate limit reached (HTTP 429). "
                                 f"Stopping calls to this provider for now.")
            last = f"HTTP {r.status_code}"
        except StockError:
            raise
        except Exception as e:  # connection/timeout: bounded retry
            last = f"{type(e).__name__}"
        if attempt < retries:
            time.sleep(min(1.5 * (attempt + 1), 4))
    raise StockError(redact(f"{provider}: request failed ({last}).", secret))


def _download(url: str, dest: Path, provider: str, secret: str = "",
              max_bytes: int | None = None) -> Path:
    import requests
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = requests.get(url, timeout=config.STOCK_TIMEOUT, stream=True)
        r.raise_for_status()
    except Exception as e:
        raise StockError(redact(f"{provider}: download failed ({type(e).__name__}).", secret))
    tmp = dest.with_suffix(dest.suffix + ".part")
    written = 0
    try:
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                written += len(chunk)
                if max_bytes and written > max_bytes:
                    raise StockError(f"{provider}: asset exceeds STOCK_VIDEO_MAX_BYTES.")
                f.write(chunk)
    finally:
        if tmp.exists() and tmp != dest:
            try:
                if written:
                    tmp.replace(dest)
                else:
                    tmp.unlink()
            except OSError:
                pass
    if not dest.exists() or dest.stat().st_size == 0:
        raise StockError(f"{provider}: empty download.")
    return dest


def _landscape(w: int, h: int) -> bool:
    return int(w or 0) > 0 and int(h or 0) > 0 and int(w) >= int(h)


_EXTS = PHOTO_EXTS + VIDEO_EXTS


def _cache() -> CacheManager:
    return CacheManager(config.CACHE_DIR)


def cached_json(key: str, producer, ttl_hours: float | None = None) -> Any:
    """Cache search results inside the existing CacheManager (category 'stock').

    Providers require caching and we must never make a duplicate API call for the
    same query within the TTL window.
    """
    ttl = config.STOCK_CACHE_TTL_HOURS if ttl_hours is None else ttl_hours
    cache = _cache()
    if cache.has("stock", key, ".json"):
        age = max(0.0, time.time() - cache.mtime("stock", key, ".json"))
        if ttl <= 0 or age <= ttl * 3600.0:
            raw = cache.get_bytes("stock", key, ".json")
            if raw:
                try:
                    return json.loads(raw.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    pass
    data = producer()
    try:
        cache.put_bytes("stock", key, ".json",
                        json.dumps(data, sort_keys=True).encode("utf-8"))
    except Exception:  # caching must never break the pipeline
        pass
    return data


def candidate(provider: str, asset_id: str, media_type: str, download_url: str,
              width: int, height: int, source_url: str = "", creator: str = "",
              license_: str = "", query: str = "", duration: float = 0.0,
              file_ext: str = "", tags: str = "", safesearch: str = "provider-default",
              has_text: bool = False, nsfw: bool = False) -> dict[str, Any]:
    """One normalized stock candidate (provider-agnostic shape)."""
    return {"provider": provider, "asset_id": str(asset_id), "media_type": media_type,
            "download_url": download_url, "source_url": source_url or download_url,
            "creator": creator, "license": license_ or "provider-default (see source_url)",
            "query": query, "width": int(width or 0), "height": int(height or 0),
            "duration": float(duration or 0.0),
            "file_ext": file_ext or (".mp4" if media_type == "video" else ".png"),
            "tags": str(tags or query), "safesearch": safesearch,
            "has_text": bool(has_text), "nsfw": bool(nsfw)}


class LocalStockProvider:
    """Local (user-supplied) assets: assets/stock/** and projects/<id>/assets/**.

    No API calls, deterministic ordering, works fully offline.
    """
    name = "local"
    kind = "stock"

    def __init__(self, roots: list[str | Path] | None = None):
        self._roots = [Path(r) for r in roots] if roots else None

    def roots(self, project_id: str = "") -> list[Path]:
        if self._roots is not None:
            return [r for r in self._roots if r.exists()]
        found = [config.ASSETS_DIR / config.LOCAL_STOCK_DIRNAME]
        if project_id:
            proj = config.PROJECTS_DIR / str(project_id) / "assets"
            found += [proj, proj / config.LOCAL_STOCK_DIRNAME]
        return [p for p in found if p.exists()]

    def _files(self, project_id: str = "") -> list[Path]:
        files: list[Path] = []
        for root in self.roots(project_id):
            try:
                for p in sorted(root.rglob("*")):
                    if p.is_file() and p.suffix.lower() in _EXTS:
                        files.append(p)
            except OSError:
                continue
        return sorted(set(files), key=lambda p: str(p).lower())

    def health(self) -> dict[str, Any]:
        files = self._files()
        return {"ok": True, "provider": self.name, "status": "AVAILABLE",
                "files": len(files), "note": "Offline local assets (no API calls)."}

    def search(self, query: str, media_type: str = "photo", count: int = 10,
               width: int = 1280, height: int = 720,
               settings: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        settings = settings or {}
        project_id = str(settings.get("project_id", "") or "")
        want = "" if media_type in ("", "any") else media_type
        tokens = [t for t in str(query or "").lower().split() if len(t) > 2]
        scored: list[tuple[int, str, dict]] = []
        for p in self._files(project_id):
            kind = media_kind(p)
            if want and kind != want:
                continue
            stem = p.stem.lower().replace("_", " ").replace("-", " ")
            hits = sum(1 for t in tokens if t in stem)
            # Hand-picked local assets are always eligible; query only ranks them.
            scored.append((-hits, str(p).lower(), candidate(
                self.name, "local-" + hashlib.sha256(str(p).encode("utf-8")).hexdigest()[:16],
                kind, str(p), width, height,
                source_url=p.resolve().as_uri(),
                creator="local asset (user supplied)",
                license_="user-supplied local asset", query=query,
                file_ext=p.suffix.lower(), tags=stem)))
        scored.sort(key=lambda t: (t[0], t[1]))
        return [c for _, _, c in scored[:max(1, int(count))]]

    def fetch(self, cand: dict[str, Any], output_path: Path | str, width: int,
              height: int, settings: dict[str, Any] | None = None) -> dict[str, Any]:
        src = Path(str(cand.get("download_url") or ""))
        if not src.exists():
            raise StockError("local: asset disappeared: " + str(src))
        dest = Path(output_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if cand.get("media_type") == "video":
            if dest.resolve() != src.resolve():
                shutil.copyfile(str(src), str(dest))
        else:
            normalize_photo(src, dest, width, height)
        return {"path": str(dest), "width": width, "height": height}


# ------------------------------------------------------- candidate scoring
# Media we must never burn into a scene: text-bearing / unsafe / portrait.
_STOPWORDS = {"a", "an", "the", "of", "in", "on", "at", "with", "and", "or", "to",
              "into", "his", "her", "their", "its", "is", "are", "was", "with"}


def query_tokens(query: str) -> list[str]:
    out = []
    for t in re.split(r"[^a-z0-9]+", str(query or "").lower()):
        if len(t) > 2 and t not in _STOPWORDS and t not in out:
            out.append(t)
    return out


def relevance(cand: dict, query: str) -> float:
    """Cheap deterministic relevance: query-token overlap with tags/alt text."""
    tokens = query_tokens(query)
    if not tokens:
        return 0.0
    hay = " ".join(str(cand.get(k, "")) for k in ("tags", "title", "alt")).lower()
    hits = sum(1 for t in tokens if t in hay)
    return hits / float(len(tokens))


def score_candidate(cand: dict, width: int, height: int, query: str = "",
                    media_pref: str = "photo", used_ids: set | None = None) -> float:
    """Deterministic quality score (higher = better). Rejects are handled by
    `acceptable()`; this only ranks the survivors. No ML model involved."""
    score = 0.0
    w, h = int(cand.get("width") or 0), int(cand.get("height") or 0)
    # Resolution: reward up to ~2.5x the frame, never above (keeps downloads light).
    if w and h:
        scale = min(w / float(max(width, 1)), 2.5)
        score += min(scale, 2.5)
        # Aspect ratio closeness to the project frame (16:9 == 1.777...).
        target = float(width) / float(max(height, 1))
        ratio = float(w) / float(h)
        score += max(0.0, 1.0 - abs(ratio - target) / target)
    score += 1.2 * relevance(cand, query)
    if str(cand.get("media_type")) == media_pref:
        score += 0.6
    if str(cand.get("safesearch", "")).lower() in ("true", "strict", "1"):
        score += 0.2
    if cand.get("has_text"):
        score -= 2.0            # fake typography inside the frame
    if cand.get("nsfw"):
        score -= 5.0
    used = used_ids or set()
    ident = "{}:{}".format(cand.get("provider", ""), cand.get("asset_id", ""))
    if ident in used:
        score -= 3.0            # already-used asset penalty (avoid duplicates)
    return round(score, 6)


def acceptable(cand: dict, width: int, height: int, media_type: str = "",
               min_video_seconds: float | None = None) -> bool:
    """Hard filters: landscape only, minimum size, sane video duration, safe."""
    if cand.get("nsfw"):
        return False
    w, h = int(cand.get("width") or 0), int(cand.get("height") or 0)
    if not _landscape(w, h):
        return False
    if w < int(width) or h < int(height):
        return False
    kind = str(cand.get("media_type") or "")
    if media_type and kind != media_type:
        return False
    if kind == "video":
        dur = float(cand.get("duration") or 0)
        minimum = config.STOCK_MIN_VIDEO_SECONDS if min_video_seconds is None \
            else float(min_video_seconds)
        if dur and dur < minimum:
            return False
    return bool(cand.get("download_url"))


def choose_candidate(cands: list[dict], width: int, height: int, query: str = "",
                     media_type: str = "", used_ids: set | None = None,
                     media_pref: str | None = None) -> dict | None:
    """Deterministic best candidate: filter -> score -> stable sort. Never the
    blind first result, and reruns always pick the same asset."""
    pref = media_pref if media_pref is not None else config.STOCK_MEDIA_PREFERENCE
    survivors = [c for c in (cands or []) if acceptable(c, width, height, media_type)]
    if not survivors:
        return None
    ranked = sorted(
        survivors,
        key=lambda c: (-score_candidate(c, width, height, query, pref, used_ids),
                       str(c.get("provider", "")), str(c.get("asset_id", ""))))
    return ranked[0]


def _parse_pexels_response(raw: Any, media: str) -> dict:
    """Validate the official Pexels REST shape; never return garbage downstream.

    Photo search returns {"photos": [...]}; video search returns {"videos": [...]}.
    If the HTTP layer returned something else (HTML error page, proxy payload),
    map it to StockError so the hybrid chain falls back cleanly instead of
    crashing with AttributeError/TypeError.
    """
    if not isinstance(raw, dict):
        raise StockError("pexels: unexpected response shape "
                         f"(expected JSON object, got {type(raw).__name__}).")
    key = "videos" if media == "video" else "photos"
    items = raw.get(key, [])
    if not isinstance(items, list):
        raise StockError(f"pexels: unexpected '{key}' payload "
                         f"(expected list, got {type(items).__name__}).")
    return raw


def _parse_pixabay_response(raw: Any, media: str) -> dict:
    """Validate the official Pixabay REST shape; never return garbage downstream.

    Both /api and /api/videos return {"hits": [...]}. Anything else is mapped to
    StockError so the hybrid chain falls back cleanly.
    """
    if not isinstance(raw, dict):
        raise StockError("pixabay: unexpected response shape "
                         f"(expected JSON object, got {type(raw).__name__}).")
    hits = raw.get("hits", [])
    if not isinstance(hits, list):
        raise StockError("pixabay: unexpected 'hits' payload "
                         f"(expected list, got {type(hits).__name__}).")
    return raw


# ------------------------------------------------------------ Pexels provider
class PexelsProvider:
    """Official Pexels API (https://api.pexels.com). Photos + videos, landscape.

    Key travels ONLY in the Authorization header and is redacted from every
    message this class can raise. Results are cached (category 'stock') so a
    rerun never burns the free tier's request budget twice.
    """

    name = "pexels"
    kind = "stock"
    _BASE = "https://api.pexels.com"

    def __init__(self, api_key: str | None = None):
        self.secret = (api_key or config.PEXELS_API_KEY or "").strip()

    def health(self) -> dict[str, Any]:
        if not self.secret:
            return {"ok": False, "provider": self.name, "status": "NO_API_KEY",
                    "note": "Set PEXELS_API_KEY in .env to enable Pexels stock."}
        try:
            self._api({"query": "nature", "per_page": 1}, media="photo")
            return {"ok": True, "provider": self.name, "status": "AVAILABLE"}
        except StockError as e:
            return {"ok": False, "provider": self.name, "status": "ERROR",
                    "error": redact(str(e), self.secret)}

    # -- internals --
    def _api(self, params: dict, media: str = "photo") -> dict:
        # Landscape is enforced here so EVERY search path is horizontal.
        params = dict(params)
        params.setdefault("orientation", "landscape")
        query = str(params.get("query", "") or "").strip()
        per_page = max(1, min(int(params.get("per_page") or config.STOCK_MAX_RESULTS), 40))
        if not query:
            raise StockError("pexels: refusing search with empty query.")
        log("PEXELS", 'Searching: "{}"'.format(query[:160]))
        raw_key = _api_cache_key(self.name, query, media, per_page,
                                 params.get("min_width", config.STOCK_MIN_WIDTH),
                                 params.get("min_height", config.STOCK_MIN_HEIGHT),
                                 config.STOCK_SAFESEARCH)
        raw = cached_json(raw_key, lambda: _http_json(
            f"{self._BASE}{'/videos/search' if media == 'video' else '/v1/search'}",
            {**params, "query": query, "per_page": per_page},
            {"Authorization": self.secret}, self.name, self.secret))
        return _parse_pexels_response(raw, media)

    def search(self, query: str, media_type: str = "photo", count: int = 10,
               width: int = 1280, height: int = 720,
               settings: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if not self.secret:
            raise StockError("pexels: PEXELS_API_KEY is not configured.")
        count = max(1, min(int(count or config.STOCK_MAX_RESULTS), 40))
        if media_type == "video":
            out = self._search_videos(query, count, width, height)
        else:
            data = self._api({"query": query, "per_page": count,
                              "orientation": "landscape"}, media="photo")
            out = self._parse_photos(data.get("photos", [])[:count] if isinstance(data, dict) else [], query)
        log("PEXELS", 'Results: {} ({}) for "{}"'.format(len(out), media_type, str(query)[:80]))
        return out

    # -- photo parsing (pure: no network, no secrets) --
    def _parse_photos(self, photos: list, query: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for p in photos or []:
            if not isinstance(p, dict):
                continue
            src = p.get("src", {}) or {}
            if not isinstance(src, dict):
                continue
            download = src.get("original") or src.get("large2x") or src.get("large") \
                or src.get("medium") or src.get("landscape")
            if not download:
                continue
            w, h = int(p.get("width") or 0), int(p.get("height") or 0)
            if not _landscape(w, h):
                continue
            out.append(candidate(
                self.name, p.get("id", ""), "photo", download, w, h,
                source_url=p.get("url", ""), creator=p.get("photographer", ""),
                license_="Pexels License (free, no attribution required)",
                query=query, file_ext=".jpg", tags=str(p.get("alt") or ""),
                safesearch="provider-default"))
        return out

    def _search_videos(self, query: str, count: int, width: int, height: int
                       ) -> list[dict[str, Any]]:
        if not config.STOCK_ALLOW_VIDEO:
            return []
        data = self._api({"query": query, "per_page": count,
                          "orientation": "landscape"}, media="video")
        out: list[dict[str, Any]] = []
        for v in data.get("videos", [])[:count]:
            if not isinstance(v, dict):
                continue
            files = [f for f in (v.get("video_files") or [])
                     if isinstance(f, dict)
                     and str(f.get("file_type", "")).startswith("video")]
            if not files:
                continue
            # Smallest file that still meets the minimum size (keeps it cheap).
            files.sort(key=lambda f: (int(f.get("width") or 0), int(f.get("height") or 0)))
            pick = next((f for f in files
                         if int(f.get("width") or 0) >= width
                         and int(f.get("height") or 0) >= height), files[-1])
            w, h = int(pick.get("width") or 0), int(pick.get("height") or 0)
            link = str(pick.get("link") or "")
            if not link or not _landscape(w, h):
                continue
            user = v.get("user") or {}
            creator = user.get("name", "") if isinstance(user, dict) else ""
            tail = link.split("?")[0].rsplit(".", 1)
            lext = ("." + "".join(c for c in tail[-1].lower() if c.isalnum())[:5]
                    if len(tail) > 1 else ".mp4")
            if len(lext) < 2:
                lext = ".mp4"
            log("PEXELS", "Selected video asset: {} ({}x{})".format(v.get("id", ""), w, h))
            out.append(candidate(
                self.name, v.get("id", ""), "video", link,
                w, h, source_url=v.get("url", "") or link,
                creator=creator,
                license_="Pexels License (free, no attribution required)",
                query=query, duration=float(v.get("duration") or 0.0),
                file_ext=lext,
                tags=query, safesearch="provider-default"))
        log("PEXELS", "Video results: {} for \"{}\"".format(len(out), str(query)[:80]))
        return out

    def fetch(self, cand: dict[str, Any], output_path: Path | str, width: int,
              height: int, settings: dict[str, Any] | None = None) -> dict[str, Any]:
        dest = Path(output_path)
        media = str(cand.get("media_type") or "photo")
        ext = str(cand.get("file_ext") or (".mp4" if media == "video" else ".png"))
        if media == "video":
            # Stock VIDEO sources must land next to scene_XXX.png as scene_XXX.mp4
            # (pipeline_steps_p2b looks for visuals/scene_NNN.mp4). A ".mp4?" or
            # query-suffixed extension would break that lookup, so sanitize.
            safe = "." + "".join(c for c in ext.lstrip(".").lower() if c.isalnum())[:5]
            ext = safe if safe.startswith(".") and len(safe) > 1 else ".mp4"
            tmp = dest.with_suffix(ext)
            if tmp == dest:
                tmp = dest.with_name(dest.stem + "_dl" + ext)
        else:
            tmp = dest.with_suffix(ext)      # download with true extension first
        _download(str(cand["download_url"]), tmp, self.name, self.secret,
                  max_bytes=config.STOCK_VIDEO_MAX_BYTES if media == "video" else None)
        log("PEXELS", "Downloaded: {} (asset {}, {})".format(
            tmp.name, cand.get("asset_id", ""), media))
        if media == "video":
            if tmp.resolve() != dest.resolve():
                shutil.move(str(tmp), str(dest))
        else:
            normalize_photo(tmp, dest, width, height)
            try:
                tmp.unlink()
            except OSError:
                pass
        return {"path": str(dest), "width": width, "height": height}


# ------------------------------------------------------------ Pixabay provider
class PixabayProvider:
    """Official Pixabay API (https://pixabay.com/api, /api/videos).

    The key MUST travel as a query parameter (Pixabay requirement), so every
    error path is redacted and no URL is ever logged. SafeSearch is enabled via
    the documented `safesearch=true` parameter. Results are cached.
    """

    name = "pixabay"
    kind = "stock"
    _BASE = "https://pixabay.com/api"

    def __init__(self, api_key: str | None = None):
        self.secret = (api_key or config.PIXABAY_API_KEY or "").strip()

    def health(self) -> dict[str, Any]:
        if not self.secret:
            return {"ok": False, "provider": self.name, "status": "NO_API_KEY",
                    "note": "Set PIXABAY_API_KEY in .env to enable Pixabay stock."}
        try:
            self._search_cached("nature", "photo", 1, config.STOCK_MIN_WIDTH,
                                config.STOCK_MIN_HEIGHT)
            return {"ok": True, "provider": self.name, "status": "AVAILABLE"}
        except StockError as e:
            return {"ok": False, "provider": self.name, "status": "ERROR",
                    "error": redact(str(e), self.secret)}

    # -- internals --
    def _search_cached(self, query: str, media: str, count: int,
                       width: int, height: int) -> dict:
        raw_key = _api_cache_key(self.name, query, media, count, width, height,
                                  config.STOCK_SAFESEARCH)
        url = f"{self._BASE}{'/videos' if media == 'video' else ''}/"
        params = {"key": self.secret, "q": query,
                  "per_page": max(3, min(int(count), 50)),
                  "safesearch": "true" if config.STOCK_SAFESEARCH else "false",
                  "min_width": int(width), "min_height": int(height)}
        if media == "photo":
            params["image_type"] = "photo"
            params["orientation"] = "horizontal"
        else:
            params["video_type"] = "film"
        raw = cached_json(raw_key, lambda: _http_json(url, params, {}, self.name,
                                                       self.secret))
        return raw

    def search(self, query: str, media_type: str = "photo", count: int = 10,
               width: int = 1280, height: int = 720,
               settings: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if not self.secret:
            raise StockError("pixabay: PIXABAY_API_KEY is not configured.")
        count = max(1, min(int(count or config.STOCK_MAX_RESULTS), 50))
        if media_type == "video":
            return self._search_videos(query, count, width, height)
        data = self._search_cached(query, "photo", count, width, height)
        out: list[dict[str, Any]] = []
        for h in data.get("hits", [])[:count]:
            if not isinstance(h, dict):
                continue
            download = h.get("largeImageURL") or h.get("webformatURL")
            if not download:
                continue
            out.append(candidate(
                self.name, h.get("id", ""), "photo", download,
                int(h.get("imageWidth") or 0), int(h.get("imageHeight") or 0),
                source_url=h.get("pageURL", ""), creator=h.get("user", ""),
                license_="Pixabay Content License (free, attribution appreciated)",
                query=query, file_ext=".jpg", tags=str(h.get("tags") or ""),
                safesearch="true" if config.STOCK_SAFESEARCH else "provider-default"))
        return out

    def _search_videos(self, query: str, count: int, width: int, height: int
                       ) -> list[dict[str, Any]]:
        if not config.STOCK_ALLOW_VIDEO:
            return []
        data = self._search_cached(query, "video", count, width, height)
        out: list[dict[str, Any]] = []
        for v in data.get("hits", [])[:count]:
            if not isinstance(v, dict):
                continue
            variants = (v.get("videos") or {})
            if not isinstance(variants, dict):
                continue
            # Smallest variant that still meets the minimum frame size.
            pick = None
            for name in ("large", "medium", "small", "tiny"):
                info = variants.get(name) or {}
                if not isinstance(info, dict):
                    continue
                w, h = int(info.get("width") or 0), int(info.get("height") or 0)
                url = str(info.get("url") or "")
                if url and w >= width and h >= height:
                    pick = (url, w, h)
                    break
            if pick is None:  # too small everywhere -> largest as last resort
                info = variants.get("large") or {}
                if not isinstance(info, dict) or not info.get("url"):
                    continue
                pick = (str(info["url"]), int(info.get("width") or 0),
                        int(info.get("height") or 0))
            url, w, h = pick
            tail = url.split("?")[0].rsplit(".", 1)
            vext = ("." + "".join(c for c in tail[-1].lower() if c.isalnum())[:5]
                    if len(tail) > 1 else ".mp4")
            if len(vext) < 2:
                vext = ".mp4"
            out.append(candidate(
                self.name, v.get("id", ""), "video", url,
                w, h, source_url=v.get("pageURL", "") or url,
                creator=v.get("user", ""),
                license_="Pixabay Content License (free, attribution appreciated)",
                query=query, duration=float(v.get("duration") or 0.0),
                file_ext=vext,
                tags=str(v.get("tags") or ""), safesearch="true", has_text=False,
                nsfw=False))
        return out

    def fetch(self, cand: dict[str, Any], output_path: Path | str, width: int,
              height: int, settings: dict[str, Any] | None = None) -> dict[str, Any]:
        dest = Path(output_path)
        media = str(cand.get("media_type") or "photo")
        ext = str(cand.get("file_ext") or (".mp4" if media == "video" else ".png"))
        if media == "video":
            safe = "." + "".join(c for c in ext.lstrip(".").lower() if c.isalnum())[:5]
            ext = safe if safe.startswith(".") and len(safe) > 1 else ".mp4"
            tmp = dest.with_suffix(ext)
            if tmp == dest:
                tmp = dest.with_name(dest.stem + "_dl" + ext)
        else:
            tmp = dest.with_suffix(ext)
        _download(str(cand["download_url"]), tmp, self.name, self.secret,
                  max_bytes=config.STOCK_VIDEO_MAX_BYTES if media == "video" else None)
        if media == "video":
            if tmp.resolve() != dest.resolve():
                shutil.move(str(tmp), str(dest))
        else:
            normalize_photo(tmp, dest, width, height)
            try:
                tmp.unlink()
            except OSError:
                pass
        return {"path": str(dest), "width": width, "height": height}