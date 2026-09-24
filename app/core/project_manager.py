"""Per-video project directories. Never regenerates existing projects."""
from __future__ import annotations

from pathlib import Path

from app.core import config
from app.core.logger import log
from app.core.state_manager import StateManager


class ProjectManager:
    def __init__(self, projects_dir: Path | str | None = None):
        self.projects_dir = Path(projects_dir) if projects_dir else config.PROJECTS_DIR
        self.projects_dir.mkdir(parents=True, exist_ok=True)

    def project_path(self, project_id: str) -> Path:
        return self.projects_dir / project_id

    def state_manager(self, project_id: str) -> StateManager:
        return StateManager(self.project_path(project_id) / "state.json")

    def exists(self, project_id: str) -> bool:
        return (self.project_path(project_id) / "state.json").exists()

    def create_project(self, project_id: str) -> Path:
        """Idempotent: if project exists, return it untouched."""
        p = self.project_path(project_id)
        if self.exists(project_id):
            log("PROJECT", f"Exists, reusing -> {p}")
            return p
        (p / "audio").mkdir(parents=True, exist_ok=True)
        (p / "visuals").mkdir(parents=True, exist_ok=True)
        (p / "chunks").mkdir(parents=True, exist_ok=True)
        (p / "output").mkdir(parents=True, exist_ok=True)
        self.state_manager(project_id).create_project(project_id)
        log("PROJECT", f"Created -> {p}")
        return p

    def load_project(self, project_id: str) -> dict:
        return self.state_manager(project_id).load()

    def list_projects(self) -> list[str]:
        return sorted(p.name for p in self.projects_dir.iterdir() if p.is_dir())

    def status(self, project_id: str) -> str:
        return self.load_project(project_id).get("status", "UNKNOWN")

    def resume_project(self, project_id: str) -> dict:
        return self.state_manager(project_id).resume()

    # Directory helpers (deterministic paths => idempotent)
    def script_path(self, project_id: str) -> Path:
        return self.project_path(project_id) / "script.json"

    def audio_dir(self, project_id: str) -> Path:
        return self.project_path(project_id) / "audio"

    def visuals_dir(self, project_id: str) -> Path:
        return self.project_path(project_id) / "visuals"

    def chunks_dir(self, project_id: str) -> Path:
        return self.project_path(project_id) / "chunks"

    def output_dir(self, project_id: str) -> Path:
        return self.project_path(project_id) / "output"

    def assets_dir(self, project_id: str) -> Path:
        """Per-project local visual assets (Part 2.2 LOCAL source).

        Lazily created only when local assets are actually needed, so existing
        project folders are not restructured.
        """
        return self.project_path(project_id) / "assets"

    def final_video_path(self, project_id: str) -> Path:
        return self.output_dir(project_id) / "final_video.mp4"
