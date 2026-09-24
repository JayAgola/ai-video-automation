"""Part 3 pipeline steps: RESEARCH -> TOPIC_DISCOVERY -> TOPIC_RANKING -> TOPIC_SELECTED -> SEO_GENERATION."""
from __future__ import annotations
import datetime
import json
from pathlib import Path
from app.core import config
from app.core.cache_manager import CacheManager
from app.core.logger import log
from app.core.project_manager import ProjectManager
from app.core.state_manager import StateManager


def research_dir(pm: ProjectManager, pid: str) -> Path:
    d = pm.project_path(pid) / "research"
    (d / "raw").mkdir(parents=True, exist_ok=True)
    (d / "normalized").mkdir(parents=True, exist_ok=True)
    return d


def step_research(pm: ProjectManager, sm: StateManager, queries=None,
                  force: bool = False, provider=None) -> dict:
    from app.research import research_engine as re, trend_discovery as td
    state = sm.load()
    pid = state["project_id"]
    rdir = research_dir(pm, pid)
    trends_path = rdir / "trends.json"
    if "RESEARCH" in state.get("completed_steps", []) and trends_path.exists() and not force:
        log("RESEARCH", "SKIPPED (already completed)")
        return json.loads(trends_path.read_text(encoding="utf-8"))
    sm.mark_started("RESEARCH")
    try:
        provider = provider or re.get_research_provider()
        cache = CacheManager(config.CACHE_DIR)
        queries = (queries or config.RESEARCH_QUERIES)[:config.YOUTUBE_MAX_QUERIES_PER_RUN]
        all_raw, all_norm, hits = [], [], 0
        failed = []
        for q in queries:
            log("RESEARCH", "Searching: {}".format(q))
            try:
                raw, hit = re.cached_search(provider, q, cache, config.YOUTUBE_MAX_RESULTS,
                                            config.RESEARCH_REGION, config.CHANNEL_LANGUAGE, force)
                hits += 1 if hit else 0
                (rdir / "raw" / "{}.json".format(re.cache_key_for(
                    q, provider.name, config.RESEARCH_REGION,
                    config.CHANNEL_LANGUAGE, config.YOUTUBE_MAX_RESULTS))).write_text(
                    json.dumps(raw[:5], indent=1), encoding="utf-8")
                all_raw.extend(raw)
                all_norm.extend([td.normalize(r) for r in raw])
            except Exception as e:
                failed.append(q)
                log("ERROR", "Query {!r} failed: {}".format(q, str(e)[:200]))
        if not all_norm:
            raise RuntimeError("No research results (failed: {}). Use manual --topic.".format(failed))
        seen, dedup = set(), []
        for r in all_norm:
            if r["video_id"] not in seen:
                seen.add(r["video_id"])
                dedup.append(r)
        (rdir / "normalized" / "records.json").write_text(
            json.dumps(dedup, indent=1), encoding="utf-8")
        trends = td.discover_trends(dedup)
        trends.update({"queries": queries, "failed_queries": failed,
                       "provider": provider.name,
                       "test_data": getattr(provider, "test_data", False),
                       "total_raw": len(all_raw), "total_unique": len(dedup),
                       "cache_hits": hits, "niche": config.CHANNEL_NICHE,
                       "date": datetime.datetime.now(datetime.timezone.utc).isoformat()})
        trends_path.write_text(json.dumps(trends, indent=2), encoding="utf-8")
        sm.update({"research_queries": queries, "research_total": len(dedup),
                   "research_provider": provider.name})
        sm.mark_completed("RESEARCH")
        log("TREND", "Analyzed {} results".format(len(dedup)))
        return trends
    except Exception as e:
        sm.mark_failed("RESEARCH", str(e))
        raise


def step_topics(pm: ProjectManager, sm: StateManager, trends: dict,
                client=None, count: int = 0) -> list:
    from app.research import topic_generator as tg
    state = sm.load()
    pid = state["project_id"]
    rdir = research_dir(pm, pid)
    tpath = rdir / "topics.json"
    if "TOPIC_DISCOVERY" in state.get("completed_steps", []) and tpath.exists():
        log("TOPIC", "SKIPPED discovery (already completed)")
        return json.loads(tpath.read_text(encoding="utf-8"))
    sm.mark_started("TOPIC_DISCOVERY")
    try:
        sample = trends.get("top_patterns", [])
        summary = tg.build_summary(trends, sample, config.CHANNEL_NICHE)
        cands = tg.generate_candidates(summary, trends, sample, client, count or config.TOPIC_COUNT)
        tpath.write_text(json.dumps(cands, indent=2), encoding="utf-8")
        sm.update({"topic_count": len(cands)})
        sm.mark_completed("TOPIC_DISCOVERY")
        log("TOPIC", "Generated {} candidates".format(len(cands)))
        return cands
    except Exception as e:
        sm.mark_failed("TOPIC_DISCOVERY", str(e))
        raise
