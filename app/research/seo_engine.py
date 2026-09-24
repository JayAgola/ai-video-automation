"""SEO engine: titles + description + tags + keywords + hashtags + title scoring."""
from __future__ import annotations

import re


def _titles(topic: str, keywords: list) -> list:
    kw = (keywords[0] if keywords else topic.split(":")[0]).strip()
    return [
        "{} — A Practical Stoic Guide".format(topic),
        "Why {} (And 5 Ways to Break the Loop)".format(kw),
        "{}: Psychology Meets Stoicism".format(topic),
        "Stop {}: A Calm, Actionable Method".format(kw),
        "The Truth About {} Nobody Explains Simply".format(kw),
    ]


def generate_seo(topic: str, keywords: list, audience: str, angle: str) -> dict:
    titles = _titles(topic, keywords)
    desc = ("{} — {}. For {}: an original, practical breakdown with "
            "modern examples and Stoic tools. No copied content; independent "
            "explanations you can apply today.").format(topic, angle, audience)
    tags = list(dict.fromkeys([k.lower() for k in keywords] + [
        "stoicism", "psychology", "self improvement", "mindset", "mental health"]))
    return {"title_options": titles, "description": desc, "tags": tags[:15],
            "keywords": keywords[:10],
            "hashtags": ["#{}".format(re.sub(r'[^a-z0-9]', '', k.lower()) or "stoicism")
                         for k in keywords[:5]] or ["#stoicism"]}


CLICKBAIT = ["shocking", "you won't believe", "100% guaranteed", "miracle", "!!!"]


def score_title(title: str, keywords: list) -> dict:
    reasons = []
    score = 60.0
    if any(k.lower() in title.lower() for k in keywords):
        score += 12
        reasons.append("Contains target keyword")
    if 30 <= len(title) <= 70:
        score += 8
        reasons.append("Good length ({} chars)".format(len(title)))
    if "?" in title or title.strip().startswith(("Why", "How", "Stop", "The")):
        score += 8
        reasons.append("Clear hook without misleading claim")
    low = title.lower()
    if any(c in low for c in CLICKBAIT):
        score -= 20
        reasons.append("Flagged: possible clickbait language")
    if sum(1 for c in title if c.isupper()) > len(title) * 0.4:
        score -= 10
        reasons.append("Excessive capitalization")
    if title.count("!") + title.count("?") > 2:
        score -= 5
        reasons.append("Excessive punctuation")
    return {"title": title, "score": round(max(min(score, 100.0), 0.0), 1), "reasons": reasons}


def thumbnail_concepts(topic: str, keywords: list) -> dict:
    kw = keywords[0] if keywords else topic
    return {"thumbnail_concepts": [
        {"concept": "Split night/day mind", "visual_prompt": "16:9 illustration, left chaotic dark mind, right calm sunrise, text-free background",
         "text": "QUIET THE NOISE", "composition": "face silhouette center, contrast halves", "emotion": "relief"},
        {"concept": "Stoic statue + modern city", "visual_prompt": "16:9 marble Stoic bust over blurred city lights, teal/amber palette",
         "text": "STAY CALM", "composition": "statue left third, bold text right", "emotion": "resolve"},
        {"concept": "Breaking loop", "visual_prompt": "16:9 circular thought-loop cracking open into light path, minimal flat style",
         "text": "BREAK THE LOOP", "composition": "loop center, light exit top-right", "emotion": "hope"},
    ]}
