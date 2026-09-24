"""Safe YouTube upload (Part 4 Prompt 3).

Hard rules:
- Upload ONLY when review.is_approved_for_publishing() is True (authoritative gate,
  re-checked here defensively before every upload attempt).
- Final video resolved through ProjectManager only — never a client-provided path.
- Metadata from existing Part 3 SEO artifact (research/seo.json); no second SEO generator.
- Duplicate upload protection: state.data.youtube.status == UPLOADED -> 409, never re-upload.
- Only safe metadata in state.json — never tokens/secrets.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.core import config
from app.core.logger import log
from app.core.project_manager import ProjectManager
from app.core.state_manager import StateManager
from app.dashboard import review
from app.dashboard import service as svc

MAX_RETRIES = 2  # transient failures only; never retry auth/quota/4xx logic errors
ALLOWED_PRIVACY = ("private", "unlisted", "public")
YT_STATUSES = ("NOT_READY", "BLOCKED_REVIEW", "BLOCKED_AUTH", "READY",
               "UPLOADING", "UPLOADED", "FAILED")


class UploadBlocked(Exception):
    """Controlled upload refusal; message is safe to show."""


class DuplicateUploadError(UploadBlocked):
    def __init__(self, video_id: str, url: str):
        super().__init__("PROJECT_ALREADY_UPLOADED")
        self.video_id = video_id
        self.url = url


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_seo(pm: ProjectManager, project_id: str) -> dict:
    """Load existing Part 3 SEO output; tolerant of missing/malformed files."""
    path = pm.project_path(project_id) / "research" / "seo.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as e:
        log("YOUTUBE", "SEO load failed (using safe defaults): {}".format(e))
        return {}


def build_metadata(pm: ProjectManager, project_id: str,
                   privacy_status: str | None = None) -> dict:
    """Build upload metadata from existing SEO artifact with safe defaults."""
    if privacy_status is None:
        privacy_status = config.YOUTUBE_DEFAULT_PRIVACY
    if privacy_status not in ALLOWED_PRIVACY:
        raise ValueError("invalid privacy status")
    seo = load_seo(pm, project_id)
    title = seo.get("recommended_title") or ""
    if not isinstance(title, str):
        title = str(title)
    options = seo.get("title_options") or []
    if not title and options:
        first = options[0]
        title = first.get("title", "") if isinstance(first, dict) else str(first)
    state = svc.load_state_safe(pm, project_id) or {}
    topic = ""
    sel = (state.get("data", {}) or {}).get("selected_topic")
    if isinstance(sel, dict):
        topic = sel.get("topic", "")
    elif isinstance(sel, str):
        topic = sel
    title = (title or topic or "Untitled video").strip()[:100]  # YouTube limit
    description = seo.get("description")
    if not isinstance(description, str):
        description = str(description) if description else ""
    description = description.strip()[:5000]
    raw_tags = seo.get("tags")
    if isinstance(raw_tags, (list, tuple)):
        tags = [str(t) for t in raw_tags if str(t).strip()][:30]
    elif raw_tags:
        tags = [str(raw_tags).strip()][:30]
    else:
        tags = []
    raw_hashes = seo.get("hashtags")
    if isinstance(raw_hashes, (list, tuple)):
        hashtags = [str(h) for h in raw_hashes if str(h).strip()][:15]
    else:
        hashtags = [str(raw_hashes).strip()] if raw_hashes else []
    if hashtags and not description.endswith("\n\n" + " ".join(hashtags)):
        description = (description + "\n\n" + " ".join(hashtags)).strip()
    return {"title": title, "description": description, "tags": tags,
            "privacy_status": privacy_status, "category_id": "27"}


def upload_readiness(pm: ProjectManager, project_id: str) -> dict:
    """Explicit, inspectable upload readiness (does not upload anything)."""
    checks = {
        "project_valid": bool(svc.is_valid_project_id(project_id)),
        "video_ready": bool(svc.final_video_info(pm, project_id, None)["available"]),
        "review_approved": bool(review.is_approved_for_publishing(pm, project_id)),
        "authenticated": False,
        "upload_enabled": config.YOUTUBE_UPLOAD_ENABLED or config.TEST_YOUTUBE_MODE,
        "already_uploaded": False,
    }
    state = svc.load_state_safe(pm, project_id) or {}
    yt = (state.get("data", {}) or {}).get("youtube")
    checks["already_uploaded"] = bool(isinstance(yt, dict) and yt.get("status") == "UPLOADED")
    try:
        from app.youtube import oauth
        checks["authenticated"] = oauth.get_client() is not None
    except Exception:
        checks["authenticated"] = False
    if not checks["project_valid"] or not checks["video_ready"]:
        status = "NOT_READY"
    elif not checks["review_approved"]:
        status = "BLOCKED_REVIEW"
    elif not checks["authenticated"]:
        status = "BLOCKED_AUTH"
    elif checks["already_uploaded"]:
        status = "UPLOADED"
    elif checks["upload_enabled"]:
        status = "READY"
    else:
        status = "BLOCKED_AUTH"
    return {"status": status, "checks": checks}


def _store_result(pm: ProjectManager, project_id: str, payload: dict) -> None:
    sm = StateManager(pm.project_path(project_id) / "state.json")
    state = sm.load()
    if not state:
        raise ValueError("state unavailable")
    data = state.setdefault("data", {})
    yt = data.get("youtube") if isinstance(data.get("youtube"), dict) else {}
    yt.update(payload)
    data["youtube"] = yt
    sm.save(state)


def upload(pm: ProjectManager, project_id: str, client=None,
           privacy_status: str | None = None) -> dict:
    """Perform a safe upload. `client` is injectable for tests (mock provider).

    Enforces: valid id -> video exists -> review APPROVED (authoritative gate) ->
    authenticated -> not already uploaded. Records ONLY safe fields in state.
    """
    if not svc.is_valid_project_id(project_id):
        raise ValueError("invalid project id")
    if not pm.project_path(project_id).is_dir():
        raise FileNotFoundError("project not found")
    if not svc.final_video_info(pm, project_id, None)["available"]:
        raise UploadBlocked("final video missing or empty")
    if not review.is_approved_for_publishing(pm, project_id):
        raise UploadBlocked("review is not APPROVED — upload blocked")
    state = svc.load_state_safe(pm, project_id) or {}
    yt = (state.get("data", {}) or {}).get("youtube") or {}
    if yt.get("status") == "UPLOADED":
        raise DuplicateUploadError(yt.get("video_id", ""), yt.get("url", ""))
    if client is None:
        from app.youtube import oauth
        client = oauth.get_client()
        if client is None:
            raise UploadBlocked("YouTube not authenticated")
    metadata = build_metadata(pm, project_id, privacy_status)
    if not metadata["title"].strip():
        raise UploadBlocked("upload metadata invalid: empty title")
    _store_result(pm, project_id, {"status": "UPLOADING",
                                   "privacy_status": metadata["privacy_status"],
                                   "updated_at": _now()})
    video_path = str(pm.project_path(project_id) / "output" / "final_video.mp4")
    log("YOUTUBE", "Upload started for project {} (privacy={}, test_client={})".format(
        project_id, metadata["privacy_status"], config.TEST_YOUTUBE_MODE))
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = client.upload_video(video_path, metadata)
            break
        except Exception as e:
            last_err = e
            log("YOUTUBE", "Upload attempt {}/{} failed: {}".format(attempt, MAX_RETRIES, e))
    else:
        _store_result(pm, project_id, {"status": "FAILED",
                                       "error": str(last_err)[:200], "updated_at": _now()})
        log("YOUTUBE", "Upload failed for project {}".format(project_id))
        raise UploadBlocked("upload failed after {} attempts: {}".format(MAX_RETRIES, last_err))
    video_id = str(result.get("video_id", ""))
    payload = {
        "status": "UPLOADED",
        "video_id": video_id,
        "url": "https://www.youtube.com/watch?v={}".format(video_id),
        "privacy_status": metadata["privacy_status"],
        "title": metadata["title"],
        "uploaded_at": _now(),
        "error": "",
    }
    _store_result(pm, project_id, payload)
    log("YOUTUBE", "Upload completed for project {} video_id={}".format(project_id, video_id))
    return {"project_id": project_id, "youtube": payload, "metadata": metadata}

