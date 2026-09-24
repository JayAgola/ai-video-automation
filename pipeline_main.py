"""Full pipeline entrypoint (Parts 1 + Part 2). Preserves Part 1 CLI."""
from __future__ import annotations
import argparse
import json
import sys
from app.core import config
from app.core.logger import log
from app.core.project_manager import ProjectManager
from pipeline_steps import step_bgm, step_mix, step_script, step_tts
from pipeline_steps_p2 import step_visuals
from pipeline_steps_p2b import step_chunks, step_final
from pipeline_steps_p3 import step_research, step_topics
from pipeline_steps_p3b import step_ranking
from pipeline_steps_p3c import step_select, step_seo


def run_research(project_id: str, queries=None, top: int = 0, select=None,
                 force_research: bool = False) -> int:
    config.ensure_dirs()
    pm = ProjectManager()
    pm.create_project(project_id)
    sm = pm.state_manager(project_id)
    try:
        trends = step_research(pm, sm, queries, force_research)
        cands = step_topics(pm, sm, trends)
        ranked = step_ranking(pm, sm, cands, trends)
        for r in (ranked[:top] if top > 0 else ranked[:10]):
            print("#{} score={} :: {}".format(r["rank"], r["score"], r["topic"]))
        if select is not None:
            sel = step_select(pm, sm, ranked, select - 1 if select > 0 else 0)
            step_seo(pm, sm, sel)
            print("Selected: {}".format(sel["topic"]))
        return 0
    except Exception as e:
        log("ERROR", "Research failed: {}".format(e))
        return 1


def script_is_resumable(state: dict) -> bool:
    """True when --resume may (re)run SCRIPT for this project.

    A step recorded in failed_steps is exactly what resume must retry (risk: the
    earlier version refused any SCRIPT that was not yet completed, so a project
    that failed *at* SCRIPT, like llama3.2:3b emitting empty narration, could
    never be resumed). Only a SCRIPT that was never attempted is refused.
    """
    completed = set(state.get("completed_steps", []))
    failed = set(state.get("failed_steps", []))
    return "SCRIPT" in completed or "SCRIPT" in failed


def run(project_id: str, topic: str, force_visuals: bool = False,
        force_chunks: bool = False, resume_only: bool = False,
        force_final: bool = False) -> int:
    config.ensure_dirs()
    pm = ProjectManager()
    pm.create_project(project_id)
    sm = pm.state_manager(project_id)

    state = sm.load()
    if (sm.next_incomplete_step() is None
            and not (force_visuals or force_chunks or force_final)):
        log("PIPELINE", "Project already completed (all steps).")
        return 0
    log("PROJECT", "{} | resume from: {}".format(project_id, sm.next_incomplete_step()))
    topic = topic or state.get("data", {}).get("topic") or "How to stop overthinking"
    script_path = pm.script_path(project_id)
    # Manual --topic mode: mark research steps satisfied so legacy states and
    # explicit topics flow straight into the media pipeline (Part 3 skippable).
    if topic and not getattr(config, "USE_RESEARCH_FLOW", False):
        cur = sm.load()
        done = set(cur.get("completed_steps", []))
        if not any(s in done for s in config.P3_STEPS):
            cur["completed_steps"] = list(done | set(config.P3_STEPS))
            sm.save(cur)
    try:
        if "SCRIPT" in sm.load().get("completed_steps", []) and script_path.exists():
            log("SCRIPT", "SKIPPED (already completed)")
            script = json.loads(script_path.read_text(encoding="utf-8"))
        else:
            if resume_only and not script_is_resumable(sm.load()):
                raise RuntimeError("resume requested but SCRIPT not completed")
            script = step_script(pm, sm, topic)
        step_tts(pm, sm, script)
        step_bgm(pm, sm, script)
        step_mix(pm, sm)
        step_visuals(pm, sm, script, force=force_visuals)
        step_chunks(pm, sm, script, force=force_chunks)
        step_final(pm, sm, script, force=force_final)
    except Exception as e:
        log("ERROR", "Pipeline stopped: {}".format(e))
        log("PIPELINE", "Resume with: python pipeline.py --project {}".format(project_id))
        return 1
    log("PIPELINE", "Pipeline completed (Parts 1+2+3)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="YT automation pipeline (Parts 1+2+3)")
    ap.add_argument("--project", default="video_001")
    ap.add_argument("--topic", default="")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--resume", action="store_true",
                    help="resume only (fail if next step was never completed)")
    ap.add_argument("--force-visuals", action="store_true")
    ap.add_argument("--force-chunks", action="store_true")
    ap.add_argument("--force-final", action="store_true",
                    help="rebuild final video (re-mux voice+BGM) even if done")
    ap.add_argument("--full", action="store_true",
                    help="run the complete media pipeline (SCRIPT->TTS->BGM->MIX->"
                         "VISUALS->CHUNKS->FINAL); reuses valid cached artifacts, "
                         "never uploads to YouTube")
    ap.add_argument("--visual-health", action="store_true",
                    help="print visual provider health and exit")
    ap.add_argument("--research", action="store_true",
                    help="run research/topic/SEO flow instead of video pipeline")
    ap.add_argument("--query", default="", help="single research query (with --research)")
    ap.add_argument("--top", type=int, default=0, help="show top N ranked topics")
    ap.add_argument("--select", type=int, default=None,
                    help="1-based rank to select + generate SEO for")
    ap.add_argument("--force-research", action="store_true")
    ap.add_argument("--force-topic", action="store_true")
    ap.add_argument("--force-seo", action="store_true")
    ap.add_argument("--research-health", action="store_true",
                    help="print research provider health and exit")
    args = ap.parse_args(argv)
    if args.status:
        pm = ProjectManager()
        print(json.dumps(pm.load_project(args.project), indent=2))
        return 0
    if args.visual_health:
        from app.visuals import visual_engine
        print(json.dumps(visual_engine.provider_health(), indent=2))
        return 0
    if args.research_health:
        from app.research import research_engine
        print(json.dumps(research_engine.research_health(), indent=2))
        return 0
    if args.research:
        queries = [args.query] if args.query else None
        return run_research(args.project, queries, args.top, args.select,
                            args.force_research or args.force_topic or args.force_seo)
    if args.full:
        log("PIPELINE", "Full media pipeline requested (cached artifacts reused)")
    return run(args.project, args.topic, args.force_visuals, args.force_chunks, args.resume,
               args.force_final)


if __name__ == "__main__":
    sys.exit(main())

