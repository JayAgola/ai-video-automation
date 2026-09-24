"""FastAPI app + dashboard API routes (read-only, lightweight, no generation)."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core import config
from app.dashboard import service as svc
from app.dashboard import review as review_mod
from app.core.project_manager import ProjectManager


def create_app(static_dir: str | None = None, projects_dir=None) -> FastAPI:
    app = FastAPI(title="YT001 Dashboard", version="0.4.0")
    static_dir = static_dir or str(config.DASHBOARD_STATIC_DIR)
    pm = ProjectManager()
    if projects_dir is not None:
        pm.projects_dir = projects_dir

    def _require_project(project_id: str):
        if not svc.is_valid_project_id(project_id):
            raise HTTPException(400, "invalid project id")
        if not pm.project_path(project_id).is_dir():
            raise HTTPException(404, "project not found")
        return project_id

    @app.get("/api/v1/dashboard/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/v1/dashboard/projects")
    def list_projects():
        projects = svc.list_projects(pm)
        return {"projects": projects, "count": len(projects)}

    @app.get("/api/v1/dashboard/projects/{project_id}")
    def project_detail(project_id: str):
        _require_project(project_id)
        try:
            return svc.project_detail(pm, project_id)
        except FileNotFoundError:
            raise HTTPException(404, "project not found")
        except ValueError:
            raise HTTPException(400, "invalid project id")

    @app.get("/api/v1/dashboard/projects/{project_id}/logs")
    def project_logs(project_id: str,
                     limit: int = Query(200, ge=1, le=2000),
                     level: str = Query(None, pattern="(?i)^(INFO|WARNING|ERROR|DEBUG)$"),
                     component: str = Query(None)):
        _require_project(project_id)
        return {"logs": svc.read_logs(project_id=project_id, limit=limit,
                                      level=level, component=component)}

    @app.get("/api/v1/dashboard/system")
    def system_status():
        return svc.system_status()

    # ---- Human review (Part 4 Prompt 2) ----
    def _guard_review(project_id: str):
        _require_project(project_id)
        state = svc.load_state_safe(pm, project_id)
        if state is None:
            raise HTTPException(409, "state unavailable")
        return state

    @app.post("/api/v1/dashboard/projects/{project_id}/review/approve")
    async def review_approve(project_id: str, body: dict = None):
        _guard_review(project_id)
        note = (body or {}).get("note", "") if isinstance(body, dict) else ""
        try:
            review = review_mod.approve(pm, project_id, note=str(note or ""))
        except PermissionError as e:
            raise HTTPException(409, str(e))
        return {"project_id": project_id, "review": review}

    @app.post("/api/v1/dashboard/projects/{project_id}/review/reject")
    async def review_reject(project_id: str, body: dict = None):
        _guard_review(project_id)
        note = (body or {}).get("note", "") if isinstance(body, dict) else ""
        try:
            review = review_mod.reject(pm, project_id, note=str(note or ""))
        except ValueError as e:
            raise HTTPException(422, str(e))
        except PermissionError as e:
            raise HTTPException(409, str(e))
        return {"project_id": project_id, "review": review}

    @app.post("/api/v1/dashboard/projects/{project_id}/review/reset")
    async def review_reset(project_id: str, body: dict = None):
        _guard_review(project_id)
        note = (body or {}).get("note", "") if isinstance(body, dict) else ""
        try:
            review = review_mod.reset(pm, project_id, note=str(note or ""))
        except ValueError as e:
            raise HTTPException(409, str(e))
        except PermissionError as e:
            raise HTTPException(409, str(e))
        return {"project_id": project_id, "review": review}

    @app.get("/api/v1/dashboard/projects/{project_id}/video")
    def project_video(project_id: str):
        _require_project(project_id)
        path = pm.project_path(project_id) / "output" / "final_video.mp4"
        if not (path.exists() and path.is_file() and path.stat().st_size > 0):
            raise HTTPException(404, "final video not available")
        # FileResponse supports HTTP range requests (browser video seeking).
        return FileResponse(str(path), media_type="video/mp4",
                            filename="final_video.mp4")

    # ---- YouTube OAuth + safe upload (Part 4 Prompt 3) ----
    @app.get("/api/v1/dashboard/youtube/status")
    def youtube_status():
        from app.youtube import oauth
        try:
            return oauth.status()
        except Exception as e:
            return {"configured": False, "authenticated": False, "channel": None,
                    "error": str(e)[:200]}

    @app.get("/api/v1/dashboard/youtube/auth_url")
    def youtube_auth_url():
        from app.youtube import oauth, OAuthError
        try:
            return {"url": oauth.start_auth()}
        except OAuthError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/v1/dashboard/youtube/callback")
    def youtube_callback(code: str = Query(None)):
        from app.youtube import oauth, OAuthError
        if not code:
            raise HTTPException(422, "missing authorization code")
        try:
            return oauth.complete_auth(code)
        except OAuthError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/v1/dashboard/projects/{project_id}/youtube/preview")
    def youtube_preview(project_id: str, privacy: str = Query(None)):
        from app.youtube import uploader
        _require_project(project_id)
        state = svc.load_state_safe(pm, project_id)
        if state is None:
            raise HTTPException(409, "state unavailable")
        readiness = uploader.upload_readiness(pm, project_id)
        try:
            metadata = uploader.build_metadata(pm, project_id, privacy)
        except ValueError as e:
            raise HTTPException(422, str(e))
        video = svc.final_video_info(pm, project_id, None)
        return {
            "project_id": project_id,
            "ready": readiness["status"] == "READY",
            "upload_status": readiness["status"],
            "checks": readiness["checks"],
            "review_status": review_mod.get_review(pm, project_id)["status"],
            "blocked": readiness["status"] not in ("READY", "UPLOADED"),
            "title": metadata["title"],
            "description": metadata["description"],
            "tags": metadata["tags"],
            "privacy_status": metadata["privacy_status"],
            "video": {"filename": "final_video.mp4", "size": video.get("size_bytes"),
                      "duration": video.get("duration")},
            "existing": (state.get("data", {}) or {}).get("youtube"),
        }

    @app.post("/api/v1/dashboard/projects/{project_id}/youtube/upload")
    async def youtube_upload(project_id: str, body: dict = None):
        from app.youtube import uploader, UploadBlocked, DuplicateUploadError
        _require_project(project_id)
        body = body if isinstance(body, dict) else {}
        confirm = body.get("confirm") is True
        if not confirm:
            raise HTTPException(422, "upload requires explicit confirm=true")
        if svc.load_state_safe(pm, project_id) is None:
            raise HTTPException(409, "state unavailable")
        try:
            return uploader.upload(pm, project_id,
                                   privacy_status=body.get("privacy_status"))
        except DuplicateUploadError as e:
            raise HTTPException(409, {"error": "PROJECT_ALREADY_UPLOADED",
                                      "video_id": e.video_id, "url": e.url})
        except UploadBlocked as e:
            raise HTTPException(403, str(e))
        except FileNotFoundError:
            raise HTTPException(404, "project not found")
        except ValueError as e:
            raise HTTPException(422, str(e))

    # Frontend static files (root).
    @app.get("/")
    def index():
        return FileResponse(str(static_dir) + "/index.html")

    return app


app = create_app()