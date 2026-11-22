"""Durable, content-addressed local media library for offline-first clients."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

ALLOWED_MEDIA_EXTENSIONS = {
    ".mp4", ".mov", ".mkv", ".webm", ".avi",
    ".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac",
    ".jpg", ".jpeg", ".png", ".webp",
}
MAX_MEDIA_BYTES = 256 * 1024 * 1024
_SHA256 = re.compile(r"^[a-f0-9]{64}$")


class OfflineMediaError(ValueError):
    pass


def _paths(data_dir: Path) -> tuple[Path, Path, Path, Path]:
    base = Path(data_dir).expanduser().resolve()
    root = base / "offline_media"
    if root.is_symlink():
        raise OfflineMediaError("Offline media directory must not be a symlink.")
    root.mkdir(parents=True, exist_ok=True)
    media = root / "files"
    incoming = root / ".incoming"
    for directory in (media, incoming):
        if directory.is_symlink():
            raise OfflineMediaError("Offline media storage contains an unsafe symlink.")
        directory.mkdir(parents=True, exist_ok=True)
        if not directory.resolve().is_relative_to(root.resolve()):
            raise OfflineMediaError("Offline media storage escaped its data directory.")
    for stale in incoming.glob("*.part"):
        try:
            if stale.is_file() and not stale.is_symlink() and stale.stat().st_mtime < time.time() - 86400:
                stale.unlink()
        except OSError:
            pass
    database = root / "index.sqlite3"
    if database.is_symlink():
        raise OfflineMediaError("Offline media index must not be a symlink.")
    return root, media, incoming, database


def _connect(database: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("""
        CREATE TABLE IF NOT EXISTS offline_media (
            sha256 TEXT PRIMARY KEY,
            stored_name TEXT NOT NULL,
            original_name TEXT NOT NULL,
            extension TEXT NOT NULL,
            content_type TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            imported_at TEXT NOT NULL
        )
    """)
    return connection


@contextmanager
def _database(database: Path):
    connection = _connect(database)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_file_exclusive(source: Path, destination: Path, expected_sha256: str) -> None:
    """Publish a verified copy without hard links or overwriting an existing path."""
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output, Path(source).open("rb") as incoming:
            shutil.copyfileobj(incoming, output, length=1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        if _sha256_file(destination) != expected_sha256:
            raise OfflineMediaError("Copied media failed SHA-256 verification.")
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def import_media_file(
    *, data_dir: Path, source_path: Path, filename: str, content_type: str = "application/octet-stream"
) -> dict[str, Any]:
    source = Path(source_path)
    if source.is_symlink() or not source.is_file():
        raise OfflineMediaError("Incoming media file is missing or unsafe.")
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_MEDIA_EXTENSIONS:
        raise OfflineMediaError("Unsupported media extension.")
    size = source.stat().st_size
    if size <= 0 or size > MAX_MEDIA_BYTES:
        raise OfflineMediaError("Media size must be between 1 byte and 256 MiB.")
    sha256 = _sha256_file(source)
    root, media_dir, _, database = _paths(data_dir)
    safe_name = Path(filename.replace("\\", "/")).name.strip()
    if not safe_name or len(safe_name) > 180 or any(ord(char) < 32 for char in safe_name):
        raise OfflineMediaError("Invalid original filename.")
    stored_name = sha256 + extension
    destination = media_dir / stored_name
    created = False
    if destination.exists():
        if destination.is_symlink() or not destination.is_file() or destination.stat().st_size != size or _sha256_file(destination) != sha256:
            raise OfflineMediaError("Existing content-addressed media file is unsafe or has a hash mismatch.")
    else:
        try:
            _copy_file_exclusive(source, destination, sha256)
            created = True
        except FileExistsError:
            if destination.is_symlink() or not destination.is_file() or destination.stat().st_size != size or _sha256_file(destination) != sha256:
                raise OfflineMediaError("Concurrent media import produced an unsafe or mismatched destination.") from None
    import datetime
    imported_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        with _database(database) as connection:
            existing = connection.execute("SELECT * FROM offline_media WHERE sha256=?", (sha256,)).fetchone()
            if existing:
                existing_path = media_dir / existing["stored_name"]
                if existing_path.is_symlink() or not existing_path.is_file():
                    raise OfflineMediaError("Indexed media file is missing or unsafe.")
                if _sha256_file(existing_path) != sha256:
                    raise OfflineMediaError("Indexed media hash no longer matches its content.")
                record = dict(existing)
                duplicate = True
            else:
                connection.execute(
                    """INSERT INTO offline_media(sha256,stored_name,original_name,extension,content_type,size_bytes,imported_at)
                       VALUES(?,?,?,?,?,?,?)""",
                    (sha256, stored_name, safe_name, extension, content_type[:160], size, imported_at),
                )
                record = dict(connection.execute("SELECT * FROM offline_media WHERE sha256=?", (sha256,)).fetchone())
                duplicate = False
    except Exception:
        if created:
            destination.unlink(missing_ok=True)
        raise
    source.unlink(missing_ok=True)
    if duplicate and created and destination != media_dir / record["stored_name"]:
        destination.unlink(missing_ok=True)
    record["duplicate"] = duplicate
    record["download_url"] = "/api/offline-media/" + sha256 + "/file"
    return record


def list_offline_media(*, data_dir: Path) -> list[dict[str, Any]]:
    _, media_dir, _, database = _paths(data_dir)
    if not database.exists():
        return []
    with _connect(database) as connection:
        rows = connection.execute("SELECT * FROM offline_media ORDER BY imported_at DESC").fetchall()
    result = []
    for row in rows:
        record = dict(row)
        path = media_dir / record["stored_name"]
        if path.is_symlink() or not path.is_file() or path.stat().st_size != record["size_bytes"]:
            continue
        record["download_url"] = "/api/offline-media/" + record["sha256"] + "/file"
        result.append(record)
    return result


def get_offline_media_path(*, data_dir: Path, sha256: str) -> tuple[Path, dict[str, Any]]:
    if not _SHA256.fullmatch(sha256):
        raise OfflineMediaError("Invalid media SHA-256.")
    _, media_dir, _, database = _paths(data_dir)
    if not database.exists():
        raise OfflineMediaError("Offline media item not found.")
    with _connect(database) as connection:
        row = connection.execute("SELECT * FROM offline_media WHERE sha256=?", (sha256,)).fetchone()
    if not row:
        raise OfflineMediaError("Offline media item not found.")
    record = dict(row)
    path = media_dir / record["stored_name"]
    if path.is_symlink() or not path.is_file() or path.stat().st_size != record["size_bytes"]:
        raise OfflineMediaError("Offline media file is missing or unsafe.")
    digest = _sha256_file(path)
    if digest != sha256:
        raise OfflineMediaError("Offline media hash verification failed.")
    return path, record
