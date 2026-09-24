"""Focused tests Part 2.1: robust script/schema validation (llama3.2:3b failures).

Exact failure replicas:
  A) scene missing estimated_duration_seconds -> derived, validation passes.
  B) scene with narration "" -> rejected, never reaches pipeline.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core import config
from app.script import script_engine
from app.visuals import visual_engine


def _base(title="T"):
    return {"title": title, "description": "d", "tags": ["t"], "keywords": [],
            "target_duration_seconds": 30, "bgm_style": "calm", "scenes": []}


def _scene(narration, visual, dur="__MISSING__", sid=1):
    s = {"scene_id": sid, "narration": narration, "visual_direction": visual}
    if dur != "__MISSING__":
        s["estimated_duration_seconds"] = dur
    return s


class FakeClient:
    text_model = "mock"

    def __init__(self, texts):
        self.texts = list(texts)
        self.prompts = []

    def generate(self, prompt, options=None):
        import json as _j
        from app.llm.ollama_client import OllamaResult
        self.prompts.append(prompt)
        return OllamaResult(ok=True, text=_j.dumps(self.texts.pop(0)))


def run() -> bool:
    import json as _json
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        print(f"{'PASS' if cond else 'FAIL'}: {name} {detail}")
        if not cond:
            ok = False

    # T1: missing duration -> derived (9 words / 2.5wps = 3.6 -> clamp 5.0).
    d1 = _base()
    d1["scenes"] = [_scene("When your thoughts start racing, pause and take a breath.",
                           "A person sitting quietly in a peaceful mountain landscape.")]
    n1, f1 = script_engine.pre_validate_script(d1)
    check("T1-missing-no-fatal", f1 == [], str(f1))
    dur1 = n1["scenes"][0]["estimated_duration_seconds"]
    check("T1-derived-clamped", dur1 == config.SCENE_MIN_SECONDS, f"dur={dur1}")
    try:
        script_engine.validate_script(n1)
        check("T1-passes", True)
    except Exception as e:
        check("T1-passes", False, str(e)[:150])

    # T2: valid duration preserved.
    d2 = _base()
    d2["scenes"] = [_scene("When your thoughts start racing, pause and take a breath.",
                           "A mountain lake at sunrise.", 8)]
    n2, f2 = script_engine.pre_validate_script(d2)
    check("T2-preserved", n2["scenes"][0]["estimated_duration_seconds"] == 8 and f2 == [])

    # T3: extreme 50 -> clamped to max.
    d3 = _base()
    d3["scenes"] = [_scene("When your thoughts start racing, pause and take a breath.",
                           "A mountain lake at sunrise.", 50)]
    n3, _ = script_engine.pre_validate_script(d3)
    check("T3-clamped", n3["scenes"][0]["estimated_duration_seconds"] == config.SCENE_MAX_SECONDS,
          f"dur={n3['scenes'][0]['estimated_duration_seconds']}")

    # T4/T5: empty + whitespace rejected, never patched.
    for name, narr in (("T4-empty", ""), ("T5-whitespace", "   ")):
        d = _base()
        d["scenes"] = [_scene(narr, "A peaceful mountain landscape.")]
        _, fatals = script_engine.pre_validate_script(d)
        check(f"{name}-fatal", any("empty narration" in f for f in fatals), str(fatals))
        try:
            script_engine.validate_script(d)
            check(f"{name}-pydantic-rejects", False, "accepted empty!")
        except Exception:
            check(f"{name}-pydantic-rejects", True)

    # T6: Text:'...' sanitized by Part-2 path (unchanged).
    p6 = visual_engine.build_prompt(_scene("Take a breath now please.", "Text: 'Take a breath'", 7), None)
    check("T6-sanitized", "Text:" not in p6 and "Take a breath" not in p6, p6[:140])

    # T7/T8: narration/caption never in visual prompt; caption separate.
    sc78 = _scene("When your thoughts start racing, pause and take a breath.",
                  "A peaceful person beside a quiet mountain lake at sunrise.", 7)
    p78 = visual_engine.build_prompt(sc78, None)
    cap78 = visual_engine.scene_caption(sc78)
    check("T7-not-in-visual", sc78["narration"] not in p78)
    check("T8-caption-separate", cap78 == sc78["narration"] and cap78 not in p78)

    # T9: legacy loads; T10: valid unchanged.
    legacy = _base("legacy")
    legacy["scenes"] = [{"scene_id": 1, "narration": "Hello world test narration here.",
                         "visual_direction": "Calm lake."}]
    nl, fl = script_engine.pre_validate_script(legacy)
    check("T9-legacy", fl == [] and nl["scenes"][0]["caption_text"] != ""
          and nl["scenes"][0]["visual_prompt"] == "Calm lake.")
    valid = _base("valid")
    valid["scenes"] = [_scene("A calm spoken sentence for testing purposes here.", "Calm lake.", 12)]
    nv, fv = script_engine.pre_validate_script(valid)
    check("T10-unchanged", fv == [] and nv["scenes"][0]["estimated_duration_seconds"] == 12)

    # Correction messages: compact, specific, no Pydantic dump.
    c1 = script_engine.correction_message(
        {"scenes": [{"scene_id": 1, "narration": "x y", "visual_direction": "lake"}]})
    check("T11-corr-duration", "estimated_duration_seconds" in c1, c1[:160])
    c2 = script_engine.correction_message(
        {"scenes": [{"scene_id": 1, "narration": "", "visual_direction": "lake",
                     "estimated_duration_seconds": 7}]})
    check("T12-corr-narration", "empty narration" in c2.lower(), c2[:160])
    check("T13-no-dump", "string_too_short" not in c1 + c2 and "Field required" not in c1 + c2)

    # Mocked LLM end-to-end for the exact failure case (no network).
    good = {"scene_id": 1, "narration": "When your thoughts start racing, pause and take a breath.",
            "visual_direction": "A person sitting quietly in a peaceful mountain landscape."}
    fake = FakeClient([dict(_base("Mocked"), scenes=[good])])
    out = script_engine.generate_script("breath", fake, target_seconds=30, num_scenes=1)
    check("T14-mocked-missing-passes",
          out["scenes"][0]["estimated_duration_seconds"] >= config.SCENE_MIN_SECONDS,
          f"dur={out['scenes'][0]['estimated_duration_seconds']}")

    bad_then_good = [
        dict(_base("Bad"), scenes=[{"scene_id": 1, "narration": "",
                                    "visual_direction": "A peaceful mountain landscape."}]),
        dict(_base("Good"), scenes=[dict(good, estimated_duration_seconds=7)]),
    ]
    fake2 = FakeClient(bad_then_good)
    out2 = script_engine.generate_script("breath", fake2, target_seconds=30, num_scenes=1)
    check("T15-empty-retried",
          out2["scenes"][0]["narration"] != ""
          and "empty narration" in fake2.prompts[1].lower(),
          "retry carries correction")

    # T16/T17: --resume must be able to retry a SCRIPT that FAILED (the exact
    # video_003 dead-end: SCRIPT in failed_steps used to block resume forever).
    from pipeline_main import script_is_resumable
    check("T16-resume-failed-script-allowed",
          script_is_resumable({"completed_steps": ["RESEARCH", "SEO_GENERATION"],
                               "failed_steps": ["SCRIPT"]}) is True)
    check("T17-resume-untouched-script-refused",
          script_is_resumable({"completed_steps": [], "failed_steps": []}) is False)

    # T18-T20: JSON salvage for real llama3.2:3b defects (captured locally:
    # output ended with '"estimated_duration_seconds": 15}' -> ']' and '}' missing).
    parse_script_json = script_engine.parse_script_json
    good_json = _json.dumps(_base("T") | {
        "scenes": [{"scene_id": 1, "narration": "One calm sentence here.",
                    "visual_direction": "Calm lake.", "estimated_duration_seconds": 7},
                   {"scene_id": 2, "narration": "Another calm sentence.",
                    "visual_direction": "Warm sunrise.", "estimated_duration_seconds": 8}]})
    check("T18-valid-unchanged",
          parse_script_json(good_json)["scenes"][1]["scene_id"] == 2)
    check("T19-missing-closers-recovered",
          parse_script_json(good_json[:-2])["scenes"][1]["scene_id"] == 2,
          "recovered without trailing ']}'")
    cut = good_json[:good_json.rfind('"scene_id": 2')] + '"scene_id": 2, "narration": "cut off mid'
    check("T20-truncated-scene-dropped",
          [s["scene_id"] for s in parse_script_json(cut)["scenes"]] == [1],
          str([s["scene_id"] for s in parse_script_json(cut)["scenes"]]))
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
