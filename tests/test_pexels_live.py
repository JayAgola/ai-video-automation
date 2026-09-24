"""FIX 3 — Pexels runtime verification (runs ONLY with a configured PEXELS_API_KEY).

Verifies the real provider path end-to-end:
1. API key exists (else SKIP, never fail)
2. request succeeds
3. response contains photos
4. selected result has an asset URL
5. asset can be downloaded
6. downloaded file is a valid image
7. provenance metadata contains provider/asset_id/media_type/source_url/
   creator/query/license/downloaded_at/project_id/scene_id (and no secret)
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def run() -> bool:
    from dotenv import load_dotenv

    load_dotenv()
    from app.core import config
    from app.visuals import stock_providers as sp

    if not (config.PEXELS_API_KEY or "").strip():
        print("PEXELS-LIVE: SKIP (PEXELS_API_KEY not configured)")
        return True
    key = config.PEXELS_API_KEY.strip()
    provider = sp.PexelsProvider()
    query = "person peaceful reflection"

    # 1-2. live search
    cands = provider.search(query, "photo", 5, 1280, 720, {})
    if not cands:
        print("PEXELS-LIVE: FAIL (zero candidates for '{}')".format(query))
        return False
    print("PEXELS-LIVE: PASS 1-3 (key ok, request ok, {} photos)".format(len(cands)))

    # 4. asset URL present + landscape
    best = sp.choose_candidate(cands, 1280, 720, query, "photo", set())
    assert best is not None, "no acceptable candidate"
    assert str(best.get("download_url", "")).startswith("http"), best.get("download_url")
    assert sp.acceptable(best, 1280, 720, "photo"), "best candidate fails filters"
    print("PEXELS-LIVE: PASS 4 (asset {} url ok)".format(best.get("asset_id")))

    # 5-6. download + valid image file (PNG fetch normalizes through Pillow).
    # NOTE: Pexels photos land at scene_001.png (dest) after normalization;
    # the .jpg tmp is removed. resolved path comes from fetch's return value.
    with tempfile.TemporaryDirectory() as td:
        dest = Path(td) / "scene_001.png"
        got = provider.fetch(best, dest, 1280, 720, {"project_id": "pexels_live", "scene_id": 1})
        got_path = Path(got.get("path", str(dest)))
        listing = sorted(p.name for p in Path(td).glob("*"))
        dest = got_path if got_path.exists() else dest
        assert dest.exists() and dest.stat().st_size > 0, \
            "empty download (returned={}, dir={})".format(got_path, listing)
        from PIL import Image

        with Image.open(str(dest)) as im:
            im.verify()
            fmt, size_xy = im.format, im.size
        size = dest.stat().st_size
    print("PEXELS-LIVE: PASS 5-6 (downloaded {} bytes, {} {} valid)".format(size, fmt, size_xy))

    # 7. provenance metadata complete, secret-free
    md = sp.base_metadata("pexels", best, "pexels_live", 1, query, "photo")
    required = ("provider", "asset_id", "media_type", "source_url", "creator",
                "query", "license", "downloaded_at", "project_id", "scene_id")
    missing = [k for k in required if k not in md]
    assert not missing, "metadata missing: {}".format(missing)
    assert key not in json.dumps(md), "secret leaked into metadata"
    print("PEXELS-LIVE: PASS 7 (metadata {})".format(sorted(md.keys())))
    print("PEXELS-LIVE: ALL PASS")
    return True


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
