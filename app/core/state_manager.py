"""Crash-safe persistent state management (atomic writes)."""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.logger import log


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

DEFAULT_STATE = {
    "project_id": "",
    "status": "IN_PROGRESS",  # IN_PROGRESS | COMPLETED | FAILED
    "current_step": "",
    "completed_steps": [],
    "failed_steps": [],
    "data": {},
    "created_at": "",
    "updated_at": "",
}


class StateManager:
    def __init__(self, state_path: Path | str):
        self.state_path = Path(state_path)

    # ---- IO ----
    def _atomic_write(self, state: dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".tmp", dir=str(self.state_path.parent),
                delete=False, encoding="utf-8",
            ) as f:
                tmp = f.name
                json.dump(state, f, indent=2, ensure_ascii=False)
            # Never destroy previous valid state: validate tmp then replace.
            json.loads(Path(tmp).read_text(encoding="utf-8"))
            Path(tmp).replace(self.state_path)
        finally:
            try:
                if tmp and Path(tmp).exists() and Path(tmp) != self.state_path:
                    Path(tmp).unlink()
            except OSError:
                pass
        log("STATE", f"Saved -> {self.state_path}")

    def create_project(self, project_id: str) -> dict:
        state = dict(DEFAULT_STATE)
        state.update({
            "project_id": project_id,
            "status": "IN_PROGRESS",
            "current_step": "",
            "completed_steps": [],
            "failed_steps": [],
            "data": {},
            "created_at": _now(),
            "updated_at": _now(),
        })
        self._atomic_write(state)
        return state

    def load(self) -> dict:
        if not self.state_path.exists():
            raise FileNotFoundError(f"state.json not found: {self.state_path}")
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def save(self, state: dict) -> dict:
        state["updated_at"] = _now()
        self._atomic_write(state)
        return state

    def update(self, updates: dict[str, Any]) -> dict:
        state = self.load()
        state["data"] = state.get("data", {})
        for k, v in updates.items():
            state["data"][k] = v
        return self.save(state)

    # ---- steps ----
    def mark_started(self, step: str) -> dict:
        state = self.load()
        state["current_step"] = step
        state["status"] = "IN_PROGRESS"
        return self.save(state)

    def mark_completed(self, step: str) -> dict:
        state = self.load()
        completed = state.setdefault("completed_steps", [])
        if step not in completed:
            completed.append(step)
        failed = state.setdefault("failed_steps", [])
        if step in failed:
            failed.remove(step)
        state["current_step"] = step
        if self._is_all_done(completed):
            state["status"] = "COMPLETED"
        return self.save(state)

    def mark_failed(self, step: str, error: str = "") -> dict:
        state = self.load()
        failed = state.setdefault("failed_steps", [])
        if step not in failed:
            failed.append(step)
        state["current_step"] = step
        state["status"] = "FAILED"
        if error:
            data = state.setdefault("data", {})
            data[f"last_error_{step}"] = error[:2000]
        return self.save(state)

    @staticmethod
    def _is_part1_done(completed: list) -> bool:
        from app.core import config
        return all(s in completed for s in config.PART1_STEPS)

    @staticmethod
    def _is_all_done(completed: list) -> bool:
        """COMPLETED when the media pipeline is done.

        Part 3 RESEARCH/SEO steps are intentionally NOT required for COMPLETED:
        manual --topic mode skips research, and legacy Part 1/2 states must
        never be downgraded. Research completion is tracked via its own
        completed_steps entries, not the top-level status.
        """
        from app.core import config
        steps = getattr(config, "FULL_STEPS", config.PART1_STEPS)
        return all(s in completed for s in steps)

    def next_incomplete_step(self, ordered_steps: list[str] | None = None) -> str | None:
        from app.core import config
        steps = ordered_steps or getattr(config, "FULL_STEPS", config.PART1_STEPS)
        state = self.load()
        completed = set(state.get("completed_steps", []))
        for s in steps:
            if s not in completed:
                return s
        return None

    def resume(self) -> dict:
        """Return state + next step; never resets completed work."""
        state = self.load()
        nxt = self.next_incomplete_step()
        state["_next_step"] = nxt
        return state
