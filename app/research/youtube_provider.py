"""YouTube Data API v3 provider. Quota-aware, never scrapes, never fakes data.

Requires YOUTUBE_API_KEY + YOUTUBE_RESEARCH_ENABLED=true. Without them,
health() reports UNAVAILABLE and search() raises a clear error so the
pipeline can fall back to cache / test mode / manual --topic.
"""
from __future__ import annotations

import datetime
from typing import Any

import requests

from app.core import config


def _redact_error(text: str) -> str:
    low = text.lower()
    if "key=" in low or "apikey" in low.replace("-", "").replace("_", ""):
        return "YouTube API error (credentials redacted)"
    return text[:300]


class YouTubeProvider:
    name = "youtube"
    test_data = False

    def __init__(self, api_key: str = "", enabled: bool = False):
        self.api_key = api_key or config.YOUTUBE_API_KEY
        self.enabled = enabled or config.YOUTUBE_RESEARCH_ENABLED

    def health(self) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "provider": "youtube", "status": "DISABLED",
                    "error": "Set YOUTUBE_API_KEY and YOUTUBE_RESEARCH_ENABLED=true, "
                             "or use RESEARCH_PROVIDER=test / manual --topic."}
        if not self.api_key:
            return {"ok": False, "provider": "youtube", "status": "NO_API_KEY",
                    "error": "YOUTUBE_API_KEY is empty."}
        try:
            r = requests.get("https://www.googleapis.com/youtube/v3/search",
                             params={"part": "snippet", "q": "test",
                                     "type": "video", "maxResults": 1,
                                     "key": self.api_key}, timeout=15)
            if r.status_code == 200:
                return {"ok": True, "provider": "youtube", "status": "AVAILABLE"}
            if r.status_code in (400, 403):
                return {"ok": False, "provider": "youtube", "status": "AUTH_OR_QUOTA",
                        "error": _redact_error(r.text)}
            return {"ok": False, "provider": "youtube", "status": "ERROR",
                    "error": "HTTP {}".format(r.status_code)}
        except Exception as e:
            return {"ok": False, "provider": "youtube", "status": "UNREACHABLE",
                    "error": "{}: {}".format(type(e).__name__, e)}

    def _iso_to_sec(self, iso: str) -> int:
        import re
        m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
        if not m:
            return 0
        h, mi, s = (int(x) if x else 0 for x in m.groups())
        return h * 3600 + mi * 60 + s

    def search(self, query: str, max_results: int = 25, region: str = "US",
               language: str = "en") -> list[dict[str, Any]]:
        h = self.health()
        if not h["ok"]:
            raise RuntimeError("YouTube research unavailable: {}. "
                               "Use cached research or manual --topic.".format(
                                   h.get("error", h.get("status"))))
        try:
            r = requests.get("https://www.googleapis.com/youtube/v3/search",
                             params={"part": "snippet", "q": query, "type": "video",
                                     "maxResults": min(max_results, 50),
                                     "regionCode": region, "relevanceLanguage": language,
                                     "order": "viewCount", "key": self.api_key}, timeout=30)
            r.raise_for_status()
            items = r.json().get("items", [])
        except requests.HTTPError as e:
            raise RuntimeError("YouTube API failure: {}".format(
                _redact_error(str(e)))) from e
        except Exception as e:
            raise RuntimeError("YouTube search failed for {!r}: {}: {}".format(
                query, type(e).__name__, e)) from e
        vids = [it["id"]["videoId"] for it in items if it.get("id", {}).get("videoId")]
        stats: dict[str, dict] = {}
        if vids:
            try:
                s = requests.get("https://www.googleapis.com/youtube/v3/videos",
                                 params={"part": "statistics,contentDetails,snippet",
                                         "id": ",".join(vids[:50]),
                                         "key": self.api_key}, timeout=30)
                s.raise_for_status()
                for v in s.json().get("items", []):
                    stats[v["id"]] = v
            except Exception:
                pass  # snippet data still usable; stats optional
        out = []
        for it in items:
            vid = it.get("id", {}).get("videoId", "")
            sn = it.get("snippet", {})
            st = stats.get(vid, {}).get("statistics", {})
            cd = stats.get(vid, {}).get("contentDetails", {})
            out.append({
                "video_id": vid, "title": sn.get("title", ""),
                "channel_title": sn.get("channelTitle", ""),
                "published_at": sn.get("publishedAt", ""),
                "view_count": int(st.get("viewCount", 0) or 0),
                "like_count": int(st.get("likeCount", 0) or 0),
                "comment_count": int(st.get("commentCount", 0) or 0),
                "duration_sec": self._iso_to_sec(cd.get("duration", "")),
                "channel_subscribers": None, "query": query, "source": "youtube",
                "description_snippet": (sn.get("description", "") or "")[:300],
            })
        _ = datetime.datetime.now()  # touch for future TTL debug
        return out
