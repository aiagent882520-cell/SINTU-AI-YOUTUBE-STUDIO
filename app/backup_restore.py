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
DATABASE_MEMBERS = {
    "database/sintu_studio.db": ("sintu_studio.db", {"tasks", "admin_users", "security_audit", "app_settings", "content_calendar"}),
    "database/sintu_earnings.sqlite3": ("sintu_earnings.sqlite3", {"earning_records", "earning_targets"}),
}
DATABASE_MEMBER = "database/sintu_studio.db"


class BackupValidationError(ValueError):
    """Raised when an archive cannot be trusted as a SINTU backup."""


def _safe_member_name(name: str) -> bool:
    if not name or "\\" in name or name.startswith("/"):
        return False
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return False
    if name in DATABASE_MEMBERS:
        return True
    if name.startswith("media/"):
        parts = path.parts
        return len(parts) >= 3 and parts[1] in MEDIA_DIRS
    return False


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


def validate_database(database_path: str | Path, required_tables: set[str] | None = None) -> dict:
    """Read-only SQLite recovery validation, including schema and foreign-key checks."""
    database_path = Path(database_path)
    try:
        uri = database_path.resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=10) as conn:
            conn.execute("PRAGMA query_only=ON")
            integrity = conn.execute("PRAGMA integrity_check").fetchall()
            if not integrity or any(row[0] != "ok" for row in integrity):
                raise BackupValidationError("SQLite integrity_check failed.")
            foreign_key_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
            if foreign_key_errors:
                raise BackupValidationError("SQLite foreign_key_check found inconsistent references.")
            tables = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            }
            missing = sorted((required_tables or set()) - tables)
            if missing:
                raise BackupValidationError("Restored database is missing required tables: " + ", ".join(missing))
            return {
                "integrity": "ok",
                "foreign_key_errors": 0,
                "table_count": len(tables),
                "required_tables_present": True,
                "page_count": conn.execute("PRAGMA page_count").fetchone()[0],
            }
    except BackupValidationError:
        raise
    except (OSError, sqlite3.Error, ValueError) as exc:
        raise BackupValidationError("SQLite recovery validation failed: " + str(exc)[:180]) from None


def verify_backup(archive_path: str | Path) -> dict:
    """Fully verify ZIP structure, manifest hashes, file limits and every SQLite database."""
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
            if names.count("manifest.json") != 1:
                raise BackupValidationError("Backup manifest is missing or duplicated.")
            if len(infos) > MAX_FILES + 1:
                raise BackupValidationError("Backup contains too many files.")
            for info in infos:
                if info.is_dir() or (not _safe_member_name(info.filename) and info.filename != "manifest.json"):
                    raise BackupValidationError("Archive contains an unsupported or unsafe path.")
                unix_mode = (info.external_attr >> 16) & 0xFFFF
                if (unix_mode & 0o170000) == 0o120000:
                    raise BackupValidationError("Archive contains a symbolic link.")
                if info.file_size > MAX_TOTAL_BYTES:
                    raise BackupValidationError("Archive member exceeds the size safety limit.")
            manifest_info = next(item for item in infos if item.filename == "manifest.json")
            if manifest_info.file_size > 5 * 1024 * 1024:
                raise BackupValidationError("Backup manifest exceeds the 5 MiB safety limit.")
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
            database_results = {}
            with tempfile.TemporaryDirectory(prefix="sintu-backup-check-") as temp_dir:
                for entry in entries:
                    if not isinstance(entry, dict):
                        raise BackupValidationError("Backup manifest contains an invalid entry.")
                    name = entry.get("path")
                    expected_size = entry.get("size_bytes")
                    expected_hash = entry.get("sha256")
                    if not isinstance(name, str) or not _safe_member_name(name) or name in expected_names:
                        raise BackupValidationError("Backup manifest contains an unsafe or duplicate path.")
                    if not isinstance(expected_size, int) or isinstance(expected_size, bool) or expected_size < 0:
                        raise BackupValidationError("Backup manifest contains an invalid file size.")
                    if not isinstance(expected_hash, str) or len(expected_hash) != 64 or any(c not in "0123456789abcdef" for c in expected_hash):
                        raise BackupValidationError("Backup manifest contains an invalid SHA-256 digest.")
                    expected_names.add(name)
                    total += expected_size
                    if total > MAX_TOTAL_BYTES:
                        raise BackupValidationError("Backup exceeds the 2 GiB uncompressed safety limit.")
                    try:
                        with archive.open(name, "r") as member:
                            if name in DATABASE_MEMBERS:
                                database_copy = Path(temp_dir) / (DATABASE_MEMBERS[name][0] + ".check")
                                with database_copy.open("wb") as output:
                                    actual_size, actual_hash = _digest_stream(member, output)
                            else:
                                actual_size, actual_hash = _digest_stream(member)
                    except (KeyError, OSError, zipfile.BadZipFile, RuntimeError):
                        raise BackupValidationError("Backup member could not be read: " + name) from None
                    if actual_size != expected_size or actual_hash != expected_hash:
                        raise BackupValidationError("Backup checksum or file size mismatch: " + name)
                    if name in DATABASE_MEMBERS:
                        _, required = DATABASE_MEMBERS[name]
                        database_results[name] = validate_database(database_copy, required)
                if DATABASE_MEMBER not in database_results:
                    raise BackupValidationError("Backup does not contain the studio database.")
                archive_names = set(names) - {"manifest.json"}
                if archive_names != expected_names:
                    raise BackupValidationError("Archive members do not match the manifest.")
                if manifest.get("total_uncompressed_bytes") != total:
                    raise BackupValidationError("Backup total size does not match its manifest.")
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
        "databases": database_results,
    }


def snapshot_database(source_path: str | Path, snapshot_path: str | Path) -> None:
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
    """Restore databases atomically with rollback copies; add media without overwriting."""
    if not app_stopped:
        raise BackupValidationError("Stop SINTU Studio first, then explicitly confirm --app-stopped.")
    archive_path = Path(archive_path)
    verification = verify_backup(archive_path)
    data_dir = Path(data_dir).expanduser().resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    backup_dir = data_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    if backup_dir.is_symlink():
        raise BackupValidationError("Backup safety-copy directory is a symbolic link; restore stopped.")
    import secrets
    restore_token = secrets.token_hex(6)
    staged = {}
    safety = {}
    installed = []
    added_media_paths = []
    added_media = 0
    skipped_media = 0
    media_conflicts = []
    database_results = {}
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            manifest = json.loads(archive.read("manifest.json"))
            media_hashes = {
                entry["path"]: entry["sha256"]
                for entry in manifest["files"] if entry["path"].startswith("media/")
            }
            database_names = [name for name in DATABASE_MEMBERS if name in archive.namelist()]
            for member_name in database_names:
                filename, required_tables = DATABASE_MEMBERS[member_name]
                destination = data_dir / filename
                if destination.is_symlink():
                    raise BackupValidationError("Studio database path is a symbolic link; restore stopped.")
                stage = data_dir / (".sintu-restore-" + restore_token + "-" + filename)
                with archive.open(member_name, "r") as member, stage.open("xb") as output:
                    shutil.copyfileobj(member, output, 1024 * 1024)
                staged[filename] = stage
                database_results[filename] = validate_database(stage, required_tables)
                if destination.is_file():
                    safe_copy = backup_dir / ("pre-restore-" + filename + "-" + restore_token + ".sqlite")
                    snapshot_database(destination, safe_copy)
                    safety[filename] = safe_copy
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
                    if not target.is_file():
                        media_conflicts.append(name)
                    else:
                        with target.open("rb") as existing:
                            _, existing_hash = _digest_stream(existing)
                        if existing_hash != media_hashes.get(name):
                            media_conflicts.append(name)
                    continue
                temporary_media = None
                try:
                    with tempfile.NamedTemporaryFile(
                        mode="wb", prefix=".sintu-restore-media-", suffix=".tmp",
                        dir=target.parent, delete=False,
                    ) as output:
                        temporary_media = Path(output.name)
                        with archive.open(info, "r") as member:
                            shutil.copyfileobj(member, output, 1024 * 1024)
                        output.flush()
                        os.fsync(output.fileno())
                    # Exclusive creation is portable to Android/Termux, where os.link may be unavailable.
                    # It also guarantees that a racing file is never overwritten.
                    descriptor = os.open(
                        target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
                    )
                    added_media_paths.append(target)
                    with os.fdopen(descriptor, "wb") as published:
                        with temporary_media.open("rb") as source:
                            shutil.copyfileobj(source, published, 1024 * 1024)
                        published.flush()
                        os.fsync(published.fileno())
                    added_media += 1
                except FileExistsError:
                    skipped_media += 1
                finally:
                    if temporary_media is not None:
                        temporary_media.unlink(missing_ok=True)
            for filename, stage in staged.items():
                destination = data_dir / filename
                for suffix in ("-wal", "-shm"):
                    sidecar = Path(str(destination) + suffix)
                    if sidecar.is_symlink():
                        raise BackupValidationError("Database sidecar is a symbolic link; restore stopped.")
                    sidecar.unlink(missing_ok=True)
                os.replace(stage, destination)
                installed.append(filename)
                filename_member = next(name for name, pair in DATABASE_MEMBERS.items() if pair[0] == filename)
                _, required_tables = DATABASE_MEMBERS[filename_member]
                database_results[filename] = validate_database(destination, required_tables)
    except Exception:
        for media_path in reversed(added_media_paths):
            media_path.unlink(missing_ok=True)
        for filename in reversed(installed):
            destination = data_dir / filename
            safe_copy = safety.get(filename)
            if safe_copy and safe_copy.exists():
                os.replace(safe_copy, destination)
            else:
                destination.unlink(missing_ok=True)
        raise
    finally:
        for stage in staged.values():
            stage.unlink(missing_ok=True)
    return {
        "restored": True,
        "databases": database_results,
        "database_safety_copies": {name: str(path) for name, path in safety.items() if path.exists()},
        "media_files_added": added_media,
        "media_files_preserved": skipped_media,
        "media_conflicts": media_conflicts,
        "recovery_validation": {
            "passed": True,
            "databases_checked": len(database_results),
            "all_sqlite_integrity_checks": "ok",
            "all_foreign_key_checks": "ok",
            "required_schema_tables_present": True,
        },
        "verification": verification,
    }
