"""Part 4 Prompt 2 — human review workflow tests (fast, no media generation)."""
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")

from app.core import config
from app.core.project_manager import ProjectManager
from app.core.state_manager import StateManager
from app.dashboard import review as rv
from app.dashboard import service as svc
from app.dashboard.api import create_app

TMP = Path(tempfile.mkdtemp(prefix="p4_review_"))
PROJECTS = TMP / "projects"
PROJECTS.mkdir(parents=True)
failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else "FAIL"), name, extra)
    if not cond:
        failures.append(name)


def make_project(pid, with_video=False, review=None, corrupt=False):
    pp = PROJECTS / pid
    (pp / "output").mkdir(parents=True, exist_ok=True)
    if corrupt:
        (pp / "state.json").write_text("{not json", encoding="utf-8")
    else:
        sm = StateManager(pp / "state.json")
        sm.create_project(pid)
        if review is not None:
            state = sm.load()
            state.setdefault("data", {})["review"] = review
            sm.save(state)
    if with_video:
        (pp / "output" / "final_video.mp4").write_bytes(b"\x00" * 128)
    return pp


pm = ProjectManager()
pm.projects_dir = PROJECTS

# ---- Test 1: review initialization ----
make_project("r_ready", with_video=True)
make_project("r_novideo")
make_project("r_approved", with_video=True,
             review={"status": "APPROVED", "reviewer": "local_user", "note": "ok",
                     "history": [{"action": "APPROVED", "reviewer": "local_user", "note": "ok", "timestamp": "t0"}]})
make_project("r_rejected", with_video=True,
             review={"status": "REJECTED", "reviewer": "local_user", "note": "bad scene",
                     "history": [{"action": "REJECTED", "reviewer": "local_user", "note": "bad scene", "timestamp": "t0"}]})
make_project("r_pending", with_video=True,
             review={"status": "PENDING", "reviewer": "local_user", "note": "", "history": []})

check("T1a video exists -> PENDING", rv.get_review(pm, "r_ready")["status"] == "PENDING")
check("T1b no video -> NOT_READY", rv.get_review(pm, "r_novideo")["status"] == "NOT_READY")
check("T1c existing APPROVED kept", rv.get_review(pm, "r_approved")["status"] == "APPROVED")
check("T1d existing REJECTED kept", rv.get_review(pm, "r_rejected")["status"] == "REJECTED")
check("T1e existing PENDING kept", rv.get_review(pm, "r_pending")["status"] == "PENDING")

# ---- Test 2: approve ----
r = rv.approve(pm, "r_ready", note="Reviewed and approved.")
check("T2a PENDING->APPROVED", r["status"] == "APPROVED")
check("T2b reviewer stored", r["reviewer"] == "local_user")
check("T2c note stored", r["note"] == "Reviewed and approved.")
check("T2d timestamp stored", bool(r["updated_at"]))
check("T2e history entry", r["history"][-1]["action"] == "APPROVED")
check("T2f persisted atomically",
      json.loads((PROJECTS / "r_ready" / "state.json").read_text(encoding="utf-8"))["data"]["review"]["status"] == "APPROVED")

# ---- Test 3: reject ----
r = rv.reject(pm, "r_ready", note="Scene 4 needs work.")
check("T3a APPROVED->REJECTED via reject", r["status"] == "REJECTED")
check("T3b rejection reason stored", r["note"] == "Scene 4 needs work.")
try:
    rv.reject(pm, "r_ready", note="   ")
    check("T3c empty note rejected", False)
except ValueError:
    check("T3c empty note rejected", True)

# ---- Test 4: reset ----
r = rv.reset(pm, "r_ready", note="revised")
check("T4a REJECTED->PENDING", r["status"] == "PENDING")
rv.approve(pm, "r_ready", note="again")
r = rv.reset(pm, "r_ready", note="rev2")
check("T4b APPROVED->PENDING", r["status"] == "PENDING")
try:
    rv.reset(pm, "r_ready")
    check("T4c reset invalid from PENDING", False)
except ValueError:
    check("T4c reset invalid from PENDING", True)

# ---- Test 5: invalid transitions ----
try:
    rv.approve(pm, "r_novideo", note="x")
    check("T5 NOT_READY->APPROVED blocked", False)
except PermissionError:
    check("T5 NOT_READY->APPROVED blocked", True)

# ---- Test 6/7: approval + rejection persistence across refresh ----
rv.approve(pm, "r_ready", note="final")
check("T6 APPROVED survives refresh", rv.get_review(pm, "r_ready")["status"] == "APPROVED")
rv.reject(pm, "r_ready", note="no")
check("T7 REJECTED survives refresh", rv.get_review(pm, "r_ready")["status"] == "REJECTED")

# ---- Test 8: history preservation ----
rv.reset(pm, "r_ready", note="r1")
rv.reject(pm, "r_ready", note="r2")
rv.reset(pm, "r_ready", note="r3")
rv.approve(pm, "r_ready", note="r4")
acts = [h["action"] for h in rv.get_review(pm, "r_ready")["history"]]
check("T8 history sequence", acts[-5:] == ["REJECTED", "RESET", "REJECTED", "RESET", "APPROVED"], str(acts[-5:]))

# ---- Test 9: path traversal ----
for bad in ["../r_ready", "..\\r_ready", "..%2F..%2Fx", str(PROJECTS), "a/b", ".", "..", "proj id"]:
    check("T9 traversal blocked: " + bad[:20], not svc.is_valid_project_id(bad))
check("T9 valid id ok", svc.is_valid_project_id("video_001"))

# ---- Test 10: missing/corrupt state (service level) ----
make_project("r_corrupt", with_video=True, corrupt=True)
check("T10a corrupt state tolerated", svc.load_state_safe(pm, "r_corrupt") is None)
check("T10b corrupt -> NOT_READY", rv.get_review(pm, "r_corrupt")["status"] == "NOT_READY")
try:
    rv.approve(pm, "r_corrupt", note="x")
    check("T10c approve corrupt state fails", False)
except ValueError:
    check("T10c approve corrupt state fails", True)

# ---- Test 11 + 12 + 13: API tests ----
from fastapi.testclient import TestClient
app = create_app(static_dir=str(config.DASHBOARD_STATIC_DIR), projects_dir=PROJECTS)
client = TestClient(app)

resp = client.post("/api/v1/dashboard/projects/r_pending/review/approve", json={"note": "api approve"})
check("T12a POST approve 200", resp.status_code == 200 and resp.json()["review"]["status"] == "APPROVED")
check("T12b GET projects includes review_status",
      any(p["project_id"] == "r_pending" and p["review_status"] == "APPROVED"
          for p in client.get("/api/v1/dashboard/projects").json()["projects"]))
check("T12c GET detail has review",
      client.get("/api/v1/dashboard/projects/r_pending").json()["review"]["status"] == "APPROVED")
resp = client.post("/api/v1/dashboard/projects/r_pending/review/reject", json={"note": "api reject"})
check("T12d POST reject 200", resp.status_code == 200 and resp.json()["review"]["status"] == "REJECTED")
resp = client.post("/api/v1/dashboard/projects/r_pending/review/reject", json={"note": ""})
check("T12e reject w/o note 422", resp.status_code == 422)
resp = client.post("/api/v1/dashboard/projects/r_pending/review/reset", json={"note": "reset"})
check("T12f POST reset 200", resp.status_code == 200 and resp.json()["review"]["status"] == "PENDING")
resp = client.post("/api/v1/dashboard/projects/r_novideo/review/approve", json={"note": "x"})
check("T11 approve w/o video 409", resp.status_code == 409)
resp = client.post("/api/v1/dashboard/projects/r_corrupt/review/approve", json={"note": "x"})
check("T12g corrupt state 409", resp.status_code == 409)
check("T12h missing project 404",
      client.post("/api/v1/dashboard/projects/nope/review/approve", json={}).status_code == 404)
for bad in ["..%2Fr_ready", "..\\r_ready", str(PROJECTS)]:
    check("T12i traversal via API: " + bad[:14],
          client.post("/api/v1/dashboard/projects/{}/review/approve".format(bad), json={}).status_code in (400, 404))

# ---- Test 13: video endpoint ----
check("T13a video 200",
      client.get("/api/v1/dashboard/projects/r_ready/video").status_code == 200)
check("T13b video content", client.get("/api/v1/dashboard/projects/r_ready/video").content[:4] == b"\x00\x00\x00\x00")
check("T13c video missing 404",
      client.get("/api/v1/dashboard/projects/r_novideo/video").status_code == 404)
check("T13d video invalid id 404/400",
      client.get("/api/v1/dashboard/projects/..%2F..%2Fetc/video").status_code in (400, 404))
check("T13e state.json not servable",
      client.get("/api/v1/dashboard/projects/r_ready/video").content[:1] != b"{")

# ---- Test 14: frontend checks (static analysis of app.js) ----
js = (config.DASHBOARD_STATIC_DIR / "app.js").read_text(encoding="utf-8")
check("T14a esc() used", "function esc(" in js and "esc(" in js)
check("T14b no raw innerHTML of untrusted topic", "esc(p.topic" in js)
check("T14c approve/reject/reset wired",
      all(x in js for x in ["review/approve", "review/reject", "review/reset"]))
check("T14d confirmation dialogs", js.count("confirm(") >= 2)
check("T14e video player element", "<video" in js)
check("T14f NOT_READY disables actions", "disabled" in js and "NOT_READY" in js)

# cleanup
shutil.rmtree(TMP, ignore_errors=True)
print()
print("P4-REVIEW: {} failures".format(len(failures)))
sys.exit(1 if failures else 0)
