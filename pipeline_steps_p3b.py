"""Part 3b steps: TOPIC_RANKING -> TOPIC_SELECTED -> SEO_GENERATION."""
from __future__ import annotations
import json
from app.core import config
from app.core.logger import log
from app.core.project_manager import ProjectManager
from app.core.state_manager import StateManager
from pipeline_steps_p3 import research_dir


def step_ranking(pm: ProjectManager, sm: StateManager, cands: list, trends: dict) -> list:
    from app.research import topic_scorer as ts
    from app.research import trend_discovery as td
    state = sm.load()
    pid = state["project_id"]
    rdir = research_dir(pm, pid)
    ranked_path = rdir / "ranked.json"
    if "TOPIC_RANKING" in state.get("completed_steps", []) and ranked_path.exists():
        log("TOPIC", "SKIPPED ranking (already completed)")
        return json.loads(ranked_path.read_text(encoding="utf-8"))
    sm.mark_started("TOPIC_RANKING")
    try:
        norm = json.loads((rdir / "normalized" / "records.json").read_text(encoding="utf-8"))
        src_titles = [r["title"] for r in norm]
        ms = [td.metrics(r) for r in norm] or [
            {"trend_score": 65.0, "freshness_score": 60.0, "engagement_score": 55.0}]
        agg = {k: sum(m[k] for m in ms) / len(ms) for k in
               ("trend_score", "freshness_score", "engagement_score")}
        ranked = []
        for c in cands:
            kws = c.get("search_keywords", [])
            comp = ts.competition_for(norm, kws)
            orig = ts.originality_check(c.get("topic", ""), src_titles)
            gap = str(c.get("content_gap", "")).lower()
            gap_score = 85.0 if any(g in gap for g in
                ["beginner", "practical", "steps", "modern", "myth", "mistake"]) else 65.0
            c = dict(c, competition=comp,
                     originality_check={"status": orig["status"],
                        "source_similarity_warning": orig["source_similarity_warning"]},
                     originality=orig, content_gap_score=gap_score,
                     search_intent=ts.search_intent(c.get("topic", ""), kws))
            s = ts.score_candidate(c, agg)
            ranked.append({**c, "score": s["score"], "components": s["components"]})
        ranked.sort(key=lambda x: x["score"], reverse=True)
        for i, r in enumerate(ranked, 1):
            r["rank"] = i
        ranked_path.write_text(json.dumps(ranked, indent=2), encoding="utf-8")
        sm.update({"top_score": ranked[0]["score"] if ranked else 0})
        sm.mark_completed("TOPIC_RANKING")
        if ranked:
            log("TOPIC", "Ranked candidate #1 score={}".format(ranked[0]["score"]))
        return ranked
    except Exception as e:
        sm.mark_failed("TOPIC_RANKING", str(e))
        raise
