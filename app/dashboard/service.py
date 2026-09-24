"""Dashboard service: reads existing state/cache/artifacts (NEVER generates).

All functions are lightweight and only inspect on-disk data. They reuse the
existing ProjectManager/StateManager and the project directory layout.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from app.core import config
from app.core.project_manager import ProjectManager

# Projects may only be simple names (blocks path traversal like ../../).
PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

LOG_LINE_RE = re.compile(
    r"^(?P<ts>\S+Z?)\s+(?P<level>\w+)\s+\[(?P<component>[A-Z_]+)\]\s*(?P<message>.*)$")


def is_valid_project_id(project_id: str) -> bool:
    return bool(PROJECT_ID_RE.fullmatch(project_id or ""))


def load_state_safe(pm: ProjectManager, project_id: str) -> dict | None:
    """Return parsed state, or None if missing/unreadable/corrupt (no crash)."""
    path = pm.project_path(project_id) / "state.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        return data
    except Exception:
        return None


def available(path: Path) -> bool:
    try:
        return path.exists() and path.stat().st_size > 0
    except Exception:
        return False


def _script_scenes(project_path: Path) -> list:
    sp = project_path / "script.json"
    if not sp.exists():
        return []
    try:
        data = json.loads(sp.read_text(encoding="utf-8"))
        return data.get("scenes", []) if isinstance(data, dict) else []
    except Exception:
        return []


def title_from_script(project_path: Path):
    sp = project_path / "script.json"
    if not sp.exists():
        return None
    try:
        data = json.loads(sp.read_text(encoding="utf-8"))
        return data.get("title") if isinstance(data, dict) else None
    except Exception:
        return None


def pipeline_progress(state: dict, steps=None) -> dict:
    steps = steps or config.DASH_STEPS
    completed = set(state.get("completed_steps", []) or [])
    failed = set(state.get("failed_steps", []) or [])
    current = state.get("current_step")
    running = (state.get("status") == "IN_PROGRESS")
    nodes = []
    for s in steps:
        if s in completed:
            status = "completed"
        elif s in failed:
            status = "failed"
        elif running and current == s:
            status = "running"
        else:
            status = "pending"
        nodes.append({"step": s, "status": status,
                      "label": s.replace("_", " ").title()})
    done = sum(1 for n in nodes if n["status"] == "completed")
    total = max(len(nodes), 1)
    return {"steps": nodes, "completed": done, "total": total,
            "percent": round(100.0 * done / total, 1)}
def scene_progress(project_path: Path, state: dict | None) -> dict:
    """Scene progress from actual artifacts; never invents values."""
    scenes = _script_scenes(project_path)
    total = len(scenes) if scenes else None
    if not total:
        return {"completed": None, "total": None, "percent": None, "detail": "Not available"}
    if state is None:
        return {"completed": None, "total": total, "percent": None, "detail": "Not available"}
    data = state.get("data", {}) or {}
    chunks = data.get("chunks", {}) or {}
    visuals = data.get("visuals", {}) or {}
    completed = 0
    for sc in scenes:
        sid = str(sc.get("scene_id", "")).zfill(3)
        if chunks.get("scene_" + sid) == "COMPLETED" and \
           (project_path / "chunks" / ("scene_" + sid + ".mp4")).exists():
            completed += 1
    percent = round(100.0 * completed / total, 1)
    return {"completed": completed, "total": total, "percent": percent,
            "detail": "{} / {} completed".format(completed, total),
            "visuals_tracked": sum(1 for v in visuals.values() if v == "COMPLETED") or None}


def artifacts(pm: ProjectManager, project_id: str) -> dict:
    pp = pm.project_path(project_id)

    def file_art(name: str) -> dict:
        p = pp / name
        return {"exists": available(p), "kind": "file",
                "size_bytes": p.stat().st_size if p.exists() else None}

    def dir_art(name: str) -> dict:
        p = pp / name
        if not p.is_dir():
            return {"exists": False, "kind": "dir", "count": None}
        try:
            count = sum(1 for f in p.iterdir() if f.is_file())
        except Exception:
            count = None
        return {"exists": count is not None and count > 0, "kind": "dir", "count": count}

    out = {
        "state.json": file_art("state.json"),
        "script.json": file_art("script.json"),
        "research": dir_art("research"),
        "audio": dir_art("audio"),
        "visuals": dir_art("visuals"),
        "chunks": dir_art("chunks"),
        "output": dir_art("output"),
        "final_video.mp4": file_art("output/final_video.mp4"),
    }
    for name in ("selected_topic.json", "seo.json", "trends.json", "topics.json",
                 "research_report.md"):
        out[name] = file_art("research/" + name)
    return out


def final_video_info(pm: ProjectManager, project_id: str, state: dict | None) -> dict:
    p = pm.project_path(project_id) / "output" / "final_video.mp4"
    info = {"available": available(p), "size_bytes": None, "duration_sec": None}
    if p.exists():
        info["size_bytes"] = p.stat().st_size
        if state:
            dur = (state.get("data", {}) or {}).get("mixed_duration") or \
                  (state.get("data", {}) or {}).get("final_duration")
            if isinstance(dur, (int, float)):
                info["duration_sec"] = round(float(dur), 1)
    return info


def project_summary(pm: ProjectManager, project_id: str) -> dict:
    state = load_state_safe(pm, project_id)
    base = {
        "project_id": project_id, "topic": None, "current_step": None,
        "status": None, "completed_steps": [], "created_at": None,
        "updated_at": None, "progress_percent": None, "scenes_completed": None,
        "scenes_total": None, "final_video_available": False,
        "review_status": None, "state_available": state is not None,
    }
    if state is None:
        return base
    pp = pm.project_path(project_id)
    data = state.get("data", {}) or {}
    scenes = scene_progress(pp, state)
    base.update({
        "topic": (data.get("selected_topic") or data.get("topic")
                  or title_from_script(pp)),
        "current_step": state.get("current_step"),
        "status": state.get("status"),
        "completed_steps": state.get("completed_steps", []),
        "created_at": state.get("created_at"),
        "updated_at": state.get("updated_at"),
        "progress_percent": pipeline_progress(state)["percent"],
        "scenes_completed": scenes["completed"],
        "scenes_total": scenes["total"],
        "final_video_available": final_video_info(pm, project_id, state)["available"],
    })
    from app.dashboard import review as review_mod
    base["review_status"] = review_mod.get_review(pm, project_id)["status"]
    return base


def list_projects(pm: ProjectManager | None = None) -> list:
    pm = pm or ProjectManager()
    return [project_summary(pm, pid) for pid in pm.list_projects()]


def project_detail(pm: ProjectManager | None, project_id: str) -> dict:
    pm = pm or ProjectManager()
    if not is_valid_project_id(project_id):
        raise ValueError("invalid project id")
    if not pm.project_path(project_id).is_dir():
        raise FileNotFoundError("project not found: {}".format(project_id))
    state = load_state_safe(pm, project_id)
    pp = pm.project_path(project_id)
    sel_path = pp / "research" / "selected_topic.json"
    selected_topic = None
    if sel_path.exists():
        try:
            selected_topic = json.loads(sel_path.read_text(encoding="utf-8"))
        except Exception:
            selected_topic = None
    out = {
        "project_id": project_id,
        "state_available": state is not None,
        "state": state,
        "pipeline": pipeline_progress(state) if state
                    else {"steps": [], "completed": 0, "total": len(config.DASH_STEPS),
                          "percent": None},
        "scenes": scene_progress(pp, state),
        "artifacts": artifacts(pm, project_id),
        "final_video": final_video_info(pm, project_id, state),
        "selected_topic": selected_topic,
    }
    from app.dashboard import review as review_mod
    out["review"] = review_mod.get_review(pm, project_id)
    out["seo"] = _seo_info(pp)
    return out


def _seo_info(pp: Path) -> dict | None:
    sp = pp / "research" / "seo.json"
    if not sp.exists():
        return None
    try:
        data = json.loads(sp.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def read_logs(project_id: str | None = None, limit: int = 200,
              level: str | None = None, component: str | None = None) -> list:
    log_path = config.LOG_FILE
    if not log_path.exists():
        return []
    try:
        lines = log_path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    wanted_level = str(level).upper() if level else None
    out = []
    for ln in lines:
        m = LOG_LINE_RE.match(ln)
        if not m:
            continue
        d = m.groupdict()
        if wanted_level and d["level"].upper() != wanted_level:
            continue
        if component and d["component"].upper() != str(component).upper():
            continue
        if project_id:
            if project_id not in ln:
                continue
        out.append({"timestamp": d["ts"], "level": d["level"].upper(),
                    "component": d["component"], "message": d["message"].strip()})
    return out[-int(limit):]


def system_status() -> dict:
    cfg = config.as_dict()
    ollama = {"status": "UNKNOWN"}
    try:
        from app.llm.ollama_client import OllamaClient
        conn = OllamaClient().check_connection()
        ollama = {"status": "ONLINE" if conn.get("ok") else "OFFLINE",
                  "text_model": cfg["OLLAMA_TEXT_MODEL"]}
    except Exception as e:
        ollama = {"status": "OFFLINE", "error": str(e)[:120]}
    pm = ProjectManager()
    states = [load_state_safe(pm, pid) for pid in pm.list_projects()]
    statuses = [s.get("status") for s in states if s]
    return {
        "app": "OK", "ollama": ollama,
        "visual_provider": cfg["VISUAL_PROVIDER"],
        "test_visual_mode": cfg["TEST_VISUAL_MODE"],
        "research_provider": cfg["RESEARCH_PROVIDER"],
        "projects_total": len(states),
        "projects_active": statuses.count("IN_PROGRESS"),
        "projects_completed": statuses.count("COMPLETED"),
        "projects_failed": statuses.count("FAILED"),
    }