"""Final video concat (ffmpeg, scene_id order) + mux mixed voice+BGM audio.

Idempotent unless force=True.
"""
from __future__ import annotations
import subprocess
from pathlib import Path
from app.core.logger import log


def concat_chunks(chunks, output, audio_track=None, force=False):
    from app.video.chunk_renderer import _enc_args, video_duration
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if not force and output.exists() and output.stat().st_size > 0:
        log("VIDEO", "Reuse final -> {}".format(output.name))
        return output, video_duration(output)
    lst = output.with_suffix(".txt")
    lst.write_text("".join("file '{}'\n".format(Path(c).resolve()) for c in chunks),
                   encoding="utf-8")
    try:
        # Chunks carry per-scene voice audio. Re-encoding the concat while
        # muxing a second audio input truncates output (concat-demuxer audio
        # timestamps end early, -shortest then cuts the video). Fast safe path:
        #   1. concat demuxer + stream copy (no re-encode, seconds) -> temp file
        #   2. drop temp audio, mux full mixed voice+BGM (or voiceover fallback)
        #      with video stream-copy.
        if audio_track is not None:
            audio_track = Path(audio_track)
            if not audio_track.exists():
                raise FileNotFoundError("Mixed audio missing: {}".format(audio_track))
            tmp = output.with_name(output.stem + "_concat_tmp.mp4")
            cmd_v = ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                     "-i", str(lst), "-c", "copy", str(tmp)]
            r = subprocess.run(cmd_v, capture_output=True, text=True, timeout=600)
            if r.returncode != 0 or not tmp.exists():
                raise RuntimeError(r.stderr[:500])
            try:
                vdur = video_duration(tmp)
                cmd_a = (["ffmpeg", "-y", "-v", "error", "-i", str(tmp),
                          "-i", str(audio_track.resolve()), "-map", "0:v:0",
                          "-map", "1:a:0", "-c:v", "copy",
                          "-c:a", "aac", "-b:a", "192k",
                          "-t", "{:.2f}".format(vdur), str(output)])
                r = subprocess.run(cmd_a, capture_output=True, text=True, timeout=600)
                if r.returncode != 0 or not output.exists():
                    raise RuntimeError(r.stderr[:500])
            finally:
                try:
                    tmp.unlink()
                except OSError:
                    pass
        else:
            cmd = (["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                    "-i", str(lst)] + _enc_args() + ["-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "128k", str(output)])
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if r.returncode != 0 or not output.exists():
                raise RuntimeError(r.stderr[:500])
    finally:
        try:
            lst.unlink()
        except OSError:
            pass
    dur = video_duration(output)
    log("VIDEO", "Final video -> {} ({:.1f}s){}".format(
        output.name, dur, " [voice+BGM]" if audio_track else ""))
    return output, dur

