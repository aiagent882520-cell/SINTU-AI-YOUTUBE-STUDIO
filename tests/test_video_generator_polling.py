import json
from contextlib import contextmanager

import pytest

from app import video_generator


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit=-1):
        return self.body if limit < 0 else self.body[:limit]


def test_download_video_file_waits_for_active_then_downloads(monkeypatch):
    calls = []
    def fake_urlopen(request, timeout):
        calls.append((request.full_url, timeout))
        if ":download?" not in request.full_url:
            return FakeResponse(json.dumps({"state": "ACTIVE"}).encode())
        return FakeResponse(b"verified-mp4-bytes")

    monkeypatch.setattr(video_generator.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(video_generator, "_validate_video", lambda raw: raw)
    result = video_generator._download_video_file("file_123", "test-key")
    assert result == b"verified-mp4-bytes"
    assert len(calls) == 2
    assert all(timeout <= 30 for _, timeout in calls)
    assert calls[0][0].endswith("/files/file_123")
    assert calls[1][0].endswith("/files/file_123:download?alt=media")


def test_download_video_file_enforces_ten_minute_processing_deadline(monkeypatch):
    clock = {"now": 0.0}
    calls = {"status": 0}
    def fake_urlopen(request, timeout):
        calls["status"] += 1
        assert timeout <= 30
        return FakeResponse(b'{"state":"PROCESSING"}')

    def fake_sleep(seconds):
        clock["now"] += seconds

    monkeypatch.setattr(video_generator.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(video_generator.time, "sleep", fake_sleep)
    monkeypatch.setattr(video_generator.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(video_generator.VideoGenerationFailed, match="10 minutes"):
        video_generator._download_video_file("file_123", "test-key")
    assert clock["now"] == 600
    assert calls["status"] == 120


def test_download_video_file_stops_immediately_when_provider_fails(monkeypatch):
    calls = {"status": 0}
    def fake_urlopen(request, timeout):
        calls["status"] += 1
        return FakeResponse(b'{"state":"FAILED"}')

    monkeypatch.setattr(video_generator.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(video_generator.VideoGenerationFailed, match="processing failed"):
        video_generator._download_video_file("file_123", "test-key")
    assert calls["status"] == 1
