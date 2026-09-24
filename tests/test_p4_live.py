"""Lightweight live-server E2E: real uvicorn + HTTP (no AI generation)."""
import io
import sys
import threading
import time
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")

import uvicorn
from app.dashboard.api import create_app

PORT = 8123
config_kwargs = dict(host="127.0.0.1", port=PORT, log_level="error")
server = uvicorn.Server(uvicorn.Config(create_app(), **config_kwargs))
t = threading.Thread(target=server.run, daemon=True)
t.start()
for _ in range(50):
    if server.started:
        break
    time.sleep(0.2)
assert server.started, "server failed to start"

results = []


def get(path, expect=200, contains=None):
    ok = False
    body = b""
    try:
        with urllib.request.urlopen("http://127.0.0.1:{}/{}".format(PORT, path), timeout=10) as r:
            body = r.read()
            ok = r.status == expect and (contains is None or contains in body)
    except urllib.error.HTTPError as e:
        body = str(e).encode()
        ok = e.code == expect
    except Exception as e:
        body = str(e).encode()
    results.append(ok)
    print(("PASS" if ok else "FAIL"), path, ("" if ok else body[:200]))


get("api/v1/dashboard/health", contains=b"ok")
get("api/v1/dashboard/projects")
pid = sorted(p.name for p in __import__("pathlib").Path("projects").iterdir() if p.is_dir())[0]
get("api/v1/dashboard/projects/" + pid)
get("api/v1/dashboard/projects/{}/logs".format(pid))
get("api/v1/dashboard/projects/no_such_project", expect=404)
get("api/v1/dashboard/projects/..%2F..%2Fetc", expect=404)
get("api/v1/dashboard/system", contains=b"visual_provider")
get("", contains=b"YT001 Dashboard")

server.should_exit = True
t.join(timeout=10)
print("LIVE E2E: {} / {}".format(sum(results), len(results)))
sys.exit(0 if all(results) else 1)
