"""Test 1+2+3: provider health, placeholder image, image cache HIT."""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from test_part2_common import _script2
from app.core import config
from app.core.cache_manager import CacheManager
from app.core.project_manager import ProjectManager
from app.visuals import visual_engine
from app.visuals.test_provider import TestImageProvider

config.ensure_dirs()
h = visual_engine.provider_health("test")
assert h["ok"], h
print("provider health: PASS", h)
assert visual_engine.provider_health("nope")["ok"] is False
print("unknown provider error: PASS")

PID = "test_p2_visual"
pm = ProjectManager()
pm.create_project(PID)
pm.state_manager(PID).create_project(PID)
script = _script2()
cache = CacheManager(config.CACHE_DIR)
prov = TestImageProvider()
vdir = pm.visuals_dir(PID)
p1, m1, hit1 = visual_engine.generate_scene_image(PID, script["scenes"][0], script, vdir, cache, prov)
assert p1.exists()
from PIL import Image
im = Image.open(str(p1))
assert im.size == (config.IMAGE_WIDTH, config.IMAGE_HEIGHT), im.size
print("placeholder image: PASS {} {}".format(p1, im.size))
p2, m2, hit2 = visual_engine.generate_scene_image(PID, script["scenes"][0], script, vdir, cache, prov)
assert hit2 is True and p1 == p2
print("image cache HIT: PASS")
print("P2-VISUAL: ALL PASS")
