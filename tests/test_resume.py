"""Test 5: resume — mark SCRIPT/TTS/BGM completed, MIX failed; pipeline must resume at MIX."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def run() -> bool:
    from app.core import config
    from app.core.project_manager import ProjectManager
    config.ensure_dirs()
    pm = ProjectManager()
    pm.create_project("test_resume")
    sm = pm.state_manager("test_resume")
    sm.create_project("test_resume")
    for s in ("SCRIPT", "TTS", "BGM"):
        sm.mark_started(s)
        sm.mark_completed(s)
    sm.mark_started("MIX")
    sm.mark_failed("MIX", "simulated failure")
    resumed = sm.resume()
    nxt = resumed.get("_next_step")
    ok = nxt == "MIX" and all(s in resumed["completed_steps"] for s in ("SCRIPT", "TTS", "BGM"))
    print(f"RESUME TEST: next={nxt} completed={resumed['completed_steps']} ->",
          "PASS" if ok else "FAIL")
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
