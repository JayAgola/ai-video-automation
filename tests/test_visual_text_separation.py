"""Focused tests: AI visuals contain NO narration/caption text; captions render in video stage.

Uses existing test provider (no expensive AI generation).
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core import config
from app.core.cache_manager import CacheManager
from app.script import script_engine
from app.visuals import image_cache as icache
from app.visuals import visual_engine
from app.visuals.test_provider import TestImageProvider
from app.video import caption_overlay, chunk_renderer


def _scene():
    return {
        "scene_id": 1,
        "narration": "When you notice yourself overthinking, take a breath.",
        "visual_direction": "Text: 'Overthinking fix' peaceful person on mountain overlook at sunrise",
        "estimated_duration_seconds": 10,
    }


def run() -> bool:
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        print(f"{'PASS' if cond else 'FAIL'}: {name} {detail}")
        if not cond:
            ok = False

    sc = _scene()
    norm = script_engine.normalize_scene(sc)
    check("scene-normalize-keeps-narration", norm["narration_text"].startswith("When you notice"))
    check("scene-normalize-derives-caption", norm["caption_text"] == norm["narration_text"])
    check("scene-normalize-keeps-visual", "mountain" in norm["visual_prompt"])

    prompt = visual_engine.build_prompt(sc, {"visual_style": "stylized 2D illustration"})
    check("visual-prompt-excludes-narration", sc["narration"] not in prompt, prompt[:120])
    check("visual-prompt-excludes-caption", norm["caption_text"] not in prompt)
    check("visual-prompt-strips-text-instruction", "Text:" not in prompt, prompt[:160])
    check("visual-prompt-keeps-scene", "mountain" in prompt.lower())

    neg = visual_engine.negative_prompt()
    for token in ["no text", "no typography", "no captions", "no subtitles", "no letters"]:
        check(f"negative-has-{token.replace(' ', '-')}", token in neg.lower())
    check("comfyui-uses-global-negative",
          "VISUAL_NEGATIVE_PROMPT" in Path(ROOT, "app/visuals/comfyui_provider.py").read_text())

    # Cache versioning: v1-style key (no version) must differ from current key.
    from app.core.cache_manager import CacheManager as CM
    legacy = CM.hash_key(prompt, {"provider": "test", "model": "m", "width": 1, "height": 1, "seed": 1})
    current = icache.image_settings_key(prompt, "test", "m", 1, 1, 1)
    check("cache-version-invalidates-legacy", legacy != current)
    check("cache-version-flag", config.VISUAL_CACHE_VERSION == "v2_no_text", config.VISUAL_CACHE_VERSION)

    # Test provider: clean visual, no narration text rendered.
    config.ensure_dirs()
    prov = TestImageProvider()
    out = Path("projects/test_notext/visuals/clean.png")
    meta = prov.generate_image(prompt, out, 640, 360, {"seed": 7, "scene_id": 1})
    check("test-provider-clean-image", Path(meta["path"]).exists())
    try:
        import pytesseract  # optional OCR check
        from PIL import Image
        text = pytesseract.image_to_string(Image.open(str(out)))
        check("test-image-has-no-narration-ocr", sc["narration"][:10].lower() not in text.lower(), repr(text[:80]))
    except Exception as e:
        print(f"SKIP ocr-check (tesseract missing: {e})")

    # Caption overlay: renderer-side, wrapped, bounded, unicode-safe.
    cap = "When you notice yourself overthinking, take a breath. \u6df7\u5408 test \u00e9\u00e8"
    framed = caption_overlay.overlay_caption(out, cap, Path("projects/test_notext/visuals/framed.png"))
    check("caption-overlay-creates-frame", framed.exists())
    from PIL import Image
    check("caption-overlay-same-size", Image.open(str(framed)).size == Image.open(str(out)).size)
    check("caption-wrap", len(caption_overlay.wrap_caption(cap)) >= 1)
    # Captioned chunk settings differ from uncaptioned (cache-safe).
    s_plain = chunk_renderer.renderer_settings("zoom_in", "")
    s_cap = chunk_renderer.renderer_settings("zoom_in", cap)
    check("caption-in-chunk-settings", s_plain["caption_hash"] != s_cap["caption_hash"])

    # Production example from the spec.
    prod = {"scene_id": 9,
            "narration": "When you notice yourself overthinking, take a breath.",
            "visual_direction": ("A peaceful person sitting alone on a mountain overlook "
                                 "at sunrise, thoughtful expression, calm atmosphere, "
                                 "warm cinematic lighting, stylized 2D illustration."),
            "estimated_duration_seconds": 10}
    pp = visual_engine.build_prompt(prod, None)
    check("prod-visual-clean", "When you notice yourself overthinking" not in pp
          and "mountain" in pp.lower() and "sunrise" in pp.lower(), pp[:200])
    check("prod-caption-separate", visual_engine.scene_caption(prod) == prod["narration"])
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
