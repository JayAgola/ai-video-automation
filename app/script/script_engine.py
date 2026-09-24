"""Script engine: topic -> validated structured JSON script via Ollama."""
from __future__ import annotations

import inspect
import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.core.logger import log


class Scene(BaseModel):
    scene_id: int
    narration: str = Field(min_length=1)
    visual_direction: str = Field(min_length=1)
    estimated_duration_seconds: float = Field(gt=0)
    # Optional text-separation fields (backward compatible): derived when absent.
    narration_text: str = ""
    visual_prompt: str = ""
    caption_text: str = ""
    # Optional Part 2.2 hybrid-source planning fields (defaults keep legacy
    # scripts valid; invalid values fall back to safe defaults).
    visual_type: str = "unknown"
    visual_source_preference: str = "auto"
    stock_search_query: str = ""


def normalize_scene(scene: dict) -> dict:
    """Backward-compatible view: narration_text / visual_prompt / caption_text.

    Old scripts only have narration + visual_direction. New code must use this
    so caption text never has to be parsed back out of visual fields.
    Duration fallback (Part 2.1): missing/invalid estimated_duration_seconds is
    derived deterministically from narration word count and clamped to
    SCENE_MIN/MAX_SECONDS. Empty narration is NEVER patched — it stays empty
    so validation/retry rejects it.
    """
    from app.core import config as _cfg
    s = dict(scene)
    narration = str(s.get("narration_text") or s.get("narration") or "").strip()
    visual = str(s.get("visual_prompt") or s.get("visual_direction") or "").strip()
    caption = str(s.get("caption_text") or narration).strip()
    s["narration_text"] = narration
    if not s.get("narration"):
        s["narration"] = narration
    s["visual_prompt"] = visual
    if not s.get("visual_direction"):
        s["visual_direction"] = visual
    s["caption_text"] = caption
    # Part 2.2 planning fields: validate/normalize, never fatal (defaults keep
    # legacy scripts valid). Kept in sync with app.visuals.visual_engine sets.
    pref = str(s.get("visual_source_preference") or "auto").strip().lower()
    s["visual_source_preference"] = pref if pref in {
        "auto", "stock", "ai", "local"} else "auto"
    vt = str(s.get("visual_type") or "unknown").strip().lower()
    s["visual_type"] = vt if vt in {
        "person", "animal", "landscape", "object", "place", "room", "abstract",
        "cartoon", "fictional", "unknown"} else "unknown"
    s["stock_search_query"] = " ".join(str(s.get("stock_search_query") or "").split())
    dur = s.get("estimated_duration_seconds")
    try:
        dur_f = float(dur) if dur is not None else float("nan")
    except (TypeError, ValueError):
        dur_f = float("nan")
    if not (dur_f == dur_f and dur_f > 0):  # missing / NaN / <= 0 / garbage
        if narration:
            words = len(narration.split())
            wps = float(getattr(_cfg, "SCRIPT_WPS", 2.5)) or 2.5
            dur_f = words / wps
        else:
            dur_f = float(getattr(_cfg, "SCENE_MIN_SECONDS", 5))
    lo = float(getattr(_cfg, "SCENE_MIN_SECONDS", 5))
    hi = float(getattr(_cfg, "SCENE_MAX_SECONDS", 30))
    s["estimated_duration_seconds"] = max(lo, min(hi, round(float(dur_f), 2)))
    return s


def scene_validation_issues(scene: dict) -> list[str]:
    """Compact per-scene issues for LLM correction (no Pydantic dumps)."""
    s = scene if isinstance(scene, dict) else {}
    issues: list[str] = []
    if not str(s.get("narration_text") or s.get("narration") or "").strip():
        issues.append("empty narration")
    dur = s.get("estimated_duration_seconds")
    try:
        ok = dur is not None and float(dur) > 0
    except (TypeError, ValueError):
        ok = False
    if not ok:
        issues.append("missing estimated_duration_seconds")
    if not str(s.get("visual_prompt") or s.get("visual_direction") or "").strip():
        issues.append("missing visual_direction")
    return issues


class Script(BaseModel):
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    tags: list[str] = Field(min_length=1)
    keywords: list[str] = Field(default_factory=list)
    target_duration_seconds: int = Field(gt=0)
    bgm_style: str = Field(min_length=1)
    scenes: list[Scene] = Field(min_length=1, max_length=16)


SYSTEM_PROMPT = (
    "You are a professional YouTube scriptwriter. You reply with ONE valid JSON "
    "object and nothing else: no markdown, no ``` fences, no comments, and no text "
    "before or after the JSON. You NEVER summarise a topic: every scene you write is "
    "fully developed spoken narration of the requested length."
)

ORIGINALITY_RULES = (
    "ORIGINALITY (mandatory): Do not copy another video's script. Do not reproduce "
    "another creator's wording. Do not imitate a specific creator. Use trends/topics "
    "only as inspiration. Produce original explanations and storytelling in your own words."
)


# Narrative beats a long-form (3-4 minute) script must cover. Wording adapts per
# topic, but every beat gets its own fully developed scene.
_LONGFORM_BEATS = (
    "1. Hook - a specific moment from the viewer's own life.\n"
    "2. Problem - what it costs them, in concrete everyday detail.\n"
    "3. Why it happens - the mechanism/psychology behind it.\n"
    "4. Core concept - the one idea that changes how they see it.\n"
    "5. Practical technique - exactly what to do, step by step.\n"
    "6. Worked example - the technique applied to a realistic situation.\n"
    "7. Common mistake - what people get wrong and how to avoid it.\n"
    "8. Action plan - how to apply this in the next seven days.\n"
    "9. Final takeaway - the closing thought that sticks."
)

# JSON-only contract. Kept as a plain (non-f) string because it contains literal
# braces from the schema text.
_JSON_CONTRACT = (
    "# OUTPUT FORMAT (MANDATORY)\n"
    "- Output ONLY ONE valid JSON object. No markdown, no ```json fences, no text "
    "before or after the object, no comments, no explanations.\n"
    "- Every key and every string value uses double quotes; commas between all "
    "pairs; NO trailing commas; close every { } and [ ].\n"
    "- NEVER use unescaped double quotes inside a string value. Avoid quotation "
    "marks in narration; if you must quote, escape them like \\\".\n"
    "- Required top-level keys (ALL of them): title, description, tags, keywords, "
    "target_duration_seconds, bgm_style, scenes.\n"
    "- scenes is an array of scene objects. Every scene object has EXACTLY these "
    "keys: scene_id (int), narration (string), visual_direction (string), "
    "estimated_duration_seconds (number), visual_type (string), "
    "visual_source_preference (string), stock_search_query (string).\n"
)

_VISUAL_RULES = (
    "- visual_direction is a PURE VISUAL SCENE DESCRIPTION (it is used for a stock "
    "search or image generation, never as narration). Describe ONLY what the camera "
    "sees: subject, environment, lighting, mood, style. NEVER include narration "
    "sentences, captions, quotes, on-screen text, typography, letters, words, signs, "
    "logos or 'Text: ...'.\n"
    "- visual_type: one of person, animal, landscape, object, place, room, abstract, "
    "cartoon, fictional, unknown.\n"
    "- visual_source_preference: auto (let the system choose), stock (real "
    "photography of real-world subjects), ai (surreal/fictional/impossible "
    "concepts), local (user-supplied asset).\n"
    "- stock_search_query: 2-5 simple lowercase keywords describing the visual "
    "subject (e.g. 'person peaceful reflection'). NEVER the narration sentence, "
    "NEVER quotes.\n"
)

# The GOOD example deliberately demonstrates a ~45-word narration, so the model
# imitates the LENGTH as well as the shape.
_SCENE_EXAMPLE = (
    'GOOD scene example (narration is ~45 words - imitate this length): '
    '{"scene_id": 1, "narration": "It is eleven at night and you are still replaying '
    'a conversation from this morning, rewriting sentences you cannot change and '
    'imagining outcomes that will never happen. Your body is in bed but your mind is '
    'still in that room, arguing with someone who has already forgotten the moment.", '
    '"visual_direction": "A man lying awake in a dark bedroom at night, blue moonlight '
    'through the window, restless expression, calm cinematic mood", '
    '"estimated_duration_seconds": 20, "visual_type": "person", '
    '"visual_source_preference": "stock", "stock_search_query": "man lying awake '
    'bedroom night"}\n'
    'BAD scene: {"scene_id": 1, "narration": "", "visual_direction": "Person thinking '
    'with text saying TAKE A BREATH"}\n'
    'BAD scene: a one-line narration such as "Overthinking is bad for you." - that is '
    'far too short and will be rejected.\n'
    "- NEVER return empty narration. NEVER omit estimated_duration_seconds. NEVER add "
    "fields that are not listed above. NEVER wrap the JSON in markdown.\n"
)

_SCHEMA_LINE = (
    '{"title": str, "description": str, "tags": [str], "keywords": [str], '
    '"target_duration_seconds": int, "bgm_style": str, '
    '"scenes": [{"scene_id": int, "narration": str, "visual_direction": str, '
    '"estimated_duration_seconds": number, "visual_type": str, '
    '"visual_source_preference": str, "stock_search_query": str}]}'
)


def _word_budget(target_seconds: int, num_scenes: int) -> dict:
    """Translate seconds into a word budget the model can actually follow.

    Small models cannot convert "15-25 seconds" into words, so every narration
    target is stated in words as well (words = seconds * SCRIPT_WPS). Pure function.
    """
    from app.core import config
    wps = float(getattr(config, "SCRIPT_WPS", 2.5)) or 2.5
    per_lo = float(getattr(config, "SCRIPT_NARRATION_MIN_SECONDS", 15))
    per_hi = float(getattr(config, "SCRIPT_NARRATION_MAX_SECONDS", 25))
    return {
        "wps": wps,
        "per_scene_lo": max(5, int(round(per_lo * wps))),
        "per_scene_hi": max(6, int(round(per_hi * wps))),
        "total_lo": max(10, int(round(
            float(getattr(config, "SCRIPT_TARGET_MIN_SECONDS", 180)) * wps))),
        "total_hi": max(11, int(round(
            float(getattr(config, "SCRIPT_TARGET_MAX_SECONDS", 240)) * wps))),
        "target_words": max(10, int(round(float(target_seconds) * wps))),
        "min_scenes": max(1, int(getattr(config, "SCRIPT_MIN_SCENES", 8))),
        "max_scenes": max(1, int(getattr(config, "SCRIPT_MAX_SCENES", 16))),
    }



def build_prompt(topic: str, target_seconds: int = 210, num_scenes: int = 9,
                 correction: str = "") -> str:
    """Long-form script prompt (reliable 8+ scene, 180-240s narration).

    Long-form mode (num_scenes >= SCRIPT_MIN_SCENES = the production path) states the
    narration budget in WORDS *and* seconds and demands 8+ scenes with 3-5 sentences
    each. The old wording ("narration = one complete sentence, 15-30 seconds")
    contradicted itself - one sentence is ~5-10 seconds of speech, so 9 scenes could
    never exceed ~90 seconds. Short-form callers (explicitly small num_scenes) keep
    their smaller contract unchanged.
    """
    b = _word_budget(target_seconds, num_scenes)
    n = max(1, int(num_scenes))
    long_form = n >= b["min_scenes"]
    min_scenes = max(1, min(b["min_scenes"], n))
    pref_scenes = max(min_scenes, n)
    max_scenes = max(pref_scenes, min(b["max_scenes"], 12))
    if long_form:
        task = (
            f"# TASK\nWrite an ORIGINAL {max(1, int(round(target_seconds / 60)))}-minute "
            f"YouTube NARRATION script about: {topic}\n"
            "# LENGTH (MANDATORY - THE MOST IMPORTANT REQUIREMENT)\n"
            f"- Write {min_scenes} to {max_scenes} scenes ({pref_scenes} is ideal). "
            f"NEVER write fewer than {min_scenes} scenes.\n"
            f"- EACH scene narration MUST be {b['per_scene_lo']}-{b['per_scene_hi']} "
            f"words: 15-25 seconds of natural spoken English (about {b['wps']:g} spoken "
            "words per second). Write 3-5 complete sentences in every scene.\n"
            f"- The COMPLETE narration MUST be {b['total_lo']}-{b['total_hi']} words = "
            f"180-240 seconds of speech. Aim for about {b['target_words']} words "
            f"(~{int(target_seconds)} seconds), i.e. the MIDDLE of the range: a script "
            f"of exactly {b['total_lo']} words is a fail as soon as a few words are "
            "missing, so err on the long side (never below "
            f"{b['target_words']} words, up to {b['total_hi']}).\n"
            "- NEVER write a one-sentence scene. NEVER summarise the topic. Every scene "
            "must be fully developed with explanation, concrete detail or an example.\n"
            "- estimated_duration_seconds is that scene's REAL spoken length: a number "
            "between 15 and 25.\n"
            "# STRUCTURE (one scene per beat, in this order; adapt the wording to the "
            "topic)\n" + _LONGFORM_BEATS + "\n"
        )
    else:
        per = max(8, b["target_words"] // n)
        forbid = (f" A reply with fewer than {n} scenes is rejected." if n > 1 else "")
        if n >= 3:
            jobs = (
                f"- Give EACH scene its own distinct job, as separate entries in the "
                f"scenes array: scene 1 = hook that poses the question to the viewer; "
                f"scenes 2-{n - 1} = one DIFFERENT explanation step each (never "
                f"repeat a point); scene {n} = closing takeaway.\n"
            )
        elif n == 2:
            jobs = ("- Give EACH scene its own distinct job: scene 1 = hook that poses "
                    "the question; scene 2 = explanation plus closing takeaway.\n")
        else:
            jobs = ""
        task = (
            f"# TASK\nWrite an ORIGINAL YouTube narration script about: {topic}\n"
            f"- Return EXACTLY {n} scene(s) in the scenes array (scene_id 1 through "
            f"{n}).{forbid}\n"
            f"- Target total duration ~{int(target_seconds)} seconds across those "
            f"{n} scenes.\n"
            + jobs +
            f"- Each scene narration is about {int(per * 0.8)}-{int(per * 1.2)} words "
            "of natural spoken English.\n"
            "- Every scene must be fully developed, never a one-line summary.\n"
        )
    base = (
        ORIGINALITY_RULES + "\n\n" + task + "\n" + _JSON_CONTRACT
        + "\n" + _VISUAL_RULES + "\n" + _SCENE_EXAMPLE
        + "\nReturn JSON with EXACTLY this schema:\n" + _SCHEMA_LINE + "\n"
    )
    if correction:
        base += ("\n# CORRECTION REQUIRED\n" + correction
                 + "\nApply this correction and return the COMPLETE corrected JSON "
                   "object (all scenes, full length).\n")
    if long_form:
        base += (
            "\n# FINAL CHECK BEFORE YOU ANSWER\n"
            f"scenes: {min_scenes}-{max_scenes} | every narration: "
            f"{b['per_scene_lo']}-{b['per_scene_hi']} words | total narration: "
            f"{b['target_words']}-{b['total_hi']} words (aim ~{int(target_seconds)} "
            "seconds; never below 180 seconds of speech).\n"
            "Output ONLY the JSON object.\n"
        )
    else:
        base += (
            "\n# FINAL CHECK BEFORE YOU ANSWER\n"
            f"scenes: EXACTLY {n} (scene_id 1..{n}) | each narration: "
            f"{int(per * 0.8)}-{int(per * 1.2)} words | total ~{b['target_words']} "
            "words.\n"
            "Output ONLY the JSON object.\n"
        )
    return base



def extract_json(text: str) -> str:
    """Safe extraction/repair: strip fences, then widest {...} or [...] block."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    # Prefer JSON array (topic candidates) when it spans the payload.
    a_start, a_end = t.find("["), t.rfind("]")
    b_start, b_end = t.find("{"), t.rfind("}")
    if a_start != -1 and a_end != -1 and a_end > a_start:
        if b_start == -1 or a_start <= b_start:
            return t[a_start:a_end + 1]
    if b_start != -1 and b_end != -1 and b_end > b_start:
        return t[b_start:b_end + 1]
    return t


def _close_containers(text: str) -> str:
    """Append only the structural delimiters a small model forgot to emit.

    llama3.2:3b reliably stops right after the last scene object, omitting the
    closing `]` and `}` ("Expecting ',' delimiter" at the very end of the text).
    This closes an unterminated string and then the open `{`/`[` in reverse
    order. It never invents scene content.
    """
    in_str = False
    esc = False
    stack: list[str] = []
    for ch in text:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]" and stack:
            stack.pop()
    out = text + ('"' if in_str else "")
    for ch in reversed(stack):
        out += "}" if ch == "{" else "]"
    return out


def _scene_defect_notes(scene: object) -> list[str]:
    """Short defect tags for one raw scene: empty/short/long/missing visual."""
    from app.core import config as _cfg
    if not isinstance(scene, dict):
        return ["not an object"]
    notes: list[str] = []
    words = len(str(scene.get("narration_text")
                    or scene.get("narration") or "").split())
    wps = float(getattr(_cfg, "SCRIPT_WPS", 2.5)) or 2.5
    per_lo = max(6, int(round(15 * wps)))
    per_hi = max(12, int(round(25 * wps)))
    if words == 0:
        notes.append("empty narration")
    elif words < per_lo:
        notes.append(f"only {words} words (need {per_lo}-{per_hi})")
    elif words > per_hi * 2:
        notes.append(f"{words} words (too long, split it)")
    if not str(scene.get("visual_prompt")
               or scene.get("visual_direction") or "").strip():
        notes.append("missing visual_direction")
    return notes


def _fatal_scene_notes(data: dict) -> str:
    """One-line scene breakdown recomputed from stored scenes (log/correction).

    pre_validate_script strips its internal notes before returning, so this
    recomputes the same defect tags from the scenes themselves — narration
    content is never read into the message beyond word counts.
    """
    scenes = data.get("scenes") if isinstance(data, dict) else None
    if not isinstance(scenes, list):
        return ""
    parts = []
    for i, s in enumerate(scenes):
        sid = s.get("scene_id", i + 1) if isinstance(s, dict) else i + 1
        notes = _scene_defect_notes(s)
        if notes:
            parts.append(f"scene {sid}: {', '.join(notes)}")
    return "; ".join(parts)


def dump_attempt_raw(attempt: int, text: str) -> None:
    """Persist the raw LLM reply for SCRIPT attempt N (debugging aid).

    Always-on, tiny (a few KB), git-ignored via logs/*. Dumps are the only way
    to see what a reasoning model actually emitted when a scene comes back
    empty or `scenes` collapses to a non-list; the pipeline log only keeps a
    500-char fingerprint. Reuses LOGS_DIR from the existing config.
    """
    try:
        from app.core import config as _cfg
        dump_dir = Path(str(getattr(_cfg, "LOGS_DIR", "logs") or "logs"))
        dump_dir.mkdir(parents=True, exist_ok=True)
        (dump_dir / f"script_attempt{attempt}_raw.txt").write_text(
            text or "", encoding="utf-8")
    except Exception:
        pass


def _scene_complete(scene: object) -> bool:
    """A scene is complete only when it has BOTH spoken text and a visual."""
    if not isinstance(scene, dict):
        return False
    narration = str(scene.get("narration_text") or scene.get("narration") or "").strip()
    visual = str(scene.get("visual_prompt") or scene.get("visual_direction") or "").strip()
    return bool(narration) and bool(visual)


_THINK_RE = re.compile(r"<think(?:ing)?>.*?</think(?:ing)?>", re.DOTALL | re.IGNORECASE)


def _strip_reasoning(text: str) -> str:
    """Drop a reasoning model's internal thinking trace (deepseek-r1 etc.).

    Never touches JSON content: it removes only the known non-JSON reasoning block so
    the widest-brace extraction cannot lock onto a brace inside the trace.
    Truncation safety: the model may repeat the preamble on RETRIES and get cut off
    mid-<think>, leaving an unterminated tag whose trace runs to EOF. In that case
    the JSON AFTER the tag is gone too, and cutting everything from the LAST tag
    start would throw away a good script that preceded it — so cut only when the
    open tag comes BEFORE any JSON object start.
    """
    out = _THINK_RE.sub("", text or "")
    low = out.lower()
    for tag in ("<think", "<thinking"):
        idx = low.find(tag)
        if idx != -1 and out.find("{", idx) == -1:
            # No JSON after the tag → the trace swallowed the reply (or there
            # never was one). Cut the trace, keep any script before it.
            out = out[:idx]
            break
    # A finished thinking block: real JSON always FOLLOWS thinking, never
    # precedes it. Keep everything after the LAST closing tag so a repeated
    # preamble (retries print the whole prompt + trace + script) cannot cause
    # the widest-brace span to merge the trace's braces with the real script.
    closers = [m.end() for m in re.finditer(r"</think(?:ing)?>",
                                            out, re.IGNORECASE)]
    if closers:
        out = out[max(closers):]
    return out.strip()


def _iter_json_objects(text: str) -> list[str]:
    """Yield candidate {...} spans (balanced, string-aware) in source order.

    Lets parse_script_json() prefer the FIRST complete script-like object even
    when a reasoning model emitted a bare thought preamble or a second trailing
    JSON block after the real script. Structure-only: string contents are never
    modified.
    """
    spans: list[str] = []
    n = len(text or "")
    i = 0
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        depth = 0
        in_str = False
        esc = False
        end = -1
        for j in range(i, n):
            ch = text[j]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    spans.append(text[i:j + 1])
                    end = j
                    break
        i = (end + 1) if end != -1 else (i + 1)
    return spans


def _looks_like_script(data: object) -> bool:
    """True when `data` is a script-shaped object (scenes + spoken text)."""
    if not isinstance(data, dict):
        return False
    scenes = data.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        return False
    first = scenes[0] if isinstance(scenes[0], dict) else {}
    return bool(str(first.get("narration_text")
                    or first.get("narration") or "").strip())


def _drop_trailing_incomplete(scenes: list) -> None:
    """Drop trailing empty-narration / half-written scene dicts in place.

    Safety policy: an unterminated trailing object recovered by repair helpers
    may parse with an empty narration (the model's words were cut off by the
    context/timeout limit), and a reasoning model may emit a trailing
    half-written scene even when the earlier tag pair was closed. Dropping
    trailing phantom TAILS is safe because re-running the retry will regenerate
    the scenes with REAL narration. Middle empty scenes and leading empties
    stay fatal — they indicate the model emitted a placeholder, not a
    truncation. A single empty scene is also kept: the engine must reject it,
    not silently pass an empty script.
    """
    if not isinstance(scenes, list) or len(scenes) < 2:
        return
    while len(scenes) > 1:
        last = scenes[-1]
        if not isinstance(last, dict):
            scenes.pop()
            continue
        if str(last.get("narration_text") or last.get("narration") or "").strip():
            return  # last scene complete: nothing to drop
        scenes.pop()


def _strip_trailing_commas(text: str) -> str:
    """Remove commas that sit directly before a closing } or ] (outside strings).

    Purely structural: a trailing comma is never valid JSON and removing it cannot
    change any string content.
    """
    out: list[str] = []
    in_str = False
    esc = False
    i = 0
    while i < len(text):
        ch = text[i]
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
        elif ch == ",":
            j = i + 1
            while j < len(text) and text[j] in " \t\r\n":
                j += 1
            if j < len(text) and text[j] in "}]":
                i += 1  # drop the comma before the closer
                continue
            out.append(ch)
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def parse_script_json(text: str) -> dict:
    """Parse script JSON, tolerating the classic small-model defects.

    Handled safely (structure only - narration text is never rewritten):
    reasoning-model thinking traces (tagged or bare preambles), ```json fences,
    prose around the object, trailing commas, missing final closing delimiters,
    and a trailing scene cut off mid-write (dropped, never completed with
    invented content). Raises json.JSONDecodeError when nothing salvageable
    remains, so the existing retry path still runs.
    """
    cleaned = _strip_reasoning(text)
    raw = extract_json(cleaned)
    candidates: list[str] = [raw]
    b_start, b_end = cleaned.find("{"), cleaned.rfind("}")
    if b_start != -1 and b_end > b_start and cleaned[b_start:b_end + 1] != raw:
        # The widest-span rule picked another block (e.g. prose containing a
        # bracket): also try the outermost JSON object.
        candidates.append(cleaned[b_start:b_end + 1])
    # Reasoning models (deepseek-r1) may emit a bare thought preamble or think
    # FORWARD into a second JSON block after the real script. Prefer the first
    # COMPLETE, script-shaped object in source order; the widest-span candidate
    # above would otherwise merge both blocks into one invalid document.
    for span in _iter_json_objects(cleaned):
        if span not in candidates:
            candidates.append(span)
    best_structural: dict | None = None
    best_pos: int | None = None
    first_err: json.JSONDecodeError | None = None
    for cand in candidates:
        for variant in (cand, _strip_trailing_commas(cand)):
            try:
                data = json.loads(variant)
            except json.JSONDecodeError as e:
                if first_err is None:
                    first_err = e
                data = None
            else:
                if _looks_like_script(data):
                    _drop_trailing_incomplete(data["scenes"])
                    return data
                pos = cleaned.find(variant) if variant else -1
                if isinstance(data, dict) and pos != -1 and (
                        best_structural is None
                        or (best_pos is not None and pos < best_pos)):
                    best_structural = data
                    best_pos = pos
                continue
            try:
                data = json.loads(_close_containers(variant))
            except json.JSONDecodeError:
                # A second well-formed JSON object AFTER the script (forward
                # thinking) makes the widest span unparseable; the ordered
                # object spans below still recover the real script.
                continue
            scenes = data.get("scenes") if isinstance(data, dict) else None
            if isinstance(scenes, list):
                _drop_trailing_incomplete(scenes)
            if _looks_like_script(data):
                _drop_trailing_incomplete(data["scenes"])
                return data
            pos = cleaned.find(variant) if variant else -1
            if isinstance(data, dict) and pos != -1 and (
                    best_structural is None
                    or (best_pos is not None and pos < best_pos)):
                best_structural = data
                best_pos = pos
    if best_structural is not None:
        # No candidate looked like a finished script (e.g. every candidate has an
        # empty narration): return the earliest structural object so validation —
        # not the parser — produces the actionable retry message.
        return best_structural
    if first_err is not None:
        raise first_err
    raise json.JSONDecodeError("could not find a JSON object in the model reply",
                               cleaned or "", 0)



def pre_validate_script(data: dict) -> tuple[dict, list[str]]:
    """Parse-order pipeline: normalize field names -> narration check ->
    duration derive/clamp -> visual split. Returns (normalized_data, fatal_issues).

    Missing duration is DERIVED here (never fatal). Empty narration is FATAL
    (never patched — must go through LLM retry). Surplus scenes are NOT fatal:
    the engine only ever trims to Pydantic's hard cap (16), so a 9-scene script
    under SCRIPT_MAX_SCENES=16 stays intact while a 13+ scene reply becomes
    valid without another LLM round-trip. Surplus under SCRIPT_MAX_SCENES is
    NEVER trimmed here (only Pydantic's cap applies); the length gate decides
    whether the total still fits the target window.

    Does NOT cap to SCRIPT_MAX_SCENES: deepseek-r1 can emit 13+ scenes and the
    pipeline would otherwise tell the model to EXPAND a script that is already
    too long.
    """
    from app.core import config as _cfg
    fatals: list[str] = []
    if not isinstance(data, dict):
        return data, ["top-level JSON must be an object with scenes"]
    scenes = data.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        return data, ["scenes must be a non-empty list"]
    max_scenes = max(1, min(int(getattr(_cfg, "SCRIPT_MAX_SCENES", 16)), 16))
    try:
        cap = int(getattr(Script.model_fields["scenes"], "max_length", max_scenes)
                  or max_scenes)
    except Exception:
        cap = max_scenes
    cap = max(1, min(cap, 16))
    if len(scenes) > cap:
        data = dict(data)
        data["scenes"] = list(scenes[:cap])
        scenes = data["scenes"]
    normed: list[dict] = []
    for i, raw in enumerate(scenes):
        s = raw if isinstance(raw, dict) else {}
        sid = s.get("scene_id", i + 1)
        notes = _scene_defect_notes(s)
        # Fatal: empty narration (no silent replacement allowed).
        if "empty narration" in notes:
            fatals.append(f"scene {sid}: empty narration. Every scene must contain "
                          f"a non-empty spoken sentence.")
        n = normalize_scene(s)  # derives + clamps duration deterministically
        try:
            n["scene_id"] = int(n.get("scene_id", sid))
        except (TypeError, ValueError):
            n["scene_id"] = sid
            fatals.append(f"scene {sid}: scene_id must be an integer.")
        normed.append(n)
    data = dict(data)
    data["scenes"] = normed
    data.pop("_fatal_scene_notes", None)  # internal log/correction detail only
    return data, fatals


_TOP_LEVEL_FIELDS = ("title", "description", "tags", "keywords",
                     "target_duration_seconds", "bgm_style", "scenes")


def correction_message(data: dict, exc: Exception | None = None) -> str:
    """Compact structured correction for the next LLM retry (no Pydantic dump)."""
    bits: list[str] = []
    scenes = data.get("scenes") if isinstance(data, dict) else None
    if isinstance(scenes, list):
        for i, raw in enumerate(scenes):
            sid = raw.get("scene_id", i + 1) if isinstance(raw, dict) else i + 1
            for issue in scene_validation_issues(raw if isinstance(raw, dict) else {}):
                if issue == "empty narration":
                    bits.append(f"scene {sid} contained empty narration. Every scene "
                                f"must contain a non-empty spoken sentence.")
                elif issue == "missing estimated_duration_seconds":
                    bits.append(f"scene {sid} omitted estimated_duration_seconds. Every "
                                f"scene must include it (number 5-30).")
                elif issue == "missing visual_direction":
                    bits.append(f"scene {sid} omitted visual_direction. Describe only "
                                f"visible objects/scenes, no text.")
    if exc is not None:
        msg = str(exc)[:300]
        if "estimated_duration_seconds" in msg and not any("estimated_duration" in b for b in bits):
            bits.append("Your previous JSON omitted estimated_duration_seconds. Every "
                        "scene must include it.")
        if "narration" in msg and not any("empty narration" in b for b in bits):
            bits.append("Your previous JSON contained empty narration. Every scene must "
                        "contain a non-empty spoken sentence.")
        if isinstance(exc, ValidationError):
            # Pydantic names the offending field - far more actionable than a dump.
            for err in getattr(exc, "errors", lambda: [])()[:3]:
                loc = [str(p) for p in (err.get("loc") or ())]
                if len(loc) != 1 or loc[0] not in _TOP_LEVEL_FIELDS:
                    continue
                if any(loc[0] in b for b in bits):
                    continue
                bits.append(f"top-level field '{loc[0]}' is missing or invalid "
                            f"({str(err.get('msg', 'invalid'))[:60]}). It must be "
                            f"present and valid in the JSON object.")
    seen: list[str] = []
    for b in bits:
        if b not in seen:
            seen.append(b)
    if not seen and exc is not None:
        # Unparseable / non-scene errors: give the small model an actionable,
        # compact instruction instead of an empty correction (which used to
        # resend the identical prompt and fail the same way).
        if isinstance(exc, json.JSONDecodeError):
            seen.append(
                "Your previous reply was NOT valid JSON (" + str(exc.msg)[:80] + "). "
                "Output ONE JSON object only: no markdown, no ``` fences, no text before "
                "or after the object, every string in double quotes, commas between all "
                "values, and never put unescaped double quotes inside a string value.")
        else:
            seen.append(
                "Your previous JSON did not match the schema. Output ONE JSON object "
                "with EXACTLY these keys: title, description, tags, keywords, "
                "target_duration_seconds, bgm_style, scenes[]. Every scene needs "
                "scene_id, narration, visual_direction, estimated_duration_seconds.")
    return " ".join(seen[:4])  # compact: at most 4 sentences


def validate_script(data: dict) -> Script:
    return Script.model_validate(data)


def script_word_count(script: dict) -> int:
    """Total spoken narration words across scenes (same text the estimate uses)."""
    total = 0
    for raw in ((script or {}).get("scenes") or []):
        if isinstance(raw, dict):
            total += len(str(raw.get("narration_text") or raw.get("narration") or "").split())
    return total


def script_estimated_total(script: dict) -> float:
    """Estimated total from the actual narration words (no stretching).

    Uses narration word count / SCRIPT_WPS for every scene; never invents time and
    never trusts the model's own estimated_duration_seconds values.
    """
    from app.core import config as _cfg
    wps = float(getattr(_cfg, "SCRIPT_WPS", 2.5)) or 2.5
    return round(script_word_count(script) / wps, 2)


def script_length_issues(script: dict, num_scenes_expected: int | None = None) -> list[str]:
    """Cross-scene duration gate for long-form (3-4 min) videos.

    Per-scene durations stay clamped to SCENE_MIN/MAX_SECONDS; this checks the
    script as a whole: scene count + total estimated narration length.
    A too-short script must be expanded by the LLM (real narration), never
    stretched/duplicated downstream.

    num_scenes_expected overrides the floor only when the caller EXPLICITLY
    requests a short-form script (e.g. unit fixtures with num_scenes=1); the
    long-form production path always requires SCRIPT_MIN_SCENES.
    """
    from app.core import config as _cfg
    issues: list[str] = []
    scenes = (script or {}).get("scenes") if isinstance(script, dict) else None
    n = len(scenes) if isinstance(scenes, list) else 0
    total = script_estimated_total(script if isinstance(script, dict) else {})
    lo_n = int(getattr(_cfg, "SCRIPT_MIN_SCENES", 8))
    if num_scenes_expected is not None and int(num_scenes_expected) < lo_n:
        lo_n = int(num_scenes_expected)
    lo_s = float(getattr(_cfg, "SCRIPT_TARGET_MIN_SECONDS", 180))
    hi_s = float(getattr(_cfg, "SCRIPT_TARGET_MAX_SECONDS", 240))
    if num_scenes_expected is not None and int(num_scenes_expected) < int(
            getattr(_cfg, "SCRIPT_MIN_SCENES", 8)):
        lo_s = 0.0  # short-form fixture: only count/scene gates apply, no duration floor
    if n < lo_n:
        issues.append(f"script has only {n} scenes (minimum {lo_n}). Add "
                      f"{lo_n - n} more scene(s) with real spoken narration.")
    if total < lo_s:
        issues.append(f"estimated narration is only {total:.1f}s "
                      f"(target {lo_s:.0f}-{hi_s:.0f}s). Expand every narration "
                      "to 15-25 seconds of natural speech.")
    elif lo_s > 0 and total > hi_s:
        # Long-form only: the ceiling is enforced together with the floor so the
        # result stays inside the configured target window. Short-form callers pass
        # an explicit small num_scenes and keep no floor/ceiling.
        issues.append(f"estimated narration is {total:.1f}s, above the {hi_s:.0f}s "
                      f"maximum (target {lo_s:.0f}-{hi_s:.0f}s). Tighten the longest "
                      "scenes; do not remove scenes.")
    return issues


def resolve_script_model(available: list[str], preferred: str = "",
                         fallback: str = "") -> str:
    """Pick the SCRIPT model: preferred when installed, else the fallback.

    Pure function (no network). `available` is the installed-model list from the
    existing OllamaClient.check_model(); matching reuses OllamaClient.model_in_list
    so base-name/tag handling lives in one place.
    """
    from app.llm.ollama_client import model_in_list
    pref = str(preferred or "").strip()
    fb = str(fallback or "").strip()
    if pref and model_in_list(pref, available):
        return pref
    if fb and model_in_list(fb, available):
        return fb
    return pref or fb


# Ollama's structured-output grammar ("format": "json") is unusable with
# reasoning/"thinking" models: the template has to emit the JSON grammar before
# any thinking, so deepseek-r1:7b answers with an EMPTY object ("{ }", 6 chars,
# ~24s - measured) instead of a script, and the pipeline then dies with
# "scenes must be a non-empty list". Those models therefore run in PLAIN mode;
# parse_script_json() already strips the <think> trace, any prose around the
# object, and salvages missing closing delimiters.
_REASONING_MODEL_RE = re.compile(r"[/:_-](r1|qwq|think|reason)", re.IGNORECASE)


def json_mode_supported(model: str) -> bool:
    """True when Ollama JSON mode is safe for `model` (pure, no network).

    Non-reasoning models (llama3.2, qwen2.5, mistral...) benefit from JSON mode.
    Reasoning builds (deepseek-r1, qwq, *-think-*) return an empty object under
    the JSON grammar, so they are always called in plain mode.
    """
    return not _REASONING_MODEL_RE.search(str(model or ""))


def _supports_kwarg(func, name: str) -> bool:
    """True when a generate() implementation accepts `name`.

    Keeps the engine usable with the deterministic test clients, which only accept
    (prompt, options=...).
    """
    try:
        params = inspect.signature(func).parameters
    except (TypeError, ValueError):
        return False
    if name in params:
        return True
    return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


def _generate(client, prompt: str, options: dict, use_json: bool = True):
    """One SCRIPT LLM call on the existing client (JSON mode when supported)."""
    from app.core import config
    kwargs: dict = {}
    if _supports_kwarg(client.generate, "system"):
        kwargs["system"] = SYSTEM_PROMPT
    model = str(getattr(client, "text_model", "") or "")
    if (use_json and getattr(config, "SCRIPT_JSON_MODE", True)
            and json_mode_supported(model)
            and _supports_kwarg(client.generate, "fmt")):
        kwargs["fmt"] = "json"
    return client.generate(prompt, options=options, **kwargs)


def correction_for_length(script: dict, num_scenes: int, target_seconds: int) -> str:
    """Expansion correction that states the MEASURED length (retries differ).

    Long-form callers (>= SCRIPT_MIN_SCENES scenes) keep the 180-240s window
    wording unchanged. Short-form callers (explicitly small num_scenes) get a
    correction consistent with THEIR target - the old text demanded 180-240s of
    narration from e.g. a 60s/3-scene request, contradicting itself on retry.
    """
    b = _word_budget(target_seconds, num_scenes)
    scenes = [s for s in ((script or {}).get("scenes") or []) if isinstance(s, dict)]
    total = script_estimated_total(script)
    words = script_word_count(script)
    n_req = max(1, int(num_scenes))
    parts = [
        f"The previous script was only {total:.0f} seconds of narration "
        f"({words} words in {len(scenes)} scenes).",
        "Do NOT rewrite it briefly and do NOT summarise it: generate substantially "
        "longer narration with new detail, examples and explanation.",
    ]
    if n_req >= b["min_scenes"]:
        min_scenes = max(1, min(b["min_scenes"], n_req))
        max_scenes = max(min_scenes, min(b["max_scenes"], 12))
        parts += [
            f"Produce {min_scenes} to {max_scenes} scenes (no more than 12) with "
            f"15-25 seconds "
            f"({b['per_scene_lo']}-{b['per_scene_hi']} words) of spoken narration in EACH "
            "scene, 3-5 sentences per scene.",
            f"The COMPLETE narration must be {b['total_lo']}-{b['total_hi']} words = "
            f"180-240 seconds of speech, ideally about {b['target_words']} words "
            f"(~{int(target_seconds)} seconds).",
        ]
    else:
        per = max(8, b["target_words"] // n_req)
        parts += [
            f"Return EXACTLY {n_req} scenes (scene_id 1 through {n_req}): a reply "
            f"with fewer than {n_req} scenes is rejected.",
            f"Each scene narration must be about {int(per * 0.8)}-{int(per * 1.2)} "
            f"words, about {b['target_words']} words in total "
            f"(~{int(target_seconds)} seconds).",
        ]
    return " ".join(parts)


# Deterministic local completion used when the LLM keeps returning too-short
# scripts. Splits an over-long narration: every scene keeps its own topic angle
# and visual, so no content is invented or duplicated — the model still wrote
# every word; only the scene BOUNDARIES change.
_SPLIT_CUES = (" however ", " but ", " instead ", " for example ",
               " for instance ", " then ", " next ", " finally ")


def _split_words(words: list[str], lo: int, hi: int) -> list[list[str]]:
    """Greedily cut a word list into chunks <= hi words (>= lo when possible).

    Splits prefer sentence ends, then discourse cues; pure function.
    """
    chunks: list[list[str]] = []
    cur: list[str] = []
    for w in words:
        cur.append(w)
        if len(cur) >= lo and (w.endswith((".", "?", "!"))
                               or (len(cur) >= hi - 8 and
                                   ("".join(cur[-3:]).lower().rstrip(".,!?")
                                    in ("however", "instead", "then", "next",
                                        "finally")))):
            chunks.append(cur)
            cur = []
        elif len(cur) >= hi:
            chunks.append(cur)
            cur = []
    if cur:
        if chunks and len(cur) < lo // 2:
            chunks[-1].extend(cur)
        else:
            chunks.append(cur)
    return [c for c in chunks if c]


def expand_short_script(script: dict, target_seconds: int = 210) -> dict:
    """Complete a too-short script deterministically (no LLM, no new wording).

    Splits each over-long narration into TWO scenes sharing the original
    visual direction: part 1 keeps the scene topic, part 2 continues it
    ("...continued"). Total narration seconds never change through a split.
    """
    from app.core import config as _cfg
    data = json.loads(json.dumps(script or {}))  # deep copy of plain data
    scenes = [s for s in (data.get("scenes") or []) if isinstance(s, dict)]
    wps = float(getattr(_cfg, "SCRIPT_WPS", 2.5)) or 2.5
    per_lo = max(6, int(round(15 * wps)))
    per_hi = max(12, int(round(25 * wps)))
    hi_total = float(getattr(_cfg, "SCRIPT_TARGET_MAX_SECONDS", 240))
    out: list[dict] = []
    for s in scenes:
        text = str(s.get("narration_text") or s.get("narration") or "")
        words = text.split()
        if 10 <= len(words) <= per_hi and len(out) + (len(scenes) - len(out)) < 16:
            out.append(s)
            continue
        if len(words) > per_hi and len(out) < 15:
            # Split over-long scene in two; both halves keep the original angle.
            chunks = _split_words(words, per_lo, per_hi)
            if len(chunks) >= 2:
                for k, ch in enumerate(chunks[:2]):
                    part = dict(s)
                    part["narration"] = " ".join(ch)
                    part["narration_text"] = part["narration"]
                    part["caption_text"] = part["narration"]
                    if k == 1:
                        v = str(part.get("visual_direction")
                                or part.get("visual_prompt") or "")
                        part["visual_direction"] = (v + " (continuation of "
                                                    "previous scene)").strip()
                        part["visual_prompt"] = part["visual_direction"]
                        part["stock_search_query"] = str(
                            part.get("stock_search_query") or "")
                    out.append(normalize_scene(part))
                continue
        out.append(s)
    if len(out) > 16:
        out = out[:16]
    data["scenes"] = out
    for i, s in enumerate(data["scenes"]):
        s["scene_id"] = i + 1
    data, _fatals = pre_validate_script(data)
    return data



def generate_script(topic: str, client, target_seconds: int = 210,
                    num_scenes: int = 9, max_retries: int = 2) -> dict[str, Any]:
    """Generate + validate + repair + length-gate with bounded retries.

    Attempt 1 asks for the complete long-form script. Every retry differs from the
    attempt that failed, on the SAME Ollama client (no second client, no Pydantic
    dumps to the LLM):
      * too short / too few scenes -> the MEASURED seconds plus the required
        words/scenes are stated explicitly (expand, never summarise);
      * invalid JSON -> a compact "valid JSON only" repair instruction plus the same
        length contract (the parser already salvages fences, think-traces, trailing
        commas, missing closers and a half-written trailing scene);
      * scene-level defects -> the existing compact scene correction.
    Raises ValueError on failure (message carries the measured length when the script
    stayed outside the long-form window after retries).
    """
    from app.core import config
    log("SCRIPT", "Generating for topic: {!r} (model={})".format(
        topic, getattr(client, "text_model", "?")))
    options = {"temperature": 0.7,
               "num_ctx": config.SCRIPT_NUM_CTX,
               "num_predict": config.SCRIPT_MAX_TOKENS}
    last_err = ""
    correction = ""
    use_json = True  # dropped when the model echoes a degenerate empty object
    for attempt in range(1, max_retries + 2):
        res = _generate(client,
                        build_prompt(topic, target_seconds, num_scenes, correction),
                        options, use_json=use_json)
        if not res.ok:
            last_err = res.error
            log("ERROR", f"SCRIPT attempt {attempt} LLM error: {res.error}")
            correction = ("The previous request failed at the model level ("
                          + str(res.error)[:120] + "). Repeat the task and return the "
                          "complete JSON object.")
            continue
        try:
            data = parse_script_json(res.text)
            data, fatals = pre_validate_script(data)  # normalize + derive duration
            if fatals:
                if use_json and not isinstance(
                        (data or {}).get("scenes") if isinstance(data, dict) else None,
                        list):
                    # JSON-mode degeneracy: the grammar made the model answer with
                    # an empty object ("{ }") instead of a script (observed with
                    # thinking models). The retry must DIFFER: call the same model
                    # in plain mode instead of asking for JSON again.
                    use_json = False
                    log("SCRIPT", f"Attempt {attempt}: empty JSON object -> retrying "
                                  f"without JSON mode")
                last_err = " ".join(fatals)[:1000]
                log("ERROR", f"SCRIPT attempt {attempt} invalid scene: {last_err[:300]}")
                snippet = re.sub(r"\s+", " ", (res.text or ""))[:500]
                log("SCRIPT", f"Attempt {attempt} raw fingerprint: {snippet}")
                # Actionable detail: which scenes broke and WHY (empty vs short
                # vs too long vs missing visual). Fold it into the next attempt's
                # correction so retries differ; keep it debuggable in pipeline.log.
                try:
                    per_scene = _fatal_scene_notes(data)
                    if per_scene:
                        log("SCRIPT", f"Attempt {attempt} scene detail: "
                                     f"{per_scene[:400]}")
                        correction = (last_err + " Scene detail: "
                                      + per_scene[:400])
                    else:
                        correction = last_err
                except Exception:
                    correction = last_err
                try:
                    dump_attempt_raw(attempt, res.text)
                    from app.core import config as _dbg_cfg
                    if str(getattr(_dbg_cfg, "SCRIPT_DUMP_RAW", "") or "").strip().lower() in (
                            "1", "true", "yes", "on"):
                        dump_dir = Path(str(getattr(_dbg_cfg, "LOGS_DIR", "logs") or "logs"))
                        dump_dir.mkdir(parents=True, exist_ok=True)
                        (dump_dir / f"script_attempt{attempt}_raw.txt").write_text(
                            res.text or "", encoding="utf-8")
                except Exception:
                    pass
                continue
            script = validate_script(data)  # final Pydantic gate (durations now present)
            dumped = script.model_dump()
            total = script_estimated_total(dumped)
            words = script_word_count(dumped)
            log("SCRIPT", "Attempt {}: {} scenes, {} words, estimated {:.1f}s".format(
                attempt, len(dumped.get("scenes", [])), words, total))
            length_problems = script_length_issues(dumped, num_scenes)
            if length_problems:
                last_err = " ".join(length_problems)[:1000]
                log("ERROR", f"SCRIPT attempt {attempt} length gate: {last_err[:300]}")
                # After SCRIPT_EXPAND_RETRIES exhausted retries of pure LLM
                # expansion, stop trusting the model and complete the script
                # locally instead of failing the whole pipeline.
                if attempt > max(1, int(getattr(config, "SCRIPT_EXPAND_RETRIES", 2))):
                    completed = expand_short_script(dumped, int(target_seconds))
                    total2 = script_estimated_total(completed)
                    issues2 = script_length_issues(completed, num_scenes)
                    words2 = script_word_count(completed)
                    log("SCRIPT",
                        "Completed via local expansion: {} scenes, {} words, "
                        "~{:.1f}s".format(len(completed.get("scenes", [])),
                                           words2, total2))
                    if not issues2:
                        return completed
                    last_err = " ".join(issues2)[:1000]
                    break
                correction = correction_for_length(dumped, num_scenes, target_seconds)
                continue
            log("SCRIPT", "Completed: {} scenes, {} words, ~{:.1f}s".format(
                len(dumped.get("scenes", [])), words, total))
            return dumped
        except (json.JSONDecodeError, ValidationError) as e:
            try:
                data2 = parse_script_json(res.text)
            except Exception:
                data2 = {}
            correction = correction_message(data2 if isinstance(data2, dict) else {}, e)
            last_err = (correction or str(e))[:1000]
            log("ERROR", f"SCRIPT attempt {attempt} invalid JSON: {last_err[:300]}")
            try:
                dump_attempt_raw(attempt, res.text)
                from app.core import config as _dbg_cfg2
                if str(getattr(_dbg_cfg2, "SCRIPT_DUMP_RAW", "") or "").strip().lower() in (
                        "1", "true", "yes", "on"):
                    dump_dir = Path(str(getattr(_dbg_cfg2, "LOGS_DIR", "logs") or "logs"))
                    dump_dir.mkdir(parents=True, exist_ok=True)
                    (dump_dir / f"script_attempt{attempt}_raw.txt").write_text(
                        res.text or "", encoding="utf-8")
            except Exception:
                pass
            if isinstance(e, ValidationError):
                # Pydantic rejects BEFORE pre_validate_scene caps scene counts:
                # the reply is parseable JSON but structurally unusable (e.g. 13+
                # scenes, extra scene fields). Log a same-line fingerprint of the
                # raw reply so failures stay debuggable from pipeline.log alone.
                snippet = re.sub(r"\s+", " ", (res.text or ""))[:500]
                log("SCRIPT", f"Attempt {attempt} raw fingerprint: {snippet}")
    raise ValueError(f"Script generation failed after retries: {last_err[:500]}")


def save_script(script: dict, path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(script, indent=2, ensure_ascii=False), encoding="utf-8")
    log("SCRIPT", f"Saved -> {path}")
    return path
