"""Part 2.2 hybrid visual source tests: T1-T18 in this file (offline, no API
calls). T19-T23 are the existing suites run alongside (see final report).
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS: " if cond else "FAIL: ") + name, info)


def base_scene(**over):
    s = {"scene_id": 1,
         "narration": "Practice self-compassion and give yourself permission to make mistakes.",
         "visual_direction": "peaceful adult sitting quietly reflecting in a calm room",
         "estimated_duration_seconds": 7,
         "visual_type": "person", "visual_source_preference": "auto",
         "stock_search_query": "person peaceful reflection",
         "narration_text": "Practice self-compassion and give yourself permission to make mistakes.",
         "visual_prompt": "peaceful adult sitting quietly reflecting in a calm room",
         "caption_text": "Practice self-compassion and give yourself permission to make mistakes."}
    s.update(over)
    return s


class MockStockProvider:
    """Deterministic offline stock source (never touches the network)."""
    kind = "stock"

    def __init__(self, name="mock", fail=False, candidates=None):
        self.name, self.fail = name, fail
        self.candidates = candidates or []
        self.search_calls = 0
        self.fetch_calls = 0

    def health(self):
        return {"ok": not self.fail, "provider": self.name}

    def search(self, query, media_type="photo", count=10, width=1280, height=720,
               settings=None):
        self.search_calls += 1
        if self.fail:
            from app.visuals.stock_providers import StockError
            raise StockError(self.name + ": mock stock failure")
        return list(self.candidates)

    def fetch(self, cand, output_path, width, height, settings=None):
        self.fetch_calls += 1
        from app.visuals.stock_providers import StockError
        if self.fail:
            raise StockError(self.name + ": mock fetch failure")
        dest = Path(output_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if cand.get("media_type") == "video":
            dest.write_bytes(b"FAKE_STOCK_VIDEO_BYTES" * 64)
        else:
            from PIL import Image
            Image.new("RGB", (width, height), (40, 70, 110)).save(str(dest), "PNG")
        return {"path": str(dest), "width": width, "height": height}


class FailingAI:
    name = "failai"

    def health(self):
        return {"ok": False, "provider": self.name}

    def generate_image(self, *a, **k):
        raise RuntimeError("AI provider down")


def good_candidate(provider="mock", asset_id="a1", media_type="photo",
                   w=1920, h=1080, url="https://example.invalid/a1.jpg",
                   tags="person peaceful reflection"):
    from app.visuals.stock_providers import candidate
    return candidate(provider, asset_id, media_type, url, w, h,
                     source_url="https://example.invalid/page", creator="Someone",
                     license_="test-license", query="person peaceful reflection",
                     file_ext=".png", tags=tags)


def run_engine(scene, tmp, mocks, ai=None):
    from app.core.cache_manager import CacheManager
    from app.visuals import visual_engine
    cache = CacheManager(Path(tmp) / "cache")
    return visual_engine.generate_scene_image(
        "test_hybrid", scene, {"visual_style": ""}, Path(tmp) / "visuals",
        cache, ai, 1280, 720, stock_providers=mocks)


def run() -> bool:
    from app.visuals import visual_engine as ve
    from app.visuals import stock_providers as sp

    # T1-T5: deterministic source selection
    check("T1-mode-overrides",
          ve.source_plan(base_scene(), mode="ai") == ["ai"]
          and ve.source_plan(base_scene(), mode="stock") == ["pexels", "pixabay", "ai"]
          and ve.source_plan(base_scene(), mode="local")[0] == "local")
    check("T2-person-stock-first",
          ve.source_plan(base_scene())[0] == "pexels")
    check("T3-landscape-stock-first",
          ve.source_plan(base_scene(visual_type="landscape"))[0] == "pexels")
    check("T4-abstract-ai-first",
          ve.source_plan(base_scene(visual_type="abstract"))[0] == "ai")
    check("T5-fictional-ai-first",
          ve.source_plan(base_scene(visual_type="fictional"))[0] == "ai")

    # T6: stock failure -> AI fallback (all mocks fail, AI = test provider)
    with tempfile.TemporaryDirectory() as td:
        mocks = [MockStockProvider("mock{}".format(i), fail=True) for i in range(3)]
        from app.visuals.test_provider import TestImageProvider
        path, meta, hit = run_engine(base_scene(), td, mocks, TestImageProvider())
        check("T6-stock-fail-ai-fallback",
              Path(path).exists() and meta.get("source") != "stock"
              and meta.get("provider") == "test", Path(path).name)

    # T7: AI failure -> stock fallback (ai-first scene, mock stock succeeds)
    with tempfile.TemporaryDirectory() as td:
        c = good_candidate()
        m_pexels = MockStockProvider("pexels", candidates=[c])
        path, meta, hit = run_engine(base_scene(visual_type="abstract"), td,
                                     [MockStockProvider("local", fail=True), m_pexels,
                                      MockStockProvider("pixabay", fail=True)],
                                     FailingAI())
        check("T7-ai-fail-stock-fallback",
              Path(path).exists() and meta.get("source") == "stock"
              and meta.get("provider") == "pexels" and meta.get("asset_id") == "a1",
              str(meta.get("provider")))

    # T8: no infinite fallback (each source tried at most once, then raises)
    with tempfile.TemporaryDirectory() as td:
        mocks = [MockStockProvider("m{}".format(i), fail=True) for i in range(3)]
        try:
            run_engine(base_scene(), td, mocks, FailingAI())
            raised = False
        except Exception:
            raised = True
        check("T8-no-infinite-fallback",
              raised and all(m.search_calls <= 1 for m in mocks),
              [m.search_calls for m in mocks])

    # T9/T10: API keys never appear in provider error surfaces
    import requests as _requests
    real_get = _requests.get

    def fake_get(url, **kw):
        class R:
            status_code = 401

            def json(self):
                return {}
        return R()

    try:
        _requests.get = fake_get
        h = sp.PexelsProvider("SECRET_PEXELS_KEY_1").health()
        check("T9-pexels-key-never-logged",
              "SECRET_PEXELS_KEY_1" not in json.dumps(h), json.dumps(h)[:80])
        h2 = sp.PixabayProvider("SECRET_PIXABAY_KEY_1").health()
        check("T10-pixabay-key-never-logged",
              "SECRET_PIXABAY_KEY_1" not in json.dumps(h2), json.dumps(h2)[:80])
    finally:
        _requests.get = real_get

    # T11: asset metadata stored (provenance, no secrets)
    with tempfile.TemporaryDirectory() as td:
        path, meta, hit = run_engine(
            base_scene(), td,
            [MockStockProvider("local", fail=True),
             MockStockProvider("pexels", candidates=[good_candidate()]),
             MockStockProvider("pixabay", fail=True)])
        md = meta.get("asset_metadata") or {}
        required = ("provider", "asset_id", "media_type", "source_url", "creator",
                    "query", "license", "downloaded_at", "project_id", "scene_id")
        check("T11-metadata-stored",
              all(k in md for k in required) and md.get("project_id") == "test_hybrid"
              and md.get("scene_id") == 1 and "SECRET" not in json.dumps(meta),
              sorted(md.keys()))

    # T12: cache reuse (no second download/fetch for the same asset)
    with tempfile.TemporaryDirectory() as td:
        m = MockStockProvider("pexels", candidates=[good_candidate()])
        args = (base_scene(), td, [MockStockProvider("local", fail=True), m,
                                   MockStockProvider("pixabay", fail=True)])
        run_engine(*args)
        _, meta2, hit2 = run_engine(*args)
        check("T12-cache-reuse", hit2 is True and m.fetch_calls == 1,
              "fetches={} searches={}".format(m.fetch_calls, m.search_calls))

    # T13: duplicate stock asset avoided (already-used penalty)
    c1 = good_candidate(provider="pexels", asset_id="a1")
    c2 = good_candidate(provider="pexels", asset_id="a2")
    used = {"pexels:a1"}
    best = sp.choose_candidate([c1, c2], 1280, 720, "person peaceful reflection",
                               "photo", used)
    check("T13-duplicate-avoided", best is not None and best.get("asset_id") == "a2",
          str(best and best.get("asset_id")))

    # T14: horizontal / resolution filtering
    check("T14-resolution-filtering",
          not sp.acceptable(good_candidate(asset_id="p", w=720, h=1280), 1280, 720)
          and not sp.acceptable(good_candidate(asset_id="s", w=640, h=360), 1280, 720)
          and sp.acceptable(good_candidate(asset_id="ok", w=1920, h=1080), 1280, 720))

    # T15: SafeSearch enabled + key transport rules
    captured = {}

    def fake_http_json(url, params, headers, provider, secret="", **kw):
        captured["url"], captured["params"], captured["headers"] = (
            url, dict(params), dict(headers))
        return {"hits": [], "photos": []}

    real_http = sp._http_json
    tag = str(int(time.time() * 1000))[-8:]   # unique per run: cached_json must MISS
    try:
        sp._http_json = staticmethod(fake_http_json)
        sp.PixabayProvider("SECRET_PIXABAY_KEY_1")._search_cached(
            "person reflection " + tag, "photo", 5, 1280, 720)
        check("T15-safesearch-pixabay",
              captured["params"].get("safesearch") == "true"
              and "pixabay.com/api/" in captured["url"],
              str(captured.get("params", {}).get("safesearch")))
        sp.PexelsProvider("SECRET_PEXELS_KEY_1")._api(
            {"query": "person reflection " + tag, "per_page": 5}, media="photo")
        check("T15-safesearch-pexels-orientation",
              captured["params"].get("orientation") == "landscape"
              and captured["headers"].get("Authorization") == "SECRET_PEXELS_KEY_1"
              and "SECRET_PEXELS_KEY_1" not in captured["url"],
              str(captured.get("params", {}).get("orientation")))
    finally:
        sp._http_json = real_http

    # T19: Pexels response parsing (official REST shape -> candidates)
    pex = sp.PexelsProvider("deadbeef-key")
    photos_payload = {
        "photos": [
            {"id": 11, "width": 1920, "height": 1280, "url": "https://pexels/page/11",
             "photographer": "Anna Example", "alt": "person peaceful reflection",
             "src": {"original": "https://images.pexels/x.jpg",
                     "large2x": "https://images.pexels/x2.jpg",
                     "large": "https://images.pexels/xl.jpg",
                     "medium": "https://images.pexels/xm.jpg"}},
            {"id": 12, "width": 800, "height": 1200,  # portrait -> filtered out
             "url": "https://pexels/page/12", "photographer": "Bob",
             "alt": "portrait", "src": {"original": "https://images.pexels/y.jpg"}},
            "not-a-dict",
        ],
        "total_results": 2,
    }
    parsed = sp._parse_pexels_response(photos_payload, "photo")
    check("T19-pexels-shape-ok", isinstance(parsed, dict) and isinstance(parsed["photos"], list))
    cands = pex._parse_photos(photos_payload["photos"], "person peaceful reflection")
    check("T19-pexels-photos-parsed",
          len(cands) == 1 and cands[0]["asset_id"] == "11"
          and cands[0]["creator"] == "Anna Example"
          and cands[0]["media_type"] == "photo"
          and cands[0]["download_url"].startswith("https://images.pexels/"),
          str([c.get("asset_id") for c in cands]))
    for bad_payload in (["not", "a", "dict"], {"photos": "not-a-list"}):
        try:
            sp._parse_pexels_response(bad_payload, "photo")
            bad_ok = True
        except sp.StockError:
            bad_ok = False
        check("T19-pexels-malformed-stockerror-" + type(bad_payload).__name__, bad_ok is False)

    # T20: Pexels no-results is a clean empty list, never a crash
    check("T20-pexels-no-results", pex._parse_photos([], "person peaceful reflection") == []
          and sp._parse_pixabay_response({"hits": []}, "photo") == {"hits": []})

    # T21: Pexels API errors (HTTP 4xx/5xx/timeout) -> StockError, key redacted
    class _FakeResp:
        def __init__(self, code):
            self.status_code = code

        def json(self):
            return {}

    import requests as _rq2

    real_rq_get = _rq2.get

    def _boom(url, **kw):
        raise TimeoutError("simulated timeout")

    try:
        _rq2.get = lambda url, **kw: _FakeResp(401)
        try:
            sp._http_json("https://api.pexels.com/v1/search", {}, {}, "pexels", "TOP_SECRET_K")
            err401 = "NO-RAISE"
        except sp.StockError as e:
            err401 = str(e)
        check("T21-pexels-401-stockerror-redacted",
              isinstance(err401, str) and "TOP_SECRET_K" not in err401
              and "authentication" in err401.lower(), err401[:80])
        _rq2.get = lambda url, **kw: _FakeResp(429)
        try:
            sp._http_json("https://api.pexels.com/v1/search", {}, {}, "pexels", "TOP_SECRET_K")
            err429 = "NO-RAISE"
        except sp.StockError as e:
            err429 = str(e)
        check("T21-pexels-429-stop",
              isinstance(err429, str) and "rate limit" in err429.lower(), err429[:80])
        _rq2.get = _boom
        try:
            sp._http_json("https://api.pexels.com/v1/search", {}, {}, "pexels", "TOP_SECRET_K")
            errto = "NO-RAISE"
        except sp.StockError as e:
            errto = str(e)
        check("T21-pexels-timeout-stockerror-redacted",
              isinstance(errto, str) and "TOP_SECRET_K" not in errto, errto[:80])
    finally:
        _rq2.get = real_rq_get

    # T22: corrupted candidate cache (raw dict) recovers instead of AttributeError.
    # The engine's _resolve_stock consults the SHARED cache root, so poison the
    # real skey there with a raw dict; the fixed path must re-search instead.
    import shutil as _sh22
    from app.core import config as _cfg22
    q22 = base_scene()["stock_search_query"]
    skey22 = sp.search_cache_key("pexels", q22, "photo",
                                 _cfg22.STOCK_MAX_RESULTS, 1280, 720,
                                 _cfg22.STOCK_SAFESEARCH)
    from app.core.cache_manager import CacheManager as _CM22
    from app.visuals import visual_engine as _ve22
    shared22 = _CM22(_cfg22.CACHE_DIR)
    poison_path = shared22._path("stock", skey22, ".json")
    backup22 = poison_path.with_suffix(".json.t22bak")
    had22 = poison_path.exists()
    if had22:
        _sh22.copyfile(str(poison_path), str(backup22))
    poison_path.parent.mkdir(parents=True, exist_ok=True)
    poison_path.write_bytes(json.dumps({"photos": [{"id": 1}]}).encode("utf-8"))
    try:
        m22 = MockStockProvider("pexels", candidates=[good_candidate()])
        cands22 = sp.cached_json(skey22, lambda: m22.search(
            q22, "photo", _cfg22.STOCK_MAX_RESULTS, 1280, 720, {}))
        check("T22-corrupt-shape-detected", not isinstance(cands22, list))
        with tempfile.TemporaryDirectory() as td22:
            vis22 = Path(td22) / "visuals"
            vis22.mkdir(parents=True, exist_ok=True)
            cache22 = _CM22(Path(td22) / "cache")
            try:
                got = _ve22._resolve_stock("test_hybrid", base_scene(), vis22, cache22,
                                           m22, 1, 1280, 720, set())
                recovered22 = Path(got[0]).exists()
            except AttributeError:
                recovered22 = False
            except Exception:
                recovered22 = False
            check("T22-corrupt-cache-recovers", recovered22 is True)
    finally:
        try:
            if had22:
                _sh22.copyfile(str(backup22), str(poison_path))
                backup22.unlink()
            elif poison_path.exists():
                poison_path.unlink()
        except OSError:
            pass

    # T23: long-form script duration gate (FIX 5/6 contract)
    from app.script import script_engine as se

    def _long_scene(i, words):
        n = " ".join(["word"] * words)
        return {"scene_id": i, "narration": n, "visual_direction": "calm lake",
                "estimated_duration_seconds": 20,
                "narration_text": n, "visual_prompt": "calm lake", "caption_text": n}

    short_script = {"scenes": [_long_scene(1, 12)]}
    long_script = {"scenes": [_long_scene(i, 55) for i in range(1, 10)]}
    check("T23-short-script-rejected",
          len(se.script_length_issues(short_script)) > 0
          and se.script_estimated_total(short_script) < 180,
          str(se.script_estimated_total(short_script)))
    check("T23-long-script-accepted",
          se.script_length_issues(long_script) == []
          and 180 <= se.script_estimated_total(long_script) <= 300,
          str(se.script_estimated_total(long_script)))

    # T16-T18: caption/query separation preserved through the stock path
    scene = base_scene()
    with tempfile.TemporaryDirectory() as td:
        path, meta, _ = run_engine(
            scene, td, [MockStockProvider("local", fail=True),
                        MockStockProvider("pexels", candidates=[good_candidate()]),
                        MockStockProvider("pixabay", fail=True)])
        cap = scene["caption_text"]
        check("T16-caption-separate",
              meta.get("caption_text") == cap
              and cap not in str(meta.get("visual_prompt")))
        q = ve.scene_stock_query(scene)
        check("T17-stock-query-no-narration",
              scene["narration"] not in q and q == "person peaceful reflection", q)
        from app.visuals.visual_engine import build_prompt
        prompt = build_prompt(scene, {})
        check("T18-visual-prompt-no-caption",
              cap not in prompt and scene["narration"] not in prompt)
    print("HYBRID: {} PASS / {} FAIL".format(len(PASS), len(FAIL)))
    return not FAIL


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)