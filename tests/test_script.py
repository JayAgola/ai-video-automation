"""Test 2: script generation -> script.json with required fields."""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def run(topic: str = "How to stop overthinking") -> bool:
    from app.core import config
    from app.core.project_manager import ProjectManager
    from app.llm.ollama_client import OllamaClient
    from app.script import script_engine
    config.ensure_dirs()
    pm = ProjectManager()
    pm.create_project("test_script")
    sm = pm.state_manager("test_script")
    client = OllamaClient()
    try:
        script = script_engine.generate_script(topic, client)
    except Exception as e:
        print("SCRIPT TEST: FAIL:", e)
        return False
    script_engine.save_script(script, pm.script_path("test_script"))
    sm.update({"topic": topic})
    sm.mark_completed("SCRIPT")
    missing = [k for k in ("title", "description", "tags", "target_duration_seconds",
                           "bgm_style", "scenes") if k not in script]
    ok = not missing and len(script["scenes"]) > 0
    print("SCRIPT TEST:", "PASS" if ok else f"FAIL missing={missing}",
          f"scenes={len(script.get('scenes', []))}")
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
