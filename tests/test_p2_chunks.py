"""Test 4+5+6: chunk render, chunk cache, multi-scene concat."""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from test_part2_common import _script2, _seed_audio
from app.audio.duration import get_audio_duration
from app.core import config
from app.core.cache_manager import CacheManager
from app.core.project_manager import ProjectManager
from app.video import chunk_renderer, final_concat
from app.visuals import visual_engine
from app.visuals.test_provider import TestImageProvider

config.ensure_dirs()
PID = "test_p2_chunks"
pm = ProjectManager()
pm.create_project(PID)
pm.state_manager(PID).create_project(PID)
script = _script2()
_seed_audio(PID, script)
cache = CacheManager(config.CACHE_DIR)
prov = TestImageProvider()
vdir = pm.visuals_dir(PID)
imgs = [visual_engine.generate_scene_image(PID, sc, script, vdir, cache, prov)[0]
        for sc in script["scenes"]]
c1, d1, r1 = chunk_renderer.render_scene_chunk(
    imgs[0], pm.audio_dir(PID) / "scene_001.mp3", pm.chunks_dir(PID) / "scene_001.mp4")
assert c1.exists()
ad = get_audio_duration(pm.audio_dir(PID) / "scene_001.mp3")
assert abs(d1 - ad) < 0.8, (d1, ad)
chunk_renderer.video_duration(str(c1))
print("chunk render: PASS {} ({:.1f}s, audio {:.1f}s)".format(c1, d1, ad))
_, _, r2 = chunk_renderer.render_scene_chunk(
    imgs[0], pm.audio_dir(PID) / "scene_001.mp3", pm.chunks_dir(PID) / "scene_001.mp4")
assert r2 is True
print("chunk cache reuse: PASS")
c2, _, _ = chunk_renderer.render_scene_chunk(
    imgs[1], pm.audio_dir(PID) / "scene_002.mp3", pm.chunks_dir(PID) / "scene_002.mp4")
out, fd = final_concat.concat_chunks([c1, c2], pm.final_video_path(PID))
assert out.exists() and fd > 0
print("concat: PASS {} ({:.1f}s)".format(out, fd))
print("P2-CHUNKS: ALL PASS")
