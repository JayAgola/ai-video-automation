"""Part 4 Prompt 1 — Dashboard foundation tests (read-only, no generation)."""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import config
from app.core.project_manager import ProjectManager
from app.dashboard import service as svc
from app.dashboard.api import create_app

ROOT = Path(tempfile.mkdtemp(prefix="dash_test_"))
PROJECTS = ROOT / "projects"
pm = ProjectManager()
pm.projects_dir = PROJECTS  # redirect for the test


def make_project(pid, state=None, script=None, artifacts=()):
    p = PROJECTS / pid
    (p / "audio").mkdir(parents=True, exist_ok=True)
    if state is not None:
        (p / "state.json").write_text(json.dumps(state), encoding="utf-8")
    if script is not None:
        (p / "script.json").write_text(json.dumps(script), encoding="utf-8")
    for a in artifacts:
        f = p / a
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x", encoding="utf-8")
    return p


GOOD_STATE = {
    "project_id": "dash_a", "status": "IN_PROGRESS", "current_step": "MIX",
    "completed_steps": ["RESEARCH", "TOPIC_DISCOVERY", "TOPIC_RANKING",
                        "TOPIC_SELECTED", "SEO_GENERATION", "SCRIPT", "TTS", "BGM"],
    "failed_steps": [], "data": {"review_status": "DRAFT"},
    "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T01:00:00Z",
}
GOOD_SCRIPT = {"title": "Test Video", "scenes": [
    {"scene_id": 1, "narration": "a"}, {"scene_id": 2, "narration": "b"}]}

results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ((" | " + str(extra)[:200]) if extra else ""))


# ---- Test 1: project discovery ----
make_project("dash_a", GOOD_STATE, GOOD_SCRIPT, ("audio/scene_001.mp3",
             "visuals/scene_001.png", "chunks/scene_001.mp4",
             "output/final_video.mp4"))
make_project("dash_b", GOOD_STATE, GOOD_SCRIPT)
(PROJECTS / "dash_corrupt").mkdir(parents=True)
(PROJECTS / "dash_corrupt" / "state.json").write_text("{not json", encoding="utf-8")
(PROJECTS / "dash_empty").mkdir(parents=True)
pids = pm.list_projects()
check("T1 project discovery", set(pids) >= {"dash_a", "dash_b", "dash_corrupt", "dash_empty"}, pids)

# ---- Test 2: summary generation ----
summaries = {s["project_id"]: s for s in svc.list_projects(pm)}
a = summaries["dash_a"]
check("T2a summary fields", a["topic"] == "Test Video" and a["current_step"] == "MIX"
      and a["status"] == "IN_PROGRESS")
check("T2b final video flag", a["final_video_available"] is True)
check("T2c corrupted project tolerated", summaries["dash_corrupt"]["state_available"] is False
      and summaries["dash_empty"]["state_available"] is False)

# ---- Test 3: detail / state loading ----
d = svc.project_detail(pm, "dash_a")
check("T3 detail loads state", d["state_available"] and d["state"]["project_id"] == "dash_a")

# ---- Test 4: pipeline progress ----
pp = d["pipeline"]
check("T4a step order matches DASH_STEPS", [n["step"] for n in pp["steps"]] == config.DASH_STEPS)
statuses = {n["step"]: n["status"] for n in pp["steps"]}
check("T4b statuses", statuses["BGM"] == "completed" and statuses["MIX"] == "running"
      and statuses["VISUAL_GENERATION"] == "pending" and statuses["HUMAN_REVIEW"] == "pending")
check("T4c percent", pp["percent"] == round(100 * 8 / len(config.DASH_STEPS), 1), pp["percent"])

# ---- Test 5: scene progress ----
sc = d["scenes"]
check("T5 scene progress", sc["total"] == 2 and 0 <= sc["completed"] <= 2, sc)

# ---- Test 6: artifact detection ----
arts = d["artifacts"]
check("T6a artifacts", arts["final_video.mp4"]["exists"] is True
      and arts["script.json"]["exists"] is True and arts["audio"]["exists"] is True, arts)
check("T6b final video info", d["final_video"]["available"] is True)

# ---- Test 7: log retrieval (temp log) ----
logs_dir = ROOT / "logs"; logs_dir.mkdir(exist_ok=True)
logf = logs_dir / "pipeline.log"
logf.write_text(
    "2026-01-01T00:00:00Z INFO [PIPELINE] project dash_a step MIX started\n"
    "2026-01-01T00:00:01Z ERROR [MIX] project dash_a boom\n"
    "unparseable line\n", encoding="utf-8")
old_log = config.LOG_FILE
config.LOG_FILE = logf
try:
    logs = svc.read_logs(project_id="dash_a")
    check("T7a log parse/filter", len(logs) == 2 and logs[-1]["level"] == "ERROR", logs)
    check("T7b level filter", len(svc.read_logs(project_id="dash_a", level="error")) == 1)
finally:
    config.LOG_FILE = old_log

# ---- Test 8: malformed / missing state ----
dc = svc.project_detail(pm, "dash_corrupt")
check("T8a corrupt state tolerated", dc["state_available"] is False
      and dc["pipeline"]["percent"] is None)
de = svc.project_detail(pm, "dash_empty")
check("T8b missing state tolerated", de["state_available"] is False)

# ---- Test 9: path traversal protection ----
for bad in ("../../etc", "..\\..\\x", "a/b", ".", "..", "proj id"):
    check("T9 traversal blocked: " + bad, svc.is_valid_project_id(bad) is False)
check("T9 valid id ok", svc.is_valid_project_id("video_001"))

# ---- Test 10: API endpoints ----
from fastapi.testclient import TestClient
app = create_app(static_dir=str(config.DASHBOARD_STATIC_DIR), projects_dir=PROJECTS)
client = TestClient(app)
r = client.get("/api/v1/dashboard/health")
check("T10a health", r.status_code == 200 and r.json()["status"] == "ok")
r = client.get("/api/v1/dashboard/projects")
check("T10b list projects", r.status_code == 200 and r.json()["count"] >= 2)
r = client.get("/api/v1/dashboard/projects/dash_a")
check("T10c project detail", r.status_code == 200 and r.json()["pipeline"]["completed"] == 8)
r = client.get("/api/v1/dashboard/projects/dash_missing")
check("T10d missing project 404", r.status_code == 404)
r = client.get("/api/v1/dashboard/projects/..%2F..%2Fsecrets")
check("T10e traversal via API rejected", r.status_code in (400, 404))
r = client.get("/api/v1/dashboard/projects/dash_corrupt")
check("T10f corrupt project detail OK", r.status_code == 200
      and r.json()["state_available"] is False)
r = client.get("/api/v1/dashboard/projects/dash_a/logs")
check("T10g logs endpoint", r.status_code == 200 and isinstance(r.json()["logs"], list))
r = client.get("/api/v1/dashboard/system")
check("T10h system status", r.status_code == 200 and "visual_provider" in r.json())
r = client.get("/")
check("T10i frontend served", r.status_code == 200 and b"YT001 Dashboard" in r.content)

print("\n{} / {} passed".format(sum(1 for _, ok in results if ok), len(results)))
sys.exit(0 if all(ok for _, ok in results) else 1)

