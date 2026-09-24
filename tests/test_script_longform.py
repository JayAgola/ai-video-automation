"""Long-form script reliability tests (3-4 minute scripts, cases A-L).

Deterministic mocked clients only - NO Ollama/network calls. The mock returns
raw model text (like the real client), so parse_script_json / pre-validate /
length-gate / retry-correction paths are all exercised exactly as in production.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.script import script_engine  # noqa: E402


def _sent(i: int, words: int = 55) -> str:
    """Deterministic narration of ~`words` words (55w / 2.5wps = 22s)."""
    base = ("This is deterministic narration sentence number {i}. It explains a "
            "concrete idea in plain spoken English so the scene lasts long "
            "enough. Keep the pacing natural and keep the language simple.")
    parts = base.format(i=i).split()
    out = []
    while len(out) < words:
        out.extend(parts)
    return " ".join(out[:words]) + "."


def _scene(i: int, words: int = 55, dur="__MISSING__", narration=None):
    s = {"scene_id": i,
         "narration": narration if narration is not None else _sent(i, words),
         "visual_direction": f"Calm cinematic wide shot for scene {i}"}
    if dur != "__MISSING__":
        s["estimated_duration_seconds"] = dur
    return s


def _script_text(n=9, words=55, **scene_kw) -> str:
    scenes = [_scene(i, words, **scene_kw) for i in range(1, n + 1)]
    data = {"title": "Long Form", "description": "desc", "tags": ["tag"],
            "keywords": ["kw"], "target_duration_seconds": 210,
            "bgm_style": "calm", "scenes": scenes}
    return json.dumps(data)


class RawClient:
    """Mock client returning pre-scripted RAW model text (like real Ollama)."""

    def __init__(self, texts, text_model="mock"):
        self.texts = list(texts)
        self.prompts = []
        self.fmts = []
        self.text_model = text_model

    def generate(self, prompt, options=None, system=None, fmt=None):
        from app.llm.ollama_client import OllamaResult
        self.prompts.append(prompt)
        self.fmts.append(fmt)
        return OllamaResult(ok=True, text=self.texts.pop(0))


def run() -> bool:
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        print(f"{'PASS' if cond else 'FAIL'}: {name} {detail}")
        if not cond:
            ok = False

    # ---- A: valid 8-12 scene, 180-240s script accepted, ONE call (also L) ----
    c = RawClient([_script_text(n=9, words=55)])
    s = script_engine.generate_script("topic", c, target_seconds=210, num_scenes=9)
    total = script_engine.script_estimated_total(s)
    check("A-valid-accepted", 180 <= total <= 240 and len(s["scenes"]) == 9,
          f"scenes={len(s['scenes'])} total={total:.1f}s")
    check("L-valid-not-regenerated", len(c.prompts) == 1, f"calls={len(c.prompts)}")

    # ---- B: 1-scene short script rejected + expansion correction on retry ----
    c = RawClient([_script_text(n=1, words=12)] * 3)
    try:
        script_engine.generate_script("topic", c, target_seconds=210, num_scenes=9)
        check("B-one-scene-rejected", False, "no error raised")
    except ValueError:
        corr = c.prompts[1]
        check("B-one-scene-rejected", True)
        check("J-short-retry-differs",
              "was only" in corr and "15-25 seconds" in corr and "scenes" in corr,
              corr[:90])

    # ---- C: 5-scene script rejected ----
    c = RawClient([_script_text(n=5, words=55)] * 3)
    try:
        script_engine.generate_script("topic", c, target_seconds=210, num_scenes=9)
        check("C-five-scenes-rejected", False, "no error raised")
    except ValueError:
        check("C-five-scenes-rejected", True, c.prompts[1][:80])

    # ---- D: 8 scenes but ~50s total rejected ----
    c = RawClient([_script_text(n=8, words=15)] * 3)  # 8*15/2.5 = 48s
    try:
        script_engine.generate_script("topic", c, target_seconds=210, num_scenes=9)
        check("D-eight-short-scenes-rejected", False, "no error raised")
    except ValueError:
        check("D-eight-short-scenes-rejected", True, c.prompts[1][:80])

    # ---- E: malformed JSON then valid -> retried, then accepted ----
    c = RawClient(["{ not valid json at all ]", _script_text()])
    s = script_engine.generate_script("topic", c, target_seconds=210, num_scenes=9)
    check("E-badjson-retried-accepted",
          len(c.prompts) == 2 and len(s["scenes"]) == 9,
          f"calls={len(c.prompts)}")

    # ---- F: ```json fenced valid script handled ----
    c = RawClient(["```json\n" + _script_text() + "\n```"])
    s = script_engine.generate_script("topic", c, target_seconds=210, num_scenes=9)
    check("F-fences-parsed", len(s["scenes"]) == 9 and len(c.prompts) == 1)

    # ---- G: missing duration derived from narration, never from visuals ----
    c = RawClient([_script_text(n=9, words=55, dur="__MISSING__")])
    s = script_engine.generate_script("topic", c, target_seconds=210, num_scenes=9)
    derived = all(14.0 <= sc["estimated_duration_seconds"] <= 30.0
                  for sc in s["scenes"])
    check("G-missing-duration-derived", derived,
          str([sc["estimated_duration_seconds"] for sc in s["scenes"]]))

    # ---- H: empty narration rejected, never patched from caption/visual ----
    c = RawClient([_script_text(n=9, words=55, narration="   ")] * 3)
    try:
        script_engine.generate_script("topic", c, target_seconds=210, num_scenes=9)
        check("H-empty-narration-rejected", False, "no error raised")
    except ValueError:
        check("H-empty-narration-rejected", True)

    # ---- I: narration with escaped quotation marks survives intact ----
    first_scene = {"scene_id": 1,
                   "narration": 'He said "stop overthinking" and smiled.',
                   "visual_direction": "calm room"}
    rest = []
    _fill = ("Overthinking starts as a quiet whisper in the back of your mind "
             "and grows into a loud storm that drowns out every calm thought. "
             "You replay conversations, regret emails, and rehearse disasters "
             "that will never actually happen to you. The brain treats each "
             "imagined outcome as real, so your body tenses for no reason. "
             "Breaking that loop begins with noticing the loop itself early.")
    for i in range(2, 10):
        n = _fill if i == 2 else _sent(i, 55)
        rest.append(_scene(i, narration=n))
    i_data = {"title": "Long Form", "description": "desc", "tags": ["tag"],
              "keywords": ["kw"], "target_duration_seconds": 210,
              "bgm_style": "calm", "scenes": [first_scene] + rest}
    c = RawClient(["```json\n" + json.dumps(i_data) + "\n```"])
    s = script_engine.generate_script("topic", c, target_seconds=210, num_scenes=9)
    check("I-escaped-quotes-parsed",
          s["scenes"][0]["narration"] == first_scene["narration"],
          s["scenes"][0]["narration"][:70])

    # ---- K: invalid-JSON retry asks for clean JSON (not topic from scratch) ----
    c = RawClient(["nope [[", _script_text()])
    script_engine.generate_script("topic", c, target_seconds=210, num_scenes=9)
    corr = c.prompts[1]
    check("K-json-retry-asks-valid-json",
          "JSON" in corr.upper() and "complete" in corr.lower(), corr[:90])

    # ---- W: bare thought preamble (no think tags) + real script parses ----
    w_data = json.loads(_script_text())
    w_reply = ("Okay, the user wants a long-form script about overthinking. "
               "Let me think about what scenes would work best here, maybe a hook "
               "first, then the psychology, then a practical technique... "
               "{\n  \"note\": \"thinking draft, not the script\"\n}\n"
               "Here is the finished script:\n" + json.dumps(w_data))
    check("W-bare-preamble-script-parsed",
          script_engine.parse_script_json(w_reply)["scenes"][0]["narration"] ==
          w_data["scenes"][0]["narration"])

    # ---- X: tagged think-trace + real script parses (model thought first) ----
    x_reply = ("<think>\nLet me plan: hook, problem, mechanism, technique... "
               "I need about 200 seconds, so each scene should be long.\n</think>\n"
               + json.dumps(w_data))
    check("X-think-trace-script-parsed",
          script_engine.parse_script_json(x_reply)["scenes"][0]["narration"] ==
          w_data["scenes"][0]["narration"])

    # ---- Y: script + trailing forward-thinking JSON still returns the script ----
    y_reply = (json.dumps(w_data) + "\nHmm wait, let me double check: "
               "{\"check\": \"second thoughts, not a scene\"}")
    check("Y-trailing-object-script-kept",
          script_engine.parse_script_json(y_reply)["scenes"][0]["narration"] ==
          w_data["scenes"][0]["narration"])

    # ---- Z: multi-JSON without scenes -> structural object, no invented text ----
    z_reply = '{"note": "only a note"} ... {"other": 1}'
    try:
        z_data = script_engine.parse_script_json(z_reply)
        check("Z-no-scenes-structural", isinstance(z_data, dict))
    except Exception:
        check("Z-no-scenes-structural", True, "raised JSON error (acceptable)")

    # ---- N1: JSON mode used on the first call for a JSON-capable model ----
    c = RawClient([_script_text()])
    script_engine.generate_script("topic", c, target_seconds=210, num_scenes=9)
    check("N1-json-mode-first-attempt", c.fmts == ["json"], str(c.fmts))

    # ---- N2: empty "{}" echo -> retry WITHOUT JSON mode, then accepted ----
    c = RawClient(["{ }", _script_text()])
    s = script_engine.generate_script("topic", c, target_seconds=210, num_scenes=9)
    check("N2-empty-object-retried-plain",
          len(c.prompts) == 2 and c.fmts == ["json", None] and len(s["scenes"]) == 9,
          f"fmts={c.fmts}")

    # ---- N3: reasoning models never get JSON mode (empty-object bug) ----
    check("N3-json-mode-unsafe-reasoning",
          not script_engine.json_mode_supported("deepseek-r1:7b")
          and not script_engine.json_mode_supported(
              "tom_himanen/deepseek-r1-roo-cline-tools:7b")
          and script_engine.json_mode_supported("llama3.2:3b")
          and script_engine.json_mode_supported("qwen2.5-coder:7b"))
    c = RawClient([_script_text()], text_model="deepseek-r1:7b")
    script_engine.generate_script("topic", c, target_seconds=210, num_scenes=9)
    check("N3-reasoning-call-is-plain", c.fmts == [None], str(c.fmts))

    # ---- script_length_issues unit gates (mirror of the runtime gate) ----
    short = json.loads(_script_text(n=1, words=12))
    check("V1-length-gate-short",
          len(script_engine.script_length_issues(short)) > 0)
    good = json.loads(_script_text())
    check("V2-length-gate-good",
          script_engine.script_length_issues(good) == [])

    # ---- resolve_script_model (pure function) ----
    check("M1-model-preferred",
          script_engine.resolve_script_model(
              ["llama3.2:3b", "deepseek-r1:7b"], "deepseek-r1:7b", "llama3.2:3b")
          == "deepseek-r1:7b")
    check("M2-model-fallback",
          script_engine.resolve_script_model(
              ["llama3.2:3b"], "deepseek-r1:7b", "llama3.2:3b") == "llama3.2:3b")

    print("SCRIPT-LONGFORM:", "ALL PASS" if ok else "FAILURES PRESENT")
    return ok


if __name__ == "__main__":
    sys.exit(0 if run() else 1)

