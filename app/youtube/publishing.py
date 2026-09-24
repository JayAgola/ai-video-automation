"""Manual YouTube publishing preparation (Part 4 Prompt 4).

Provides READY_FOR_MANUAL_PUBLISH preparation package that reuses existing SEO
artifacts and project state. Does NOT upload, schedule, or publish automatically.
No OAuth required for the manual workflow.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from app.core import config
from app.core.logger import log
from app.core.project_manager import ProjectManager
from app.core.state_manager import StateManager
from app.dashboard import review
from app.dashboard import service as svc
from app.youtube import uploader

YOUTUBE_STUDIO_URL = "https://studio.youtube.com"

_PUBLISHING_STATUS_NOT_READY = "NOT_READY"
_PUBLISHING_STATUS_READY = "READY_FOR_MANUAL_PUBLISH"
_PUBLISHING_STATUS_CONFIRMED = "MANUAL_UPLOAD_CONFIRMED"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _load_publishing_state(pm: ProjectManager, project_id: str) -> dict:
    """Load the publishing block from state.json."""
    state = svc.load_state_safe(pm, project_id)
    if state is None:
        return {}
    data = state.get("data", {}) or {}
    publishing = data.get("publishing")
    if isinstance(publishing, dict):
        return publishing
    return {}


def _save_publishing_state(pm: ProjectManager, project_id: str, publishing: dict) -> None:
    """Atomically save the publishing block into state.json."""
    sm = StateManager(pm.project_path(project_id) / "state.json")
    state = sm.load()
    if not state:
        raise ValueError("state unavailable")
    data = state.setdefault("data", {})
    data["publishing"] = publishing
    sm.save(state)
    log("PUBLISHING", "Saved publishing state for project {}".format(project_id))


def derive_publishing_status(pm: ProjectManager, project_id: str) -> str:
    """Derive the publishing status from current state."""
    if not svc.is_valid_project_id(project_id):
        return _PUBLISHING_STATUS_NOT_READY
    fv_info = svc.final_video_info(pm, project_id, None)
    if not fv_info["available"]:
        return _PUBLISHING_STATUS_NOT_READY
    if not review.is_approved_for_publishing(pm, project_id):
        return _PUBLISHING_STATUS_NOT_READY
    publishing = _load_publishing_state(pm, project_id)
    if publishing.get("manual_upload_confirmed"):
        return _PUBLISHING_STATUS_CONFIRMED
    return _PUBLISHING_STATUS_READY

