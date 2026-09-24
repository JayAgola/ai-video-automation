"""Part 2 pipeline steps: VISUAL_GENERATION -> SCENE_CHUNKS -> FINAL_VIDEO."""
from __future__ import annotations
import json
from pathlib import Path
from app.core import config
from app.core.cache_manager import CacheManager
from app.core.logger import log
from app.core.project_manager import ProjectManager
from app.core.state_manager import StateManager

MOTIONS = ["zoom_in", "zoom_out", "pan_left", "pan_right"]


def _scene_key(sid: int) -> str:
    return "scene_{:03d}".format(sid)


def _get_scene_states(state: dict, field: str) -> dict:
    data = state.get("data", {})
    val = data.get(field, {})
    return dict(val) if isinstance(val, dict) else {}


def _set_scene_state(sm: StateManager, field: str, sid: int, status: str) -> None:
    state = sm.load()
    data = state.setdefault("data", {})
    slots = data.setdefault(field, {})
    slots[_scene_key(sid)] = status
    sm.save(state)


def step_visuals(pm: ProjectManager, sm: StateManager, script: dict,
                 provider=None, force: bool = False) -> dict:
    from app.visuals import visual_engine
    state = sm.load()
    pid = state["project_id"]
    visuals_dir = pm.visuals_dir(pid)
    visuals_dir.mkdir(parents=True, exist_ok=True)
    chunks_created = visuals_dir.parent / "chunks"
    chunks_created.mkdir(parents=True, exist_ok=True)
    out_created = visuals_dir.parent / "output"
    out_created.mkdir(parents=True, exist_ok=True)
    if ("VISUAL_GENERATION" in state.get("completed_steps", [])
            and not force
            and all(any((visuals_dir / "scene_{:03d}{}".format(int(s["scene_id"]), ext)).exists()
                        for ext in (".png", ".mp4"))
                    for s in script["scenes"])):
        log("VISUAL", "SKIPPED (already completed)")
        results = {}
        for s in script["scenes"]:
            sid = int(s["scene_id"])
            for ext in (".png", ".mp4"):
                p = visuals_dir / "scene_{:03d}{}".format(sid, ext)
                if p.exists():
                    results[sid] = p
                    break
        return results
    sm.mark_started("VISUAL_GENERATION")
    try:
        provider = provider or visual_engine.get_provider()
        cache = CacheManager(config.CACHE_DIR)
        results = {}
        failed = []
        for scene in sorted(script["scenes"], key=lambda s: int(s["scene_id"])):
            sid = int(scene["scene_id"])
            dest = visuals_dir / "scene_{:03d}.png".format(sid)
            if not force and _get_scene_states(sm.load(), "visuals").get(_scene_key(sid)) == "COMPLETED" \
                    and dest.exists() and dest.stat().st_size > 0:
                log("VISUAL", "Scene {}: SKIPPED (already completed)".format(sid))
                results[sid] = dest
                continue
            try:
                path, meta, hit = visual_engine.generate_scene_image(
                    pid, scene, script, visuals_dir, cache, provider,
                    state=sm.load())
                results[sid] = path
                _set_scene_state(sm, "visuals", sid, "COMPLETED")
                sm.update({"visual_meta_{:03d}".format(sid): meta})
                log("VISUAL", "Scene {}: {} ({})".format(
                    sid, "CACHE HIT" if hit else "generated", Path(path).name))
            except Exception as e:
                failed.append(sid)
                _set_scene_state(sm, "visuals", sid, "FAILED")
                sm.update({"last_error_visual_{:03d}".format(sid): str(e)[:1000]})
                log("ERROR", "Scene {} visual FAILED: {}".format(sid, e))
        if failed:
            raise RuntimeError("Visual generation failed for scenes: {}".format(failed))
        sm.mark_completed("VISUAL_GENERATION")
        return results
    except Exception as e:
        sm.mark_failed("VISUAL_GENERATION", str(e))
        raise
