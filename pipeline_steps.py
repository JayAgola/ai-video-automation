"""Part 1 pipeline steps (imported by pipeline.py)."""
from __future__ import annotations
import json
from pathlib import Path
from app.audio.audio_mixer import concat_voiceovers, mix_voice_bgm
from app.audio.bgm_manager import prepare_bgm, select_track
from app.audio.duration import get_audio_duration
from app.audio.tts_engine import synthesize_narration
from app.core import config
from app.core.cache_manager import CacheManager
from app.core.logger import log
from app.core.project_manager import ProjectManager
from app.core.state_manager import StateManager
from app.llm.ollama_client import OllamaClient
from app.script import script_engine

def step_script(pm: ProjectManager, sm: StateManager, topic: str) -> dict:
    state = sm.load()
    script_path = pm.script_path(state["project_id"])
    if "SCRIPT" in state.get("completed_steps", []) and script_path.exists():
        log("SCRIPT", "SKIPPED (already completed)")
        return json.loads(script_path.read_text(encoding="utf-8"))
    sm.mark_started("SCRIPT")
    try:
        client = OllamaClient()
        conn = client.check_connection()
        if not conn["ok"]:
            raise RuntimeError(f"Ollama offline: {conn.get('error')}")
        chk = client.check_model()
        if not chk["ok"]:
            raise RuntimeError(chk.get("error", "model unavailable"))
        # Dedicated long-form script model (config.SCRIPT_MODEL) with a graceful
        # fallback to the just-verified text model when it is not installed.
        # Model selection stays in config + the existing Ollama client (no hardcoded
        # model inside the script engine).
        preferred = str(getattr(config, "SCRIPT_MODEL", "") or "")
        script_model = script_engine.resolve_script_model(
            chk.get("models") or [], preferred, config.OLLAMA_TEXT_MODEL)
        if preferred and script_model != preferred:
            log("SCRIPT", f"SCRIPT_MODEL '{preferred}' not installed -> {script_model}")
        if script_model and script_model != client.text_model:
            log("SCRIPT", f"Using script model: {script_model}")
            client = OllamaClient(text_model=script_model)
        script = script_engine.generate_script(topic or "How to stop overthinking", client,
                                               target_seconds=210, num_scenes=9,
                                               max_retries=max(2, config.SCRIPT_EXPAND_RETRIES))
        script_engine.save_script(script, script_path)
        sm.update({"topic": topic, "title": script.get("title"),
                   "num_scenes": len(script.get("scenes", [])),
                   "script_estimated_duration": script_engine.script_estimated_total(script)})
        sm.mark_completed("SCRIPT")
        return script
    except Exception as e:
        sm.mark_failed("SCRIPT", str(e))
        raise


def step_tts(pm: ProjectManager, sm: StateManager, script: dict) -> Path:
    state = sm.load()
    pid = state["project_id"]
    audio_dir = pm.audio_dir(pid)
    voice_path = audio_dir / "voiceover.mp3"
    if "TTS" in state.get("completed_steps", []) and voice_path.exists():
        log("TTS", "SKIPPED (already completed)")
        return voice_path
    sm.mark_started("TTS")
    try:
        cache = CacheManager(config.CACHE_DIR)
        scene_files: list[Path] = []
        durations: list[float] = []
        for sc in script["scenes"]:
            sid = int(sc["scene_id"])
            dest = audio_dir / f"scene_{sid:03d}.mp3"
            if dest.exists() and dest.stat().st_size > 0:
                log("TTS", f"Reuse {dest.name}")
            else:
                _, _, hit = synthesize_narration(sc["narration"], cache=cache, dest=dest)
                log("TTS", f"{'CACHE HIT' if hit else 'Generated'} {dest.name}")
            scene_files.append(dest)
            durations.append(get_audio_duration(dest))
        concat_voiceovers(scene_files, voice_path)
        total = get_audio_duration(voice_path)
        lo = float(config.SCRIPT_TARGET_MIN_SECONDS)
        hi = float(config.SCRIPT_TARGET_MAX_SECONDS)
        log("TTS", "Actual narration duration: {:.1f}s".format(total))
        log("TARGET", "{:.0f}-{:.0f}s".format(lo, hi))
        sm.update({"scene_durations": durations, "voiceover_path": str(voice_path),
                   "voiceover_duration": total})
        if total < lo:
            raise ValueError(
                "Narration too short for long-form: actual {:.1f}s "
                "below target {:.0f}-{:.0f}s. The SCRIPT length gate should "
                "have expanded it; refusing a short video.".format(total, lo, hi))
        sm.mark_completed("TTS")
        return voice_path
    except Exception as e:
        sm.mark_failed("TTS", str(e))
        raise


def step_bgm(pm: ProjectManager, sm: StateManager, script: dict) -> Path:
    state = sm.load()
    pid = state["project_id"]
    audio_dir = pm.audio_dir(pid)
    bgm_dest = audio_dir / "background_music.mp3"
    if "BGM" in state.get("completed_steps", []) and bgm_dest.exists():
        log("BGM", "SKIPPED (already completed)")
        return bgm_dest
    sm.mark_started("BGM")
    try:
        voice_dur = float(state.get("data", {}).get("voiceover_duration") or 0)
        if voice_dur <= 0:
            voice_dur = float(sum(s.get("estimated_duration_seconds", 20)
                                  for s in script.get("scenes", [])) or 60)
        track = select_track(script.get("bgm_style", ""), deterministic=True, seed=pid)
        prepare_bgm(track, bgm_dest, voice_dur)
        sm.update({"bgm_track": track.name, "bgm_path": str(bgm_dest)})
        sm.mark_completed("BGM")
        return bgm_dest
    except Exception as e:
        sm.mark_failed("BGM", str(e))
        raise


def step_mix(pm: ProjectManager, sm: StateManager) -> Path:
    state = sm.load()
    pid = state["project_id"]
    audio_dir = pm.audio_dir(pid)
    out = audio_dir / "mixed_audio.mp3"
    if "MIX" in state.get("completed_steps", []) and out.exists():
        log("AUDIO", "SKIPPED (already completed)")
        return out
    sm.mark_started("MIX")
    try:
        mix_voice_bgm(audio_dir / "voiceover.mp3", audio_dir / "background_music.mp3", out)
        sm.update({"mixed_audio_path": str(out),
                   "mixed_duration": get_audio_duration(out)})
        sm.mark_completed("MIX")
        return out
    except Exception as e:
        sm.mark_failed("MIX", str(e))
        raise
