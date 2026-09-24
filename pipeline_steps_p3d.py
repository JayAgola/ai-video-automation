"""Research report writer (human-readable WHY for topic selection)."""
from __future__ import annotations
import json
from app.core import config
from app.core.project_manager import ProjectManager


def write_report(pm: ProjectManager, pid: str, selected: dict, package: dict) -> None:
    from pipeline_steps_p3 import research_dir
    trends_p = research_dir(pm, pid) / "trends.json"
    trends = json.loads(trends_p.read_text(encoding="utf-8")) if trends_p.exists() else {}
    L = ["# Research report — {}".format(pid), "",
         "- Date: {}".format(trends.get("date", "")),
         "- Niche: {}".format(trends.get("niche", config.CHANNEL_NICHE)),
         "- Provider: {} {}".format(trends.get("provider", "?"),
            "(TEST DATA — NOT REAL YOUTUBE DATA)" if trends.get("test_data") else "")]
    L.append("- Queries: {}".format(", ".join(trends.get("queries", []))))
    L.append("- Results: {} unique ({} raw)".format(
        trends.get("total_unique", 0), trends.get("total_raw", 0)))
    L.append("")
    L.append("## Top keywords")
    for k in (trends.get("top_keywords", []) or [])[:10]:
        L.append("- {} ({})".format(k["keyword"], k["mentions"]))
    L += ["", "## Selected topic",
          "- **{}** (score {})".format(selected.get("topic"), selected.get("score")),
          "- Angle: {}".format(selected.get("angle")),
          "- Gap: {}".format(selected.get("content_gap")),
          "- Competition: {} ({})".format(selected.get("competition", {}).get("level"),
                                          selected.get("competition", {}).get("reason")),
          "- Originality: {}".format(selected.get("originality_check")), "",
          "## SEO",
          "- Recommended: **{}**".format(package.get("recommended_title"))]
    for t in package.get("title_scores", []):
        L.append("- {} — {} ({})".format(t["title"], t["score"], "; ".join(t["reasons"])))
    L += ["", "- Tags: {}".format(", ".join(package.get("tags", []))),
          "- Hashtags: {}".format(", ".join(package.get("hashtags", []))), "",
          "## Thumbnail concepts"]
    for c in package.get("thumbnail_concepts", []):
        L.append("- {} | text={!r} | {}".format(c["concept"], c["text"], c["visual_prompt"]))
    (research_dir(pm, pid) / "research_report.md").write_text("\n".join(L), encoding="utf-8")
