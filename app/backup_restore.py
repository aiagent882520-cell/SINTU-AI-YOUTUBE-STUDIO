"""Validation and offline, non-destructive restore for SINTU Studio backup archives."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

BACKUP_FORMAT = "sintu-studio-backup-v1"
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
MAX_FILES = 10_000
MEDIA_DIRS = {"generated_images", "generated_ai_videos", "generated_audio", "generated_music", "generated_videos"}
DATABASE_MEMBER = "database/sintu_studio.db"


class BackupValidationError(ValueError):
    """Raised when an archive cannot be trusted as a SINTU backup."""


def _safe_member_name(name: str) -> bool:
    if not name or "\\" in name or name.startswith("/"):
        return False
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return False
    if name != DATABASE_MEMBER and not name.startswith("media/"):
        return False
    if name.startswith("media/"):
        parts = path.parts
        if len(parts) < 3 or parts[1] not in MEDIA_DIRS:
            return False
    return True


def _digest_stream(stream, output=None, limit=MAX_TOTAL_BYTES):
    digest = hashlib.sha256()
    size = 0
    while True:
        chunk = stream.read(1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        if size > limit:
            raise BackupValidationError("Archive member exceeds the uncompressed size safety limit.")
        digest.update(chunk)
        if output is not None:
            output.write(chunk)
    return size, digest.hexdigest()


def verify_backup(archive_path: str | Path) -> dict:
    """Fully verify ZIP structure, manifest hashes, file limits and SQLite integrity."""
    archive_path = Path(archive_path)
    if archive_path.is_symlink() or not archive_path.is_file():
        raise BackupValidationError("Backup file is missing or is a symbolic link.")
    if archive_path.stat().st_size > MAX_TOTAL_BYTES:
        raise BackupValidationError("Backup archive exceeds the 2 GiB safety limit.")
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            infos = archive.infolist()
            names = [item.filename for item in infos]
            if len(names) != len(set(names)):
                raise BackupValidationError("Archive contains duplicate file names.")
            if "manifest.json" not in names or names.count("manifest.json") != 1:
                raise BackupValidationError("Backup manifest is missing or duplicated.")
            if len(infos) > MAX_FILES + 1:
                raise BackupValidationError("Backup contains too many files.")
            for info in infos:
                if info.is_dir() or not _safe_member_name(info.filename) and info.filename != "manifest.json":
                    raise BackupValidationError("Archive contains an unsupported or unsafe path.")
                unix_mode = (info.external_attr >> 16) & 0xFFFF
                if (unix_mode & 0o170000) == 0o120000:
                    raise BackupValidationError("Archive contains a symbolic link.")
                if info.file_size > MAX_TOTAL_BYTES:
                    raise BackupValidationError("Archive member exceeds the size safety limit.")
            try:
                manifest = json.loads(archive.read("manifest.json"))
            except (UnicodeDecodeError, json.JSONDecodeError, KeyError):
                raise BackupValidationError("Backup manifest is not valid JSON.") from None
            if not isinstance(manifest, dict) or manifest.get("format") != BACKUP_FORMAT:
                raise BackupValidationError("Unsupported backup format.")
            if manifest.get("database_integrity") != "ok":
                raise BackupValidationError("Backup manifest does not attest to a valid database.")
            entries = manifest.get("files")
            if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_FILES:
                raise BackupValidationError("Backup manifest file list is invalid.")
            if manifest.get("file_count") != len(entries):
                raise BackupValidationError("Backup manifest file count does not match.")
            expected_names = set()
            total = 0
            database_seen = False
            with tempfile.TemporaryDirectory(prefix="sintu-backup-check-") as temp_dir:
                database_copy = Path(temp_dir) / "snapshot.sqlite"
                for entry in entries:
                    if not isinstance(entry, dict):
                        raise BackupValidationError("Backup manifest contains an invalid entry.")
                    name = entry.get("path")
                    expected_size = entry.get("size_bytes")
                    expected_hash = entry.get("sha256")
                    if not isinstance(name, str) or not _safe_member_name(name) or name in expected_names:
                        raise BackupValidationError("Backup manifest contains an unsafe or duplicate path.")
                    if not isinstance(expected_size, int) or expected_size < 0:
                        raise BackupValidationError("Backup manifest contains an invalid file size.")
                    if not isinstance(expected_hash, str) or len(expected_hash) != 64 or any(c not in "0123456789abcdef" for c in expected_hash):
                        raise BackupValidationError("Backup manifest contains an invalid SHA-256 digest.")
                    expected_names.add(name)
                    total += expected_size
                    if total > MAX_TOTAL_BYTES:
                        raise BackupValidationError("Backup exceeds the 2 GiB uncompressed safety limit.")
                    try:
                        with archive.open(name, "r") as member:
                            if name == DATABASE_MEMBER:
                                with database_copy.open("wb") as output:
                                    actual_size, actual_hash = _digest_stream(member, output)
                            else:
                                actual_size, actual_hash = _digest_stream(member)
                    except (KeyError, OSError, zipfile.BadZipFile, RuntimeError):
                        raise BackupValidationError("Backup member could not be read: " + name) from None
                    if actual_size != expected_size or actual_hash != expected_hash:
                        raise BackupValidationError("Backup checksum or file size mismatch: " + name)
                    if name == DATABASE_MEMBER:
                        database_seen = True
                if not database_seen:
                    raise BackupValidationError("Backup does not contain the studio database.")
                archive_names = set(names) - {"manifest.json"}
                if archive_names != expected_names:
                    raise BackupValidationError("Archive members do not match the manifest.")
                if manifest.get("total_uncompressed_bytes") != total:
                    raise BackupValidationError("Backup total size does not match its manifest.")
                try:
                    with sqlite3.connect("file:" + str(database_copy) + "?mode=ro", uri=True) as conn:
                        check = conn.execute("PRAGMA integrity_check").fetchone()
                        if not check or check[0] != "ok":
                            raise BackupValidationError("SQLite database integrity check failed.")
                except sqlite3.Error:
                    raise BackupValidationError("Backup database could not be opened safely.") from None
    except BackupValidationError:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError):
        raise BackupValidationError("Backup archive is corrupt or unreadable.") from None
    digest = hashlib.sha256()
    with archive_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "verified": True,
        "format": BACKUP_FORMAT,
        "file_count": len(entries),
        "total_uncompressed_bytes": total,
        "archive_size_bytes": archive_path.stat().st_size,
        "archive_sha256": digest.hexdigest(),
        "database_integrity": "ok",
    }


def _snapshot_database(source_path: Path, snapshot_path: Path) -> None:
    source = sqlite3.connect(str(source_path), timeout=30)
    try:
        target = sqlite3.connect(str(snapshot_path), timeout=30)
        try:
            source.backup(target, pages=256, sleep=0.01)
            check = target.execute("PRAGMA integrity_check").fetchone()
            if not check or check[0] != "ok":
                raise BackupValidationError("Current database safety snapshot failed integrity check.")
        finally:
            target.close()
    finally:
        source.close()


def restore_backup(archive_path: str | Path, data_dir: str | Path, *, app_stopped: bool = False) -> dict:
    """Restore the database atomically and add missing media without overwriting existing files.

    This must run while the application is stopped. Existing media files are never overwritten.
    """
    if not app_stopped:
        raise BackupValidationError("Stop SINTU Studio first, then explicitly confirm --app-stopped.")
    archive_path = Path(archive_path)
    verification = verify_backup(archive_path)
    data_dir = Path(data_dir).expanduser().resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    database_path = data_dir / "sintu_studio.db"
    backup_dir = data_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    import secrets
    restore_token = secrets.token_hex(6)
    staged_database = data_dir / (".sintu-restore-" + restore_token + ".sqlite")
    safety_copy = backup_dir / ("pre-restore-db-" + restore_token + ".sqlite")
    added_media = 0
    skipped_media = 0
    media_conflicts = []
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            with archive.open(DATABASE_MEMBER, "r") as member, staged_database.open("xb") as output:
                shutil.copyfileobj(member, output, 1024 * 1024)
            if database_path.is_file():
                _snapshot_database(database_path, safety_copy)
            # Restore only into the expected media folders. Never follow symlinks or overwrite files.
            for info in archive.infolist():
                name = info.filename
                if not name.startswith("media/"):
                    continue
                relative = PurePosixPath(name).parts[1:]
                target = data_dir.joinpath(*relative)
                if not target.resolve().is_relative_to(data_dir):
                    raise BackupValidationError("Media destination escapes the data directory.")
                current = data_dir
                for part in relative[:-1]:
                    current = current / part
                    if current.is_symlink():
                        raise BackupValidationError("Media destination contains a symbolic link.")
                    current.mkdir(exist_ok=True)
                    if not current.is_dir():
                        raise BackupValidationError("Media destination is not a directory.")
                if target.is_symlink():
                    raise BackupValidationError("Media destination is a symbolic link.")
                if target.exists():
                    skipped_media += 1
                    if not target.is_file() or target.stat().st_size != info.file_size:
                        media_conflicts.append(name)
                    continue
                try:
                    with archive.open(info, "r") as member, target.open("xb") as output:
                        shutil.copyfileobj(member, output, 1024 * 1024)
                    added_media += 1
                except FileExistsError:
                    skipped_media += 1
            # A leftover WAL/SHM beside the database can be replayed against the new file.
            # Since the app is stopped and the current DB has a safety snapshot, remove sidecars.
            for suffix in ("-wal", "-shm"):
                sidecar = Path(str(database_path) + suffix)
                if sidecar.is_symlink():
                    raise BackupValidationError("Database sidecar is a symbolic link; restore stopped.")
                sidecar.unlink(missing_ok=True)
            os.replace(staged_database, database_path)
    except Exception:
        if safety_copy.exists() and not database_path.exists():
            os.replace(safety_copy, database_path)
        raise
    finally:
        staged_database.unlink(missing_ok=True)
    return {
        "restored": True,
        "database": str(database_path),
        "database_safety_copy": str(safety_copy) if safety_copy.exists() else None,
        "media_files_added": added_media,
        "media_files_preserved": skipped_media,
        "media_conflicts": media_conflicts,
        "verification": verification,
    }
