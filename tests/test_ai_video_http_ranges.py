from fastapi.testclient import TestClient

from app import main


def test_ai_video_endpoint_serves_single_byte_ranges(tmp_path, monkeypatch):
    video_id = "a" * 32
    payload = bytes(range(256)) * 4
    monkeypatch.setenv("SINTU_AUTH_REQUIRED", "false")
    monkeypatch.setenv("SINTU_AUTH_REQUIRED", "false")
    monkeypatch.setattr(main, "AI_VIDEO_DIR", tmp_path)
    (tmp_path / f"{video_id}.mp4").write_bytes(payload)
    client = TestClient(main.app)

    partial = client.get(
        f"/api/ai-videos/{video_id}",
        headers={"Range": "bytes=10-19"},
    )
    assert partial.status_code == 206
    assert partial.headers["accept-ranges"] == "bytes"
    assert partial.headers["content-range"] == f"bytes 10-19/{len(payload)}"
    assert partial.content == payload[10:20]

    suffix = client.get(
        f"/api/ai-videos/{video_id}",
        headers={"Range": "bytes=-16"},
    )
    assert suffix.status_code == 206
    assert suffix.headers["content-range"] == f"bytes {len(payload) - 16}-{len(payload) - 1}/{len(payload)}"
    assert suffix.content == payload[-16:]


def test_ai_video_endpoint_rejects_unsatisfiable_byte_range(tmp_path, monkeypatch):
    video_id = "b" * 32
    payload = b"video-fixture"
    monkeypatch.setenv("SINTU_AUTH_REQUIRED", "false")
    monkeypatch.setattr(main, "AI_VIDEO_DIR", tmp_path)
    (tmp_path / f"{video_id}.mp4").write_bytes(payload)
    response = TestClient(main.app).get(
        f"/api/ai-videos/{video_id}",
        headers={"Range": f"bytes={len(payload) + 1}-"},
    )
    assert response.status_code == 416
    assert response.headers["content-range"] == f"bytes */{len(payload)}"
