"""Human review workflow (Part 4 Prompt 2).

Extends the existing state.json via StateManager's atomic persistence.
Review model (state["data"]["review"]):
    {"status": NOT_READY|PENDING|APPROVED|REJECTED, "reviewer", "note",
     "created_at", "updated_at", "history": [{action,reviewer,note,timestamp}]}
Rules:
- APPROVED is only ever set by an explicit human action (never automatic).
- Refresh derives PENDING/NOT_READY but never overwrites APPROVED/REJECTED.
- Approval requires the final video to be present and non-empty.
No YouTube/publishing logic lives here.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.core.logger import log
from app.core.project_manager import ProjectManager
from app.core.state_manager import StateManager
from app.dashboard import service as svc

ALLOWED_STATUSES = ("NOT_READY", "PENDING", "APPROVED", "REJECTED")
HISTORY_LIMIT = 100
DEFAULT_REVIEWER = "local_user"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def is_ready_for_review(pm: ProjectManager, project_id: str) -> bool:
    """Final video must exist as a regular, non-empty file."""
    return svc.final_video_info(pm, project_id, None)["available"]


def _load_state(pm: ProjectManager, project_id: str) -> dict | None:
    return svc.load_state_safe(pm, project_id)


def _stored_review(state: dict) -> dict | None:
    data = state.get("data", {}) or {}
    rev = data.get("review")
    return rev if isinstance(rev, dict) else None


def get_review(pm: ProjectManager, project_id: str) -> dict:
    """Derive effective review status. APPROVED/REJECTED are authoritative."""
    state = _load_state(pm, project_id)
    ready = is_ready_for_review(pm, project_id)
    if state is None:
        return {"status": "NOT_READY", "state_available": False, "ready": False,
                "reviewer": None, "note": "", "created_at": None,
                "updated_at": None, "history": []}
    stored = _stored_review(state)
    if stored and stored.get("status") in ("APPROVED", "REJECTED"):
        eff = stored["status"]
    elif stored and stored.get("status") in ALLOWED_STATUSES:
        eff = stored["status"] if ready else "NOT_READY"
        if stored.get("status") == "NOT_READY" and ready:
            eff = "PENDING"
    else:
        eff = "PENDING" if ready else "NOT_READY"
    return {"status": eff, "state_available": True, "ready": ready,
            "reviewer": stored.get("reviewer") if stored else None,
            "note": stored.get("note", "") if stored else "",
            "created_at": stored.get("created_at") if stored else None,
            "updated_at": stored.get("updated_at") if stored else None,
            "history": (stored.get("history", []) if stored else [])}


def _persist(pm: ProjectManager, project_id: str, action: str,
             status: str, note: str, reviewer: str) -> dict:
    """Append history + set review status through StateManager (atomic)."""
    sm = StateManager(pm.project_path(project_id) / "state.json")
    state = sm.load()
    if not state:
        raise ValueError("state unavailable")
    data = state.setdefault("data", {})
    review = data.get("review") if isinstance(data.get("review"), dict) else {}
    ts = _now()
    entry = {"action": action, "reviewer": reviewer, "note": note, "timestamp": ts}
    history = list(review.get("history", []) or []) + [entry]
    review.update({
        "status": status, "reviewer": reviewer, "note": note,
        "created_at": review.get("created_at") or ts,
        "updated_at": ts, "history": history[-HISTORY_LIMIT:],
    })
    data["review"] = review
    sm.save(state)
    log("REVIEW", "Human review {} for project {}".format(action, project_id))
    return review


def _guard_state(pm: ProjectManager, project_id: str) -> None:
    if not svc.is_valid_project_id(project_id):
        raise ValueError("invalid project id")
    if not pm.project_path(project_id).is_dir():
        raise FileNotFoundError("project not found")
    if _load_state(pm, project_id) is None:
        raise ValueError("state unavailable")


def approve(pm: ProjectManager, project_id: str, note: str = "",
            reviewer: str = DEFAULT_REVIEWER) -> dict:
    _guard_state(pm, project_id)
    if not is_ready_for_review(pm, project_id):
        raise PermissionError("final video is not ready for review")
    return _persist(pm, project_id, "APPROVED", "APPROVED", note or "", reviewer)


def reject(pm: ProjectManager, project_id: str, note: str = "",
           reviewer: str = DEFAULT_REVIEWER) -> dict:
    _guard_state(pm, project_id)
    if not is_ready_for_review(pm, project_id):
        raise PermissionError("final video is not ready for review")
    if not (note or "").strip():
        raise ValueError("a rejection note is required")
    return _persist(pm, project_id, "REJECTED", "REJECTED", note.strip(), reviewer)


def is_approved_for_publishing(pm: ProjectManager, project_id: str) -> bool:
    """Authoritative human-approval gate for any future publishing/upload."""
    return get_review(pm, project_id)["status"] == "APPROVED"


def reset(pm: ProjectManager, project_id: str, note: str = "",
          reviewer: str = DEFAULT_REVIEWER) -> dict:
    """APPROVED/REJECTED -> PENDING (pending re-review of a revised version)."""
    _guard_state(pm, project_id)
    current = get_review(pm, project_id)
    if current["status"] not in ("APPROVED", "REJECTED"):
        raise ValueError("reset is only valid from APPROVED or REJECTED")
    if not is_ready_for_review(pm, project_id):
        raise PermissionError("final video is not available")
    return _persist(pm, project_id, "RESET", "PENDING", note or "", reviewer)
