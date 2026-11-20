from fastapi.testclient import TestClient

from app import main


def test_youtube_upload_history_is_filtered_ordered_and_secret_free(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "youtube-history.sqlite3")
    monkeypatch.setenv("SINTU_AUTH_REQUIRED", "false")
    main.init_db()
    with main.db() as conn:
        rows = [
            (101, "a" * 32, "channel-a", "Completed Short", "desc-hash", "private",
             1000, "file-hash-a", "ENCRYPTED_SESSION_URL_SECRET", 1000, "COMPLETED",
             "youtube-video-a", "processed", "2026-11-19T10:00:00+00:00", "2026-11-19T10:05:00+00:00"),
            (102, "b" * 32, "channel-a", "Paused Short", "desc-hash", "unlisted",
             2000, "file-hash-b", "ANOTHER_ENCRYPTED_SESSION_SECRET", 500, "PAUSED",
             None, "", "2026-11-19T10:01:00+00:00", "2026-11-19T10:06:00+00:00"),
        ]
        conn.executemany(
            """INSERT INTO youtube_uploads(
                calendar_id,video_id,channel_id,title,description_sha256,privacy_status,
                file_size,file_sha256,encrypted_session_uri,acknowledged_offset,status,
                youtube_video_id,processing_status,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )

    client = TestClient(main.app)
    response = client.get("/api/admin/youtube/uploads")
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    assert [item["calendar_id"] for item in payload["uploads"]] == [102, 101]
    assert payload["uploads"][0]["progress_percent"] == 25.0
    assert payload["uploads"][1]["progress_percent"] == 100.0
    serialized = response.text
    for secret in ("ENCRYPTED_SESSION_URL_SECRET", "ANOTHER_ENCRYPTED_SESSION_SECRET", "file-hash-a", "desc-hash"):
        assert secret not in serialized
    assert "encrypted_session_uri" not in serialized
    assert "file_sha256" not in serialized

    completed = client.get("/api/admin/youtube/uploads", params={"status": "COMPLETED"})
    assert completed.status_code == 200
    assert [item["calendar_id"] for item in completed.json()["uploads"]] == [101]
    assert client.get("/api/admin/youtube/uploads", params={"status": "UNKNOWN"}).status_code == 400
    assert client.get("/api/admin/youtube/uploads", params={"limit": 201}).status_code == 422
