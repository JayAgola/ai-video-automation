"""Quick script test: 3 scenes only (fast on laptop GPU)."""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core import config
from app.core.project_manager import ProjectManager
from app.llm.ollama_client import OllamaClient
from app.script import script_engine

config.ensure_dirs()
pm = ProjectManager()
pm.create_project("test_script_quick")
sm = pm.state_manager("test_script_quick")
client = OllamaClient()
try:
    script = script_engine.generate_script("Why the sky is blue", client,
                                           target_seconds=60, num_scenes=3)
except Exception as e:
    print("QUICK SCRIPT TEST: FAIL:", str(e)[:500])
    raise SystemExit(1)
script_engine.save_script(script, pm.script_path("test_script_quick"))
sm.update({"topic": "Why the sky is blue"})
sm.mark_completed("SCRIPT")
print(f"QUICK SCRIPT TEST: PASS scenes={len(script['scenes'])} "
      f"title={script['title'][:60]}")
