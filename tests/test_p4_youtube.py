"""Part 4 Prompt 3 — YouTube OAuth + safe upload tests (mock client only, no network)."""
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
from app.youtube import oauth, uploader
from app.youtube.test_client import FakeYouTube

TMP = Path(tempfile.mkdtemp(prefix="p4_yt_"))
PROJECTS = TMP / "projects"
PROJECTS.mkdir(parents=True)
config.TEST_YOUTUBE_MODE = True  # never touch real Google in tests
config.YOUTUBE_UPLOAD_ENABLED = True
failures = []


def check(name, cond, extra=""):
    print(("PASS" if cond else "FAIL"), name, extra)
    if not cond:
        failures.append(name)


def make_project(pid, with_video=True, review_status=None, seo=None):
    pp = PROJECTS / pid
    (pp / "output").mkdir(parents=True, exist_ok=True)
    sm = StateManager(pp / "state.json")
    sm.create_project(pid)
    if review_status:
        state = sm.load()
        state.setdefault("data", {})["review"] = {
            "status": review_status, "reviewer": "local_user", "note": "",
            "history": [{"action": review_status, "reviewer": "local_user", "note": "", "timestamp": "t0"}]}
        sm.save(state)
    if seo is not None:
        (pp / "research").mkdir(exist_ok=True)
        (pp / "research" / "seo.json").write_text(json.dumps(seo), encoding="utf-8")
    if with_video:
        (pp / "output" / "final_video.mp4").write_bytes(b"\x00" * 256)
    return pp


pm = ProjectManager()
pm.projects_dir = PROJECTS

# ---- OAuth tests ----
check("T-O1 test mode authenticated", oauth.status()["authenticated"] is True)
check("T-O2 test mode channel labelled", "TEST" in oauth.status()["channel"]["title"])
check("T-O3 no tokens in status", "access_token" not in json.dumps(oauth.status()))
real_mode = config.TEST_YOUTUBE_MODE
config.TEST_YOUTUBE_MODE = False
config.YOUTUBE_CLIENT_SECRET_FILE = TMP / "missing_secret.json"
config.YOUTUBE_TOKEN_FILE = TMP / "missing_token.json"
check("T-O4 unconfigured -> not authenticated", oauth.get_client() is None)
try:
    oauth.start_auth()
    check("T-O6 start_auth unconfigured raises", False)
except oauth.OAuthError:
    check("T-O6 start_auth unconfigured raises", True)
try:
    oauth.complete_auth("fake_code")
    check("T-O7 complete_auth unconfigured raises", False)
except oauth.OAuthError:
    check("T-O7 complete_auth unconfigured raises", True)
config.TEST_YOUTUBE_MODE = real_mode

# ---- Review gate tests ----
make_project("yt_notready", with_video=False)
make_project("yt_pending", review_status="PENDING")
make_project("yt_rejected", review_status="REJECTED")
make_project("yt_approved", review_status="APPROVED",
             seo={"recommended_title": "Why Your Brain Becomes Louder at Night",
                  "description": "A practical stoic method.",
                  "tags": ["stoicism", "overthinking"], "hashtags": ["#stoicism"]})

for pid in ("yt_notready", "yt_pending", "yt_rejected"):
    try:
        uploader.upload(pm, pid, client=FakeYouTube())
        check("T-G gate blocks " + pid, False)
    except (uploader.UploadBlocked, FileNotFoundError):
        check("T-G gate blocks " + pid, True)

# ---- Successful upload (mock) ----
try:
    res = uploader.upload(pm, "yt_approved", client=FakeYouTube())
    yt = res["youtube"]
    check("T-U1 upload succeeds", yt["status"] == "UPLOADED")
    check("T-U2 video_id stored", yt["video_id"].startswith("TESTVID"))
    check("T-U3 url derived", yt["url"] == "https://www.youtube.com/watch?v=" + yt["video_id"])
    check("T-U4 privacy stored", yt["privacy_status"] == config.YOUTUBE_DEFAULT_PRIVACY)
    check("T-U5 timestamp stored", bool(yt.get("uploaded_at")))
    st = json.loads((PROJECTS / "yt_approved" / "state.json").read_text(encoding="utf-8"))
    blob = json.dumps(st)
    check("T-U6 state updated", st["data"]["youtube"]["status"] == "UPLOADED")
    check("T-U7 no secrets in state", all(s not in blob for s in
          ("access_token", "refresh_token", "client_secret", "authorization_code")))
    meta = res["metadata"]
    check("T-U8 seo title used", meta["title"] == "Why Your Brain Becomes Louder at Night")
    check("T-U9 seo tags used", meta["tags"] == ["stoicism", "overthinking"])
    check("T-U10 private default", meta["privacy_status"] == "private")
except uploader.UploadBlocked as e:
    check("T-U1 upload succeeds", False, str(e))

# ---- Duplicate protection ----
fy = FakeYouTube()
try:
    uploader.upload(pm, "yt_approved", client=fy)
    check("T-D1 duplicate blocked", False)
except uploader.DuplicateUploadError as e:
    check("T-D1 duplicate blocked", True)
    check("T-D2 conflict payload", e.video_id.startswith("TESTVID") and "watch?v=" in e.url)
check("T-D3 api not called again", fy.upload_calls == 0)

# ---- Failure handling ----
make_project("yt_fail", review_status="APPROVED")
try:
    uploader.upload(pm, "yt_fail", client=FakeYouTube(fail_times=uploader.MAX_RETRIES))
    check("T-F1 bounded retries then fail", False)
except uploader.UploadBlocked as e:
    check("T-F1 bounded retries then fail", "attempts" in str(e))
st = json.loads((PROJECTS / "yt_fail" / "state.json").read_text(encoding="utf-8"))
check("T-F2 failure recorded safely", st["data"]["youtube"]["status"] == "FAILED"
      and "token" not in json.dumps(st).lower().replace("tokens", ""))
# transient failure recovers via retry
make_project("yt_retry", review_status="APPROVED")
res = uploader.upload(pm, "yt_retry", client=FakeYouTube(fail_times=1))
check("T-F3 transient retried OK", res["youtube"]["status"] == "UPLOADED")

# ---- Metadata safety ----
make_project("yt_noseo", review_status="APPROVED")
m = uploader.build_metadata(pm, "yt_noseo")
check("T-M1 safe defaults w/o seo", bool(m["title"]) and m["privacy_status"] == "private")
make_project("yt_badseo", review_status="APPROVED",
             seo={"recommended_title": 123, "tags": "not-a-list"})
try:
    m2 = uploader.build_metadata(pm, "yt_badseo")
    check("T-M2 malformed seo handled", m2["title"] == "123" and m2["tags"] == ["not-a-list"])
except Exception:
    check("T-M2 malformed seo handled", False)

# ---- API tests ----
from fastapi.testclient import TestClient
app = create_app(projects_dir=PROJECTS)
c = TestClient(app)

r = c.get("/api/v1/dashboard/youtube/status")
check("T-A1 status 200", r.status_code == 200 and r.json()["authenticated"] is True)
check("T-A2 status sanitized", "token" not in r.text.lower())
r = c.get("/api/v1/dashboard/projects/yt_approved/youtube/preview")
pj = r.json()
check("T-A3 preview 200", r.status_code == 200 and pj["upload_status"] in ("READY", "UPLOADED")
      and pj["review_status"] == "APPROVED")
check("T-A4 preview fields", {"title", "tags", "privacy_status", "video"} <= set(pj))
r = c.get("/api/v1/dashboard/projects/yt_pending/youtube/preview")
pj = r.json()
check("T-A5 preview blocked (not approved)", pj["ready"] is False
      and pj["blocked"] is True and pj["upload_status"] == "BLOCKED_REVIEW")
r = c.get("/api/v1/dashboard/projects/nope/youtube/preview")
check("T-A6 preview 404", r.status_code == 404)
r = c.post("/api/v1/dashboard/projects/yt_pending/youtube/upload", json={"confirm": True})
check("T-A7 upload blocked 403", r.status_code == 403)
r = c.post("/api/v1/dashboard/projects/yt_approved/youtube/upload", json={"confirm": True})
dup_payload = r.json().get("error") or (r.json().get("detail") or {}).get("error")
check("T-A8 already uploaded 409", r.status_code == 409 and dup_payload == "PROJECT_ALREADY_UPLOADED")
r = c.post("/api/v1/dashboard/projects/yt_noseo/youtube/upload", json={"confirm": True})
check("T-A9 upload ok via api", r.status_code == 200
      and r.json()["youtube"]["status"] == "UPLOADED")
r = c.post("/api/v1/dashboard/projects/yt_noseo/youtube/upload", json={})
check("T-A9b no-confirm 422", r.status_code == 422)
r = c.post("/api/v1/dashboard/projects/../../etc/youtube/upload")
check("T-A10 traversal blocked", r.status_code in (400, 404, 422))

# ---- Frontend static checks ----
js = (Path("app/dashboard/static/app.js")).read_text(encoding="utf-8")
html = (Path("app/dashboard/static/index.html")).read_text(encoding="utf-8")
check("T-FE1 youtube section", "YouTube" in js and "renderYoutube" in js)
check("T-FE2 connect button", "Connect YouTube" in js or "connectYouTube" in js)
check("T-FE3 preview shown", "youtube/preview" in js)
check("T-FE4 confirm dialog", "confirm(" in js)
check("T-FE5 esc used for urls", js.count("esc(") >= 10)
check("T-FE6 no token handling", "access_token" not in js and "refresh_token" not in js)

print()
if failures:
    print("FAILURES:", failures)
    sys.exit(1)
print("P4-YOUTUBE: ALL PASS")

