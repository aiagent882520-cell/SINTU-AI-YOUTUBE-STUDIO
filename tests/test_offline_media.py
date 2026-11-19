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
