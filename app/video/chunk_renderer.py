"""Scene chunk renderer: IMAGE + scene AUDIO + caption overlay + Ken Burns -> scene_NNN.mp4.

Renderer inputs per scene: image_path, audio_path, caption_text, duration.
Caption text is burned as video text here — it NEVER goes to the image generator.
"""
from __future__ import annotations
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any
from app.audio.duration import get_audio_duration
from app.core import config
from app.core.cache_manager import CacheManager
from app.core.logger import log


def has_nvenc() -> bool:
    try:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-h", "encoder=h264_nvenc"],
                           capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            return False
        # Verify a real NVENC encode works (driver may be too old despite listing).
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            src = str(Path(td) / "in.png")
            out = str(Path(td) / "out.mp4")
            from PIL import Image
            Image.new("RGB", (320, 180), (10, 20, 30)).save(src)
            t = subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", src,
                 "-t", "0.5", "-c:v", "h264_nvenc", out],
                capture_output=True, text=True, timeout=60)
            return t.returncode == 0
    except Exception:
        return False


def video_duration(path: Path | str) -> float:
    r = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json",
                        "-show_format", str(path)],
                       capture_output=True, text=True, timeout=30)
    return float(json.loads(r.stdout)["format"]["duration"])


def _enc_args() -> list[str]:
    if has_nvenc():
        log("VIDEO", "Encoder: h264_nvenc")
        return ["-c:v", "h264_nvenc", "-cq", str(config.VIDEO_CRF), "-preset",
                "p4" if config.VIDEO_PRESET == "medium" else "p7"]
    log("VIDEO", "Encoder: libx264 (CPU fallback)")
    return ["-c:v", "libx264", "-crf", str(config.VIDEO_CRF), "-preset", config.VIDEO_PRESET]


def chunk_cache_key(image: Path, audio: Path, settings: dict) -> str:
    import hashlib
    ih = hashlib.sha256(image.read_bytes()).hexdigest() if image.exists() else image.name
    ah = hashlib.sha256(audio.read_bytes()).hexdigest() if audio.exists() else audio.name
    settings = dict(settings or {})
    # Caption is part of the frame: same image+audio but different caption => new chunk.
    settings.setdefault("caption_version", config.CAPTION_VERSION)
    return CacheManager.hash_key(f"{ih}||{ah}", settings)


def renderer_settings(motion: str = "zoom_in", caption_text: str = "") -> dict:
    return {"motion": motion, "fps": config.VIDEO_FPS, "width": config.VIDEO_WIDTH,
            "height": config.VIDEO_HEIGHT, "crf": config.VIDEO_CRF,
            "preset": config.VIDEO_PRESET,
            "caption_version": config.CAPTION_VERSION,
            "caption_enabled": bool(config.CAPTION_ENABLED and str(caption_text or "").strip()),
            "caption_hash": __import__("hashlib").sha256(
                str(caption_text or "").encode("utf-8")).hexdigest()[:16]}


def _zoompan_filter(duration: float, motion: str) -> str:
    frames = max(int(duration * config.VIDEO_FPS), 1)
    W, H = config.VIDEO_WIDTH, config.VIDEO_HEIGHT
    fps = config.VIDEO_FPS
    if motion == "zoom_out":
        return ("scale=2400:-2,zoompan=z='1.08-0.08*on/{0}':x='iw/2-(iw/zoom/2)':"
                "y='ih/2-(ih/zoom/2)':d={0}:fps={1}:s={2}x{3}").format(frames, fps, W, H)
    if motion == "pan_left":
        return ("scale=2400:-2,zoompan=z=1.08:x='iw/2-(iw/zoom/2)-on*{4}/{0}':"
                "y='ih/2-(ih/zoom/2)':d={0}:fps={1}:s={2}x{3}").format(frames, fps, W, H, 600)
    if motion == "pan_right":
        return ("scale=2400:-2,zoompan=z=1.08:x='iw/2-(iw/zoom/2)+on*{4}/{0}':"
                "y='ih/2-(ih/zoom/2)':d={0}:fps={1}:s={2}x{3}").format(frames, fps, W, H, 600)
    return ("scale=2400:-2,zoompan=z='1.0+0.08*on/{0}':x='iw/2-(iw/zoom/2)':"
            "y='ih/2-(ih/zoom/2)':d={0}:fps={1}:s={2}x{3}").format(frames, fps, W, H)


def render_scene_chunk_video(video, audio, output, cache=None, caption_text: str = ""):
    """Stock VIDEO scene: normalize to 16:9, overlay caption (same style as the
    image path), replace source audio with the narration, trim to narration.

    Reuses the SAME cache categories/settings as render_scene_chunk (one
    renderer, one cache), so no second rendering path exists.
    """
    import subprocess as _sp
    video, audio, output = Path(video), Path(audio), Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if not video.exists():
        raise FileNotFoundError("Scene stock video missing: {}".format(video))
    if not audio.exists():
        raise FileNotFoundError("Scene audio missing: {}".format(audio))
    W, H, fps = config.VIDEO_WIDTH, config.VIDEO_HEIGHT, config.VIDEO_FPS
    audio_dur = get_audio_duration(audio)
    settings = dict(renderer_settings("stock_video", caption_text))
    settings["source_media"] = "video"
    key = chunk_cache_key(video, audio, settings)
    cache = cache or CacheManager(config.CACHE_DIR)
    cached = cache.get("chunks", key, ".mp4")
    if output.exists() and output.stat().st_size > 0:
        try:
            if abs(video_duration(output) - audio_dur) < 0.6:
                log("VIDEO", "Reuse {} ({:.1f}s, stock video)".format(output.name, audio_dur))
                return output, audio_dur, True
        except Exception:
            pass
    if cached is not None:
        _shutil.copyfile(str(cached), str(output))
        log("VIDEO", "CACHE HIT -> {} (stock video)".format(output.name))
        return output, audio_dur, True
    # Caption overlay: extract first frame -> same Pillow overlay as images.
    overlay_arg = []
    framed = None
    if config.CAPTION_ENABLED and str(caption_text or "").strip():
        from app.video.caption_overlay import overlay_caption
        frame = output.with_name(output.stem + "_srcframe.png")
        framed = output.with_name(output.stem + "_framed.png")
        r = _sp.run(["ffmpeg", "-y", "-v", "error", "-i", str(video),
                     "-frames:v", "1", str(frame)], capture_output=True, text=True,
                    timeout=120)
        if r.returncode != 0 or not frame.exists():
            raise RuntimeError("Stock frame extraction failed: {}".format(r.stderr[:300]))
        overlay_caption(frame, caption_text, framed)
        try:
            frame.unlink()
        except OSError:
            pass
        overlay_arg = ["-i", str(framed)]
        fc = ("[0:v]scale={0}:{1}:force_original_aspect_ratio=increase,"
              "crop={0}:{1},setsar=1[v0];[v0][1:v]overlay=0:0[v]").format(W, H)
    else:
        fc = ("[0:v]scale={0}:{1}:force_original_aspect_ratio=increase,"
              "crop={0}:{1},setsar=1[v]").format(W, H)
    cmd = (["ffmpeg", "-y", "-v", "error", "-i", str(video)] + overlay_arg +
           ["-i", str(audio), "-filter_complex", fc, "-map", "[v]",
            "-map", "2:a" if overlay_arg else "1:a",
            "-t", "{:.2f}".format(audio_dur), "-r", str(fps)]
           + _enc_args() + ["-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                            str(output)])
    log("VIDEO", "Rendering {} ({:.1f}s, stock video{}) ...".format(
        output.name, audio_dur, ", captioned" if framed else ", no caption"))
    r = _sp.run(cmd, capture_output=True, text=True, timeout=900)
    if r.returncode != 0 or not output.exists():
        raise RuntimeError("Stock video render failed: {}".format(r.stderr[:500]))
    cache.put("chunks", key, ".mp4", output)
    dur = video_duration(output)
    log("VIDEO", "Rendered {} ({:.1f}s, stock video)".format(output.name, dur))
    return output, dur, False


def render_scene_chunk(image, audio, output, motion="zoom_in", cache=None, caption_text: str = ""):
    from app.audio.duration import get_audio_duration as _gad
    from app.video.caption_overlay import overlay_caption
    import shutil as _shutil
    import subprocess as _sp
    image, audio, output = Path(image), Path(audio), Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if not image.exists():
        raise FileNotFoundError("Scene image missing: {}".format(image))
    if not audio.exists():
        raise FileNotFoundError("Scene audio missing: {}".format(audio))
    # Caption overlay (renderer stage): clean image + video text -> captioned still.
    framed = image
    if config.CAPTION_ENABLED and str(caption_text or "").strip():
        framed = output.with_name(output.stem + "_framed.png")
        overlay_caption(image, caption_text, framed)
    settings = renderer_settings(motion, caption_text)
    key = chunk_cache_key(image, audio, settings)
    cache = cache or CacheManager(config.CACHE_DIR)
    cached = cache.get("chunks", key, ".mp4")
    audio_dur = _gad(audio)
    if output.exists() and output.stat().st_size > 0:
        try:
            if abs(video_duration(output) - audio_dur) < 0.6:
                log("VIDEO", "Reuse {} ({:.1f}s)".format(output.name, audio_dur))
                return output, audio_dur, True
        except Exception:
            pass
    if cached is not None:
        _shutil.copyfile(str(cached), str(output))
        log("VIDEO", "CACHE HIT -> {}".format(output.name))
        return output, audio_dur, True
    vf = _zoompan_filter(audio_dur, motion)
    cmd = ["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(framed),
           "-i", str(audio), "-vf", vf, "-t", "{:.2f}".format(audio_dur),
           "-r", str(config.VIDEO_FPS)] + _enc_args() + [
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
           "-shortest", str(output)]
    log("VIDEO", "Rendering {} ({:.1f}s, {}{}) ...".format(
        output.name, audio_dur, motion,
        ", captioned" if framed != image else ", no caption"))
    r = _sp.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0 or not output.exists():
        raise RuntimeError("Chunk render failed: {}".format(r.stderr[:500]))
    cache.put("chunks", key, ".mp4", output)
    dur = video_duration(output)
    log("VIDEO", "Rendered {} ({:.1f}s)".format(output.name, dur))
    return output, dur, False

