"""TEST YOUTUBE MODE — deterministic fake client. NO REAL UPLOAD, NO NETWORK.

Clearly labelled TEST behaviour; used only when config.TEST_YOUTUBE_MODE is true
or when tests inject it directly. Never let this stand in for production uploads.
"""
from __future__ import annotations

import time


class FakeUploadError(Exception):
    """Configurable failure for tests (transient/permanent)."""


class FakeYouTube:
    label = "TEST YOUTUBE MODE — NO REAL UPLOAD"

    def __init__(self, fail_times: int = 0):
        self.fail_times = int(fail_times)  # first N upload attempts fail transiently
        self.upload_calls = 0
        self.last_metadata = None

    def channel_info(self) -> dict:
        return {"id": "TEST_CHANNEL_ID", "title": "TEST YOUTUBE MODE — NO REAL CHANNEL"}

    def upload_video(self, path: str, metadata: dict) -> dict:
        self.upload_calls += 1
        self.last_metadata = metadata
        if self.fail_times > 0:
            self.fail_times -= 1
            raise FakeUploadError("transient test failure")
        vid = "TESTVID{:04d}".format(int(time.time()) % 10000)
        return {"video_id": vid, "url": "https://www.youtube.com/watch?v=" + vid}
