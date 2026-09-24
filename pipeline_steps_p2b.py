"""Part 2b steps: SCENE_CHUNKS -> FINAL_VIDEO."""
from __future__ import annotations
import json
from pathlib import Path
from app.core import config
from app.core.cache_manager import CacheManager
from app.core.logger import log
from app.core.project_manager import ProjectManager
from app.core.state_manager import StateManager
from pipeline_steps_p2 import MOTIONS, _get_scene_states, _scene_key, _set_scene_state


def step_chunks(pm: ProjectManager, sm: StateManager, script: dict,
                force: bool = False) -> list:
    from app.video import chunk_renderer
    from app.visuals.visual_engine import scene_caption
    state = sm.load()
    pid = state["project_id"]
    visuals_dir = pm.visuals_dir(pid)
    audio_dir = pm.audio_dir(pid)
    chunks_dir = pm.chunks_dir(pid)
    chunks_dir.mkdir(parents=True, exist_ok=True)
    ordered = sorted(script["scenes"], key=lambda s: int(s["scene_id"]))
    if ("SCENE_CHUNKS" in state.get("completed_steps", []) and not force
            and all((chunks_dir / "scene_{:03d}.mp4".format(int(s["scene_id"]))).exists()
                    for s in ordered)):
        log("VIDEO", "SKIPPED (already completed)")
        return [chunks_dir / "scene_{:03d}.mp4".format(int(s["scene_id"])) for s in ordered]
    sm.mark_started("SCENE_CHUNKS")
    try:
        cache = CacheManager(config.CACHE_DIR)
        chunks = []
        failed = []
        for i, scene in enumerate(ordered):
            sid = int(scene["scene_id"])
            img = visuals_dir / "scene_{:03d}.png".format(sid)
            aud = audio_dir / "scene_{:03d}.mp3".format(sid)
            out = chunks_dir / "scene_{:03d}.mp4".format(sid)
            motion = MOTIONS[i % len(MOTIONS)]
            if not force and _get_scene_states(sm.load(), "chunks").get(_scene_key(sid)) == "COMPLETED" \
                    and out.exists() and out.stat().st_size > 0:
                log("VIDEO", "Scene {}: SKIPPED (already completed)".format(sid))
                chunks.append(out)
                continue
            try:
                caption = scene_caption(scene)
                # Hybrid Part 2.2: stock VIDEO source renders via the same
                # renderer family (normalize + caption + narration trim).
                vid = visuals_dir / "scene_{:03d}.mp4".format(sid)
                meta = sm.load().get("data", {}).get("visual_meta_{:03d}".format(sid), {})
                use_video = (meta.get("media_type") == "video"
                             and vid.exists() and vid.stat().st_size > 0)
                if use_video:
                    path, dur, reused = chunk_renderer.render_scene_chunk_video(
                        vid, aud, out, cache, caption_text=caption)
                else:
                    path, dur, reused = chunk_renderer.render_scene_chunk(
                        img, aud, out, motion, cache, caption_text=caption)
                chunks.append(path)
                _set_scene_state(sm, "chunks", sid, "COMPLETED")
                sm.update({f"chunk_duration_{sid:03d}": dur,
                           f"chunk_caption_{sid:03d}": (caption[:200] if caption else "")})
            except Exception as e:
                failed.append(sid)
                _set_scene_state(sm, "chunks", sid, "FAILED")
                sm.update({"last_error_chunk_{:03d}".format(sid): str(e)[:1000]})
                log("ERROR", "Scene {} chunk FAILED: {}".format(sid, e))
        if failed:
            raise RuntimeError("Chunk rendering failed for scenes: {}".format(failed))
        sm.mark_completed("SCENE_CHUNKS")
        return chunks
    except Exception as e:
        sm.mark_failed("SCENE_CHUNKS", str(e))
        raise


def step_final(pm: ProjectManager, sm: StateManager, script: dict, force: bool = False) -> Path:
    from app.video import final_concat
    state = sm.load()
    pid = state["project_id"]
    chunks_dir = pm.chunks_dir(pid)
    audio_dir = pm.audio_dir(pid)
    out = pm.final_video_path(pid)
    ordered = [chunks_dir / "scene_{:03d}.mp4".format(int(s["scene_id"]))
               for s in sorted(script["scenes"], key=lambda s: int(s["scene_id"]))]
    missing = [str(c) for c in ordered if not c.exists()]
    if missing:
        raise FileNotFoundError("Missing chunks for concat: {}".format(missing))
    mixed = audio_dir / "mixed_audio.mp3"
    voice = audio_dir / "voiceover.mp3"
    # Prefer voice+BGM mix; fall back to plain voiceover (never silent/missing).
    audio_track = mixed if mixed.exists() else (voice if voice.exists() else None)
    # Rebuild final if it was made before the BGM-mux fix (old finals keep only
    # chunk voiceovers). Force flag also rebuilds on demand.
    needs_bgm_rebuild = (
        not force
        and "FINAL_VIDEO" in state.get("completed_steps", [])
        and out.exists() and out.stat().st_size > 0
        and "final_audio" not in state.get("data", {})
    )
    if (not force and not needs_bgm_rebuild
            and "FINAL_VIDEO" in state.get("completed_steps", []) and out.exists()
            and out.stat().st_size > 0):
        log("VIDEO", "SKIPPED final (already completed)")
        return out
    sm.mark_started("FINAL_VIDEO")
    try:
        path, dur = final_concat.concat_chunks(ordered, out, audio_track, force=True)
        sm.update({"final_video_path": str(path), "final_video_duration": dur,
                   "final_audio": Path(audio_track).name if audio_track else "chunks",
                   "review_status": state.get("data", {}).get("review_status", "DRAFT")})
        sm.mark_completed("FINAL_VIDEO")
        return path
    except Exception as e:
        sm.mark_failed("FINAL_VIDEO", str(e))
        raise
