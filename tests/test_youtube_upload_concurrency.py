import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import main


def configure_upload_lock_test(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "sintu-upload-lock.sqlite3")
    monkeypatch.setenv("SINTU_AUTH_REQUIRED", "false")
    main.init_db()


def insert_upload(calendar_id, status="UPLOADING"):
    now = "2026-11-21T00:00:00+00:00"
    with main.db() as conn:
        conn.execute(
            """INSERT INTO youtube_uploads(
                calendar_id,video_id,channel_id,title,description_sha256,privacy_status,
                file_size,file_sha256,status,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (calendar_id, "a" * 32, "UC-lock-test", "Lock test", "d" * 64,
             "private", 100, "f" * 64, status, now, now),
        )


def test_youtube_upload_lock_is_exclusive_and_reclaims_expired_lease(tmp_path, monkeypatch):
    configure_upload_lock_test(tmp_path, monkeypatch)
    owner = main._claim_youtube_upload_lock(41)
    with pytest.raises(HTTPException) as blocked:
        main._claim_youtube_upload_lock(41)
    assert blocked.value.status_code == 409

    with main.db() as conn:
        conn.execute(
            "UPDATE youtube_upload_locks SET lease_until=? WHERE calendar_id=?",
            (int(time.time()) - 1, 41),
        )
    replacement = main._claim_youtube_upload_lock(41)
    assert replacement != owner

    # A stale worker cannot release the replacement worker's lease.
    main._release_youtube_upload_lock(41, owner)
    with main.db() as conn:
        row = conn.execute(
            "SELECT owner FROM youtube_upload_locks WHERE calendar_id=?", (41,)
        ).fetchone()
    assert row["owner"] == replacement
    main._release_youtube_upload_lock(41, replacement)


def test_youtube_upload_state_transition_cannot_overwrite_cancelled(tmp_path, monkeypatch):
    configure_upload_lock_test(tmp_path, monkeypatch)
    insert_upload(42, status="CANCELLED")

    with pytest.raises(HTTPException) as rejected:
        main._youtube_upload_transition(42, "UPLOADING", offset=75)
    assert rejected.value.status_code == 409

    with main.db() as conn:
        row = conn.execute(
            "SELECT status,acknowledged_offset FROM youtube_uploads WHERE calendar_id=42"
        ).fetchone()
    assert tuple(row) == ("CANCELLED", 0)


def test_youtube_cancel_remains_available_while_upload_worker_holds_lease(tmp_path, monkeypatch):
    configure_upload_lock_test(tmp_path, monkeypatch)
    insert_upload(43, status="UPLOADING")
    owner = main._claim_youtube_upload_lock(43)
    try:
        response = TestClient(main.app).post("/api/admin/youtube/uploads/43/cancel")
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "CANCELLED"
        with main.db() as conn:
            status = conn.execute(
                "SELECT status FROM youtube_uploads WHERE calendar_id=43"
            ).fetchone()["status"]
        assert status == "CANCELLED"
    finally:
        main._release_youtube_upload_lock(43, owner)
