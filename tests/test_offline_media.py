from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from app.offline_media import (
    OfflineMediaError,
    get_offline_media_path,
    import_media_file,
    list_offline_media,
)


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("SINTU_AUTH_REQUIRED", "false")
    monkeypatch.setenv("SINTU_PRODUCTION_ENABLED", "true")
    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "offline-test.sqlite3")
    main._LOGIN_LIMITER.reset()
    main._FIREWALL_LIMITER.reset()
    main.init_db()
    return TestClient(main.app)



def _append_resumable_chunk_in_process(args):
    data_dir, upload_id, payload = args
    from app.resumable_media_upload import ResumableUploadError, append_upload_chunk
    try:
        return append_upload_chunk(
            data_dir=Path(data_dir), upload_id=upload_id, offset=0,
            chunk=payload, chunk_sha256=hashlib.sha256(payload).hexdigest(),
        )
    except ResumableUploadError as exc:
        return str(exc)


def test_offline_media_api_imports_deduplicates_lists_and_downloads(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    payload = b"offline-mp4-content"
    first = client.post(
        "/api/offline-media/import?filename=clip.mp4",
        content=payload,
        headers={"content-type": "video/mp4"},
    )
    assert first.status_code == 201, first.text
    media = first.json()["media"]
    assert media["sha256"] == hashlib.sha256(payload).hexdigest()
    assert media["size_bytes"] == len(payload)
    assert first.json()["duplicate"] is False

    second = client.post(
        "/api/offline-media/import?filename=renamed.mp4",
        content=payload,
        headers={"content-type": "video/mp4"},
    )
    assert second.status_code == 201
    assert second.json()["duplicate"] is True
    assert second.json()["media"]["sha256"] == media["sha256"]

    listed = client.get("/api/offline-media")
    assert listed.status_code == 200
    assert len(listed.json()["media"]) == 1

    downloaded = client.get(media["download_url"])
    assert downloaded.status_code == 200
    assert downloaded.content == payload


def test_offline_media_api_rejects_empty_and_unsupported_files(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    assert client.post("/api/offline-media/import?filename=empty.mp4", content=b"").status_code == 400
    unsupported = client.post("/api/offline-media/import?filename=payload.exe", content=b"data")
    assert unsupported.status_code == 400


def test_offline_media_import_refuses_symlinked_storage(tmp_path):
    target = tmp_path / "outside"
    target.mkdir()
    root = tmp_path / "offline_media"
    root.symlink_to(target, target_is_directory=True)
    source = tmp_path / "incoming.part"
    source.write_bytes(b"content")
    with pytest.raises(OfflineMediaError, match="symlink"):
        import_media_file(data_dir=tmp_path, source_path=source, filename="clip.mp4")


def test_offline_media_download_detects_tampered_content(tmp_path):
    source = tmp_path / "incoming.part"
    source.write_bytes(b"original")
    record = import_media_file(data_dir=tmp_path, source_path=source, filename="clip.mp4")
    stored = tmp_path / "offline_media" / "files" / record["stored_name"]
    stored.write_bytes(b"tampered")
    with pytest.raises(OfflineMediaError, match="hash verification"):
        get_offline_media_path(data_dir=tmp_path, sha256=record["sha256"])


def test_offline_media_rejects_zero_and_over_limit_files(tmp_path, monkeypatch):
    import app.offline_media as offline_media
    empty = tmp_path / "empty.part"
    empty.write_bytes(b"")
    with pytest.raises(OfflineMediaError, match="size"):
        import_media_file(data_dir=tmp_path, source_path=empty, filename="empty.mp4")
    source = tmp_path / "large.part"
    source.write_bytes(b"12345")
    monkeypatch.setattr(offline_media, "MAX_MEDIA_BYTES", 4)
    with pytest.raises(OfflineMediaError, match="size"):
        import_media_file(data_dir=tmp_path, source_path=source, filename="large.mp4")


def test_offline_media_cleans_only_stale_interrupted_upload_parts(tmp_path):
    import os
    import time
    from app.offline_media import list_offline_media
    incoming = tmp_path / "offline_media" / ".incoming"
    incoming.mkdir(parents=True)
    stale = incoming / "old-upload.part"
    stale.write_bytes(b"partial")
    os.utime(stale, (time.time() - 90000, time.time() - 90000))
    recent = incoming / "active-upload.part"
    recent.write_bytes(b"still-active")
    list_offline_media(data_dir=tmp_path)
    assert not stale.exists()
    assert recent.exists()


def test_offline_media_refuses_same_size_corrupt_unindexed_destination(tmp_path):
    import sqlite3
    source = tmp_path / "first.part"
    source.write_bytes(b"expected-content")
    record = import_media_file(data_dir=tmp_path, source_path=source, filename="clip.mp4")
    database = tmp_path / "offline_media" / "index.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM offline_media WHERE sha256=?", (record["sha256"],))
    stored = tmp_path / "offline_media" / "files" / record["stored_name"]
    stored.write_bytes(b"corrupts-content")  # same byte length, different SHA-256
    retry = tmp_path / "retry.part"
    retry.write_bytes(b"expected-content")
    with pytest.raises(OfflineMediaError, match="hash mismatch"):
        import_media_file(data_dir=tmp_path, source_path=retry, filename="clip.mp4")

def test_resumable_upload_accepts_ordered_verified_chunks_and_completes_idempotently(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    payload = b"resumable-video-payload"
    digest = hashlib.sha256(payload).hexdigest()
    created = client.post(f"/api/offline-media/uploads?filename=clip.mp4&size_bytes={len(payload)}&sha256={digest}")
    assert created.status_code == 201, created.text
    upload_id = created.json()["upload_id"]
    split = 9
    first = payload[:split]
    response = client.put(f"/api/offline-media/uploads/{upload_id}/chunks?offset=0", content=first, headers={"X-Chunk-SHA256": hashlib.sha256(first).hexdigest()})
    assert response.status_code == 200, response.text
    assert response.json()["offset"] == split
    conflict = client.put(f"/api/offline-media/uploads/{upload_id}/chunks?offset=0", content=first, headers={"X-Chunk-SHA256": hashlib.sha256(first).hexdigest()})
    assert conflict.status_code == 409
    rest = payload[split:]
    appended = client.put(f"/api/offline-media/uploads/{upload_id}/chunks?offset={split}", content=rest, headers={"X-Chunk-SHA256": hashlib.sha256(rest).hexdigest()})
    assert appended.status_code == 200
    completed = client.post(f"/api/offline-media/uploads/{upload_id}/complete")
    assert completed.status_code == 201, completed.text
    assert completed.json()["media"]["sha256"] == digest
    again = client.post(f"/api/offline-media/uploads/{upload_id}/complete")
    assert again.status_code == 201
    assert again.json()["media"]["sha256"] == digest

def test_resumable_upload_rejects_bad_chunk_hash_and_incomplete_completion(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    payload = b"integrity-check"
    digest = hashlib.sha256(payload).hexdigest()
    created = client.post(f"/api/offline-media/uploads?filename=clip.mp4&size_bytes={len(payload)}&sha256={digest}")
    upload_id = created.json()["upload_id"]
    bad = client.put(f"/api/offline-media/uploads/{upload_id}/chunks?offset=0", content=payload, headers={"X-Chunk-SHA256": "0" * 64})
    assert bad.status_code == 400
    incomplete = client.post(f"/api/offline-media/uploads/{upload_id}/complete")
    assert incomplete.status_code == 409

def test_resumable_upload_rejects_wrong_final_sha256(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    payload = b"wrong-final-digest"
    created = client.post(f"/api/offline-media/uploads?filename=clip.mp4&size_bytes={len(payload)}&sha256=" + "0" * 64)
    upload_id = created.json()["upload_id"]
    chunk = client.put(f"/api/offline-media/uploads/{upload_id}/chunks?offset=0", content=payload, headers={"X-Chunk-SHA256": hashlib.sha256(payload).hexdigest()})
    assert chunk.status_code == 200
    complete = client.post(f"/api/offline-media/uploads/{upload_id}/complete")
    assert complete.status_code == 400


def test_resumable_upload_serializes_concurrent_chunk_writes(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from app.resumable_media_upload import (
        ResumableUploadError, append_upload_chunk, create_upload,
    )
    first = b"first-chunk"
    second = b"other-chunk"
    create = create_upload(
        data_dir=tmp_path, filename="clip.mp4",
        size_bytes=len(first) + len(second),
        sha256=hashlib.sha256(first + second).hexdigest(),
    )
    upload_id = create["upload_id"]

    def append(payload):
        try:
            return append_upload_chunk(
                data_dir=tmp_path, upload_id=upload_id, offset=0,
                chunk=payload, chunk_sha256=hashlib.sha256(payload).hexdigest(),
            )
        except ResumableUploadError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(append, (first, second)))
    successes = [item for item in results if isinstance(item, dict)]
    conflicts = [item for item in results if isinstance(item, str)]
    assert len(successes) == 1
    assert len(conflicts) == 1
    assert "Offset conflict" in conflicts[0]
    from app.resumable_media_upload import get_upload
    assert get_upload(data_dir=tmp_path, upload_id=upload_id)["offset"] == len(first) or get_upload(data_dir=tmp_path, upload_id=upload_id)["offset"] == len(second)


def test_resumable_upload_serializes_concurrent_process_writes(tmp_path):
    from concurrent.futures import ProcessPoolExecutor
    from app.resumable_media_upload import create_upload, get_upload

    first = b"process-one-chunk"
    second = b"process-two-chunk"
    created = create_upload(
        data_dir=tmp_path, filename="clip.mp4",
        size_bytes=len(first) + len(second),
        sha256=hashlib.sha256(first + second).hexdigest(),
    )
    upload_id = created["upload_id"]
    args = [(str(tmp_path), upload_id, first), (str(tmp_path), upload_id, second)]

    # Independent Python processes must coordinate through the on-disk flock,
    # not a process-local threading mutex.
    with ProcessPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(_append_resumable_chunk_in_process, args))

    successes = [item for item in results if isinstance(item, dict)]
    conflicts = [item for item in results if isinstance(item, str)]
    assert len(successes) == 1
    assert len(conflicts) == 1
    assert "Offset conflict" in conflicts[0]
    assert get_upload(data_dir=tmp_path, upload_id=upload_id)["offset"] in {len(first), len(second)}


def test_resumable_unknown_session_does_not_create_session_directories(tmp_path):
    from app.resumable_media_upload import ResumableUploadError, get_upload

    unknown_id = "A" * 32
    with pytest.raises(ResumableUploadError, match="not found"):
        get_upload(data_dir=tmp_path, upload_id=unknown_id)

    root = tmp_path / "offline_media" / ".resumable"
    assert root.is_dir()
    assert not (root / unknown_id).exists()


def test_resumable_upload_rejects_symlinked_offline_media_root(tmp_path):
    from app.resumable_media_upload import ResumableUploadError, create_upload

    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "offline_media").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ResumableUploadError, match="must not be a symlink"):
        create_upload(
            data_dir=tmp_path,
            filename="clip.mp4",
            size_bytes=1,
            sha256=hashlib.sha256(b"x").hexdigest(),
        )

    assert not (outside / ".resumable").exists()
