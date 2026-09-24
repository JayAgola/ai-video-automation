"""Part 3c steps: TOPIC_SELECTED -> SEO_GENERATION."""
from __future__ import annotations
import json
from app.core import config
from app.core.logger import log
from app.core.project_manager import ProjectManager
from app.core.state_manager import StateManager
from pipeline_steps_p3 import research_dir


def step_select(pm: ProjectManager, sm: StateManager, ranked: list, index: int = 0) -> dict:
    state = sm.load()
    pid = state["project_id"]
    rdir = research_dir(pm, pid)
    sel_path = rdir / "selected_topic.json"
    if "TOPIC_SELECTED" in state.get("completed_steps", []) and sel_path.exists():
        log("TOPIC", "SKIPPED selection (already completed)")
        return json.loads(sel_path.read_text(encoding="utf-8"))
    sm.mark_started("TOPIC_SELECTED")
    try:
        if not ranked:
            raise ValueError("No ranked candidates to select.")
        sel = ranked[min(index, len(ranked) - 1)]
        sel_path.write_text(json.dumps(sel, indent=2), encoding="utf-8")
        sm.update({"selected_topic": sel["topic"], "selected_score": sel["score"]})
        sm.mark_completed("TOPIC_SELECTED")
        return sel
    except Exception as e:
        sm.mark_failed("TOPIC_SELECTED", str(e))
        raise


def step_seo(pm: ProjectManager, sm: StateManager, selected: dict) -> dict:
    from app.research import seo_engine as seo
    from pipeline_steps_p3d import write_report
    state = sm.load()
    pid = state["project_id"]
    rdir = research_dir(pm, pid)
    seo_path = rdir / "seo.json"
    if "SEO_GENERATION" in state.get("completed_steps", []) and seo_path.exists():
        log("SEO", "SKIPPED (already completed)")
        return json.loads(seo_path.read_text(encoding="utf-8"))
    sm.mark_started("SEO_GENERATION")
    try:
        kws = selected.get("search_keywords", [])
        package = seo.generate_seo(selected["topic"], kws, config.TARGET_AUDIENCE,
                                   selected.get("angle", ""))
        scored = [seo.score_title(t, kws) for t in package["title_options"]]
        scored.sort(key=lambda x: x["score"], reverse=True)
        package["title_scores"] = scored
        package["recommended_title"] = scored[0]["title"] if scored else selected["topic"]
        package.update(seo.thumbnail_concepts(selected["topic"], kws))
        seo_path.write_text(json.dumps(package, indent=2), encoding="utf-8")
        write_report(pm, pid, selected, package)
        sm.update({"recommended_title": package["recommended_title"]})
        sm.mark_completed("SEO_GENERATION")
        log("SEO", "Generated {} title options".format(len(package["title_options"])))
        return package
    except Exception as e:
        sm.mark_failed("SEO_GENERATION", str(e))
        raise
