import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from app.backup_restore import BackupValidationError, restore_backup, validate_database, verify_backup


def make_backup(tmp_path, *, tamper=False, include_earnings=False, include_runtime=False):
    source = tmp_path / "source.sqlite"
    with sqlite3.connect(source) as conn:
        for table in ("tasks", "admin_users", "security_audit", "app_settings", "content_calendar"):
            conn.execute(f"CREATE TABLE {table}(id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO tasks(value) VALUES('backup-data')")
    members = [("database/sintu_studio.db", source, source.read_bytes())]
    if include_earnings:
        earnings = tmp_path / "earnings.sqlite"
        with sqlite3.connect(earnings) as conn:
            conn.execute("CREATE TABLE earning_records(id INTEGER PRIMARY KEY, title TEXT)")
            conn.execute("CREATE TABLE earning_targets(id INTEGER PRIMARY KEY, month TEXT)")
            conn.execute("INSERT INTO earning_records(title) VALUES('revenue-record')")
        members.append(("database/sintu_earnings.sqlite3", earnings, earnings.read_bytes()))
    if include_runtime:
        runtime = tmp_path / "production_runtime.sqlite3"
        with sqlite3.connect(runtime) as conn:
            conn.execute("CREATE TABLE production_runs(id TEXT PRIMARY KEY, status TEXT)")
            conn.execute("CREATE TABLE production_steps(id INTEGER PRIMARY KEY, run_id TEXT)")
            conn.execute("INSERT INTO production_runs VALUES('run-1', 'completed')")
        members.append(("database/production_runtime.sqlite3", runtime, runtime.read_bytes()))
    members.append(("media/generated_videos/sample.mp4", None, b"video-data"))
    entries = []
    total = 0
    for name, source_path, content in members:
        raw = source_path.read_bytes() if source_path else content
        entries.append({"path": name, "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
        total += len(raw)
    manifest = {
        "format": "sintu-studio-backup-v1",
        "database_integrity": "ok",
        "database_members": [Path(name).name for name, _, _ in members if name.startswith("database/")],
        "file_count": len(entries),
        "total_uncompressed_bytes": total,
        "files": entries,
    }
    archive_path = tmp_path / "sintu-backup-test.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, source_path, content in members:
            raw = source_path.read_bytes() if source_path else content
            if tamper and name.startswith("media/"):
                raw = b"tampered"
            archive.writestr(name, raw)
        archive.writestr("manifest.json", json.dumps(manifest))
    return archive_path


def test_backup_verification_checks_all_hashes_and_sqlite(tmp_path):
    archive = make_backup(tmp_path, include_earnings=True, include_runtime=True)
    result = verify_backup(archive)
    assert result["verified"] is True
    assert result["file_count"] == 4
    assert result["database_integrity"] == "ok"
    assert set(result["databases"]) == {
        "database/sintu_studio.db", "database/sintu_earnings.sqlite3",
        "database/production_runtime.sqlite3",
    }
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


def test_restore_validates_databases_and_creates_safety_copies(tmp_path):
    archive = make_backup(tmp_path, include_earnings=True, include_runtime=True)
    data = tmp_path / "data"
    data.mkdir()
    current_db = data / "sintu_studio.db"
    with sqlite3.connect(current_db) as conn:
        conn.execute("CREATE TABLE current_data(value TEXT)")
        conn.execute("INSERT INTO current_data VALUES('keep as safety copy')")
    current_earnings = data / "sintu_earnings.sqlite3"
    with sqlite3.connect(current_earnings) as conn:
        conn.execute("CREATE TABLE old_earning(value TEXT)")
    current_runtime = data / "production_runtime.sqlite3"
    with sqlite3.connect(current_runtime) as conn:
        conn.execute("CREATE TABLE old_run(value TEXT)")
        conn.execute("INSERT INTO old_run VALUES('preserve as safety copy')")
    media_dir = data / "generated_videos"
    media_dir.mkdir()
    (media_dir / "sample.mp4").write_bytes(b"existing-video")

    result = restore_backup(archive, data, app_stopped=True)
    assert result["restored"] is True
    assert result["recovery_validation"]["passed"] is True
    assert result["recovery_validation"]["databases_checked"] == 3
    assert set(result["database_safety_copies"]) == {
        "sintu_studio.db", "sintu_earnings.sqlite3", "production_runtime.sqlite3",
    }
    for safety_path in result["database_safety_copies"].values():
        assert Path(safety_path).is_file()
    assert result["media_files_preserved"] == 1
    assert result["media_conflicts"] == ["media/generated_videos/sample.mp4"]
    assert result["media_files_added"] == 0
    assert (media_dir / "sample.mp4").read_bytes() == b"existing-video"
    with sqlite3.connect(current_db) as conn:
        assert conn.execute("SELECT value FROM tasks").fetchone() == ("backup-data",)
        assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    with sqlite3.connect(current_earnings) as conn:
        assert conn.execute("SELECT title FROM earning_records").fetchone() == ("revenue-record",)
    with sqlite3.connect(result["database_safety_copies"]["sintu_studio.db"]) as conn:
        assert conn.execute("SELECT value FROM current_data").fetchone() == ("keep as safety copy",)
    with sqlite3.connect(data / "production_runtime.sqlite3") as conn:
        assert conn.execute("SELECT status FROM production_runs WHERE id='run-1'").fetchone() == ("completed",)
    with sqlite3.connect(result["database_safety_copies"]["production_runtime.sqlite3"]) as conn:
        assert conn.execute("SELECT value FROM old_run").fetchone() == ("preserve as safety copy",)


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


def test_recovery_validation_rejects_missing_required_tables(tmp_path):
    broken = tmp_path / "missing-tables.sqlite"
    with sqlite3.connect(broken) as conn:
        conn.execute("CREATE TABLE wrong(value TEXT)")
    with pytest.raises(BackupValidationError, match="required tables"):
        validate_database(broken, {"tasks", "admin_users"})


def test_restore_failure_removes_media_added_before_database_commit(tmp_path, monkeypatch):
    from app import backup_restore

    archive = make_backup(tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    def fail_replace(source, destination):
        raise OSError("simulated database install failure")
    monkeypatch.setattr(backup_restore.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated database install failure"):
        restore_backup(archive, data, app_stopped=True)
    media_dir = data / "generated_videos"
    assert not (media_dir / "sample.mp4").exists()
    assert not list(media_dir.glob(".sintu-restore-media-*.tmp"))
    assert not list(data.glob(".sintu-restore-*.sqlite"))


def test_restore_rolls_back_all_databases_when_third_install_fails(tmp_path, monkeypatch):
    from app import backup_restore

    archive = make_backup(tmp_path, include_earnings=True, include_runtime=True)
    data = tmp_path / "data"
    data.mkdir()
    originals = {
        "sintu_studio.db": ("old_studio", "studio-original"),
        "sintu_earnings.sqlite3": ("old_earnings", "earnings-original"),
        "production_runtime.sqlite3": ("old_runtime", "runtime-original"),
    }
    for filename, (table, value) in originals.items():
        with sqlite3.connect(data / filename) as conn:
            conn.execute(f"CREATE TABLE {table}(value TEXT)")
            conn.execute(f"INSERT INTO {table} VALUES(?)", (value,))

    real_replace = backup_restore.os.replace
    failed = False

    def fail_third_install(source, destination):
        nonlocal failed
        source = Path(source)
        destination = Path(destination)
        if (
            not failed
            and destination == data / "production_runtime.sqlite3"
            and source.name.startswith(".sintu-restore-")
        ):
            failed = True
            raise OSError("simulated third database install failure")
        return real_replace(source, destination)

    monkeypatch.setattr(backup_restore.os, "replace", fail_third_install)

    with pytest.raises(OSError, match="third database install failure"):
        restore_backup(archive, data, app_stopped=True)

    assert failed is True
    for filename, (table, value) in originals.items():
        with sqlite3.connect(data / filename) as conn:
            assert conn.execute(f"SELECT value FROM {table}").fetchone() == (value,)
            assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)

    assert not (data / "generated_videos" / "sample.mp4").exists()
    assert not list(data.glob(".sintu-restore-*.sqlite"))
    assert not list(data.glob(".sintu-restore-media-*.tmp"))
    assert not list((data / "backups").glob("pre-restore-*.sqlite"))



def test_backup_allowlist_includes_verified_production_packages_and_manifests():
    from app.backup_restore import _safe_member_name

    assert _safe_member_name("media/production_packages/" + "a" * 32 + "-delivery.zip")
    assert _safe_member_name("media/production_manifests/" + "a" * 32 + "-final.json")
    assert not _safe_member_name("media/production_packages/../private.zip")
    assert not _safe_member_name("media/production_manifests/link")
