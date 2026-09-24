"""Topic candidate generation via centralized Ollama (compact summaries only).

Sends Python-aggregated trend summaries (NOT raw API dumps) to llama3.2:3b.
Deterministic fallback builds candidates from keywords when LLM is unavailable.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from app.core import config
from app.core.logger import log
from app.script.script_engine import extract_json

GAP_ANGLES = [
    "beginner-friendly explanation with practical steps",
    "modern workplace examples",
    "myth vs reality",
    "common mistakes to avoid",
    "psychological explanation plus Stoic framework",
    "short actionable 5-step method",
]


def build_summary(trends: dict, sample_titles: list, niche: str) -> str:
    kws = ", ".join(k["keyword"] for k in trends.get("top_keywords", [])[:10])
    pats = "\n".join("- {}".format(t) for t in sample_titles[:8])
    return ("Niche: {}\nRecurring keywords: {}\nHigh-performing patterns:\n{}"
            ).format(niche, kws, pats)


def _fallback_candidates(summary: str, trends: dict, count: int) -> list[dict]:
    kws = [k["keyword"] for k in trends.get("top_keywords", [])[:count]] or ["focus"]
    cands = []
    for i, kw in enumerate(kws[:count]):
        angle = GAP_ANGLES[i % len(GAP_ANGLES)]
        topic = "{}: {}".format(kw.title(), angle.title())
        tid = hashlib.sha256(topic.encode()).hexdigest()[:10]
        cands.append({
            "topic_id": tid, "topic": topic,
            "core_question": "How can {} help with {}?".format(angle, kw),
            "audience_problem": "Struggling with {}".format(kw),
            "angle": angle, "why_now": "Rising search interest in {}".format(kw),
            "search_keywords": [kw, "stoicism", "psychology"],
            "content_gap": angle, "estimated_competition": "MEDIUM",
            "originality_notes": "Original angle '{}'; own wording, no source copied.".format(angle),
        })
    return cands


def generate_candidates(summary: str, trends: dict, sample_titles: list,
                        client=None, count: int = 12) -> list[dict]:
    prompt = (
        "You generate ORIGINAL YouTube topic ideas. Output JSON list only.\n"
        "Niche summary:\n{}\n\nProduce {} original topics inspired by (never copying) "
        "these patterns. Each item: topic_id, topic, core_question, audience_problem, "
        "angle, why_now, search_keywords[3], content_gap, estimated_competition "
        "(LOW/MEDIUM/HIGH), originality_notes. No transcript copying."
    ).format(summary, count)
    if client is None:
        try:
            from app.llm.ollama_client import OllamaClient
            client = OllamaClient()
        except Exception:
            client = None
    if client is not None:
        try:
            res = client.generate(prompt, options={"temperature": 0.8})
            if res.ok:
                data = json.loads(extract_json(res.text))
                items = data if isinstance(data, list) else data.get("candidates", [])
                if items:
                    log("TOPIC", "Generated {} candidates via Ollama".format(len(items)))
                    return items[:count]
        except Exception as e:
            log("ERROR", "Topic LLM failed, using fallback: {}".format(str(e)[:200]))
    log("TOPIC", "Generated {} candidates via deterministic fallback".format(count))
    return _fallback_candidates(summary, trends, count)
