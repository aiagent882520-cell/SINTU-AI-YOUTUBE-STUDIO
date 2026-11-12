import hashlib
import json
import sqlite3
import zipfile

import pytest

from app.backup_restore import BackupValidationError, restore_backup, verify_backup


def make_backup(tmp_path, *, tamper=False):
    source = tmp_path / "source.sqlite"
    with sqlite3.connect(source) as conn:
        conn.execute("CREATE TABLE demo(value TEXT)")
        conn.execute("INSERT INTO demo VALUES('backup-data')")
    media = b"video-data"
    manifest = {
        "format": "sintu-studio-backup-v1",
        "database_integrity": "ok",
        "file_count": 2,
        "total_uncompressed_bytes": source.stat().st_size + len(media),
        "files": [
            {"path": "database/sintu_studio.db", "size_bytes": source.stat().st_size,
             "sha256": hashlib.sha256(source.read_bytes()).hexdigest()},
            {"path": "media/generated_videos/sample.mp4", "size_bytes": len(media),
             "sha256": hashlib.sha256(media).hexdigest()},
        ],
    }
    archive_path = tmp_path / "sintu-backup-test.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(source, "database/sintu_studio.db")
        archive.writestr("media/generated_videos/sample.mp4", b"tampered" if tamper else media)
        archive.writestr("manifest.json", json.dumps(manifest))
    return archive_path


def test_backup_verification_checks_all_hashes_and_sqlite(tmp_path):
    archive = make_backup(tmp_path)
    result = verify_backup(archive)
    assert result["verified"] is True
    assert result["file_count"] == 2
    assert result["database_integrity"] == "ok"
    assert len(result["archive_sha256"]) == 64


def test_backup_verification_rejects_changed_media(tmp_path):
    archive = make_backup(tmp_path, tamper=True)
    with pytest.raises(BackupValidationError, match="checksum"):
        verify_backup(archive)


def test_backup_verification_rejects_unsafe_manifest_path(tmp_path):
    archive = make_backup(tmp_path)
    with zipfile.ZipFile(archive, "a") as z:
        z.writestr("../escape.txt", "bad")
    with pytest.raises(BackupValidationError):
        verify_backup(archive)


def test_restore_requires_explicit_stopped_app_confirmation(tmp_path):
    archive = make_backup(tmp_path)
    with pytest.raises(BackupValidationError, match="Stop SINTU"):
        restore_backup(archive, tmp_path / "data", app_stopped=False)


def test_restore_creates_database_safety_copy_and_adds_media_without_overwrite(tmp_path):
    archive = make_backup(tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    current_db = data / "sintu_studio.db"
    with sqlite3.connect(current_db) as conn:
        conn.execute("CREATE TABLE current_data(value TEXT)")
        conn.execute("INSERT INTO current_data VALUES('keep as safety copy')")
    media_dir = data / "generated_videos"
    media_dir.mkdir()
    (media_dir / "sample.mp4").write_bytes(b"existing-video")

    result = restore_backup(archive, data, app_stopped=True)
    assert result["restored"] is True
    assert result["database_safety_copy"]
    assert Path(result["database_safety_copy"]).is_file()
    assert result["media_files_preserved"] == 1
    assert result["media_conflicts"] == ["media/generated_videos/sample.mp4"]
    assert result["media_files_added"] == 0
    assert (media_dir / "sample.mp4").read_bytes() == b"existing-video"
    with sqlite3.connect(current_db) as conn:
        assert conn.execute("SELECT value FROM demo").fetchone() == ("backup-data",)
        assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    with sqlite3.connect(result["database_safety_copy"]) as conn:
        assert conn.execute("SELECT value FROM current_data").fetchone() == ("keep as safety copy",)


from pathlib import Path

def test_restore_preserves_identical_existing_media_without_conflict(tmp_path):
    archive = make_backup(tmp_path)
    data = tmp_path / "data"
    media_dir = data / "generated_videos"
    media_dir.mkdir(parents=True)
    (media_dir / "sample.mp4").write_bytes(b"video-data")
    result = restore_backup(archive, data, app_stopped=True)
    assert result["media_files_preserved"] == 1
    assert result["media_conflicts"] == []
    assert (media_dir / "sample.mp4").read_bytes() == b"video-data"


def test_restore_refuses_symlink_database_destination(tmp_path):
    archive = make_backup(tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    outside = tmp_path / "outside.sqlite"
    with sqlite3.connect(outside) as conn:
        conn.execute("CREATE TABLE safe(value TEXT)")
    (data / "sintu_studio.db").symlink_to(outside)
    with pytest.raises(BackupValidationError, match="symbolic link"):
        restore_backup(archive, data, app_stopped=True)
