"""Research engine: cached search + normalize + metrics (part A)."""
from __future__ import annotations
import datetime
import hashlib
import json
import time
from pathlib import Path
from typing import Any
from app.core import config
from app.core.cache_manager import CacheManager
from app.core.logger import log


def get_research_provider(name: str | None = None):
    from app.research.test_provider import TestResearchProvider
    from app.research.youtube_provider import YouTubeProvider
    name = (name or ("test" if config.TEST_RESEARCH_MODE or
                     config.RESEARCH_PROVIDER == "test" else config.RESEARCH_PROVIDER))
    if name == "test":
        return TestResearchProvider()
    if name == "youtube":
        return YouTubeProvider()
    raise ValueError("RESEARCH PROVIDER NOT CONFIGURED: {!r}.".format(name))


def research_health(name: str | None = None) -> dict[str, Any]:
    try:
        return get_research_provider(name).health()
    except Exception as e:
        return {"ok": False, "error": str(e)}


def cache_key_for(query: str, provider: str, region: str, language: str,
                  max_results: int) -> str:
    payload = "{}||{}||{}||{}".format(query.strip().lower(), region, language, max_results)
    return hashlib.sha256("{}||{}".format(payload, provider).encode()).hexdigest()


def _fresh(path: Path, ttl_h: float) -> bool:
    return (time.time() - path.stat().st_mtime) / 3600.0 <= ttl_h


def cached_search(provider, query: str, cache: CacheManager, max_results: int = 25,
                  region: str = "US", language: str = "en",
                  force: bool = False) -> tuple:
    key = cache_key_for(query, provider.name, region, language, max_results)
    path = cache.cache_dir / "research" / (key + ".json")
    if not force and path.exists() and path.stat().st_size > 0 and _fresh(path, config.RESEARCH_CACHE_TTL_HOURS):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            log("CACHE", "research cache HIT {}".format(query))
            return data.get("records", []), True
        except Exception:
            log("CACHE", "research cache corrupted, refetching {}".format(query))
    log("CACHE", "research cache MISS {}".format(query))
    last_err = ""
    for attempt in range(1, 4):
        try:
            records = provider.search(query, max_results, region, language)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"query": query, "provider": provider.name,
                                       "test_data": getattr(provider, "test_data", False),
                                       "records": records}, indent=1), encoding="utf-8")
            tmp.replace(path)
            log("RESEARCH", "Retrieved {} videos for {!r}".format(len(records), query))
            return records, False
        except Exception as e:
            last_err = str(e)[:400]
            log("ERROR", "Research attempt {} for {!r}: {}".format(attempt, query, last_err))
            time.sleep(2 * attempt)
    raise RuntimeError("Research failed for {!r}: {}".format(query, last_err))
