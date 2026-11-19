"""Bounded, hash-verified resumable uploads for offline media clients."""
from __future__ import annotations

import hashlib
import fcntl
import json
import os
import re
import secrets
import shutil
from contextlib import contextmanager
import time
from pathlib import Path
from typing import Any

from .offline_media import MAX_MEDIA_BYTES, OfflineMediaError, import_media_file

_CHUNK_BYTES = 4 * 1024 * 1024
_SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{32,64}$")
_SHA = re.compile(r"^[a-f0-9]{64}$")


class ResumableUploadError(ValueError):
    pass


def _root(data_dir: Path) -> Path:
    base = Path(data_dir).expanduser().resolve()
    media_root = base / "offline_media"
    if media_root.is_symlink():
        raise ResumableUploadError("Offline media directory must not be a symlink.")
    media_root.mkdir(parents=True, exist_ok=True)
    resolved_media_root = media_root.resolve()
    if not resolved_media_root.is_relative_to(base):
        raise ResumableUploadError("Offline media storage escaped its data directory.")
    root = media_root / ".resumable"
    if root.is_symlink():
        raise ResumableUploadError("Resumable upload storage is unsafe.")
    root.mkdir(parents=True, exist_ok=True)
    if not root.resolve().is_relative_to(resolved_media_root):
        raise ResumableUploadError("Resumable upload storage escaped its data directory.")
    return root


@contextmanager
def _session_lock(data_dir: Path, upload_id: str):
    """Serialize an existing session across threads AND separate server processes."""
    metadata_path, _ = _paths(data_dir, upload_id, create=False)
    lock_path = metadata_path.parent / ".session.lock"
    if lock_path.is_symlink():
        raise ResumableUploadError("Upload session lock path is unsafe.")
    with lock_path.open("a+b") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

def _write_metadata(path: Path, metadata: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(metadata))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _paths(data_dir: Path, upload_id: str, *, create: bool = False) -> tuple[Path, Path]:
    if not isinstance(upload_id, str) or not _SESSION_ID.fullmatch(upload_id):
        raise ResumableUploadError("Invalid upload session ID.")
    root = _root(data_dir)
    directory = root / upload_id
    if directory.is_symlink():
        raise ResumableUploadError("Upload session path is unsafe.")
    if create:
        directory.mkdir(exist_ok=True)
    elif not directory.is_dir():
        raise ResumableUploadError("Upload session not found.")
    if not directory.resolve().is_relative_to(root.resolve()):
        raise ResumableUploadError("Upload session path escaped its storage directory.")
    return directory / "session.json", directory / "payload.part"


def create_upload(*, data_dir: Path, filename: str, size_bytes: int, sha256: str) -> dict[str, Any]:
    safe_name = Path(filename.replace("\\", "/")).name.strip()
    if not safe_name or len(safe_name) > 180 or any(ord(c) < 32 for c in safe_name):
        raise ResumableUploadError("Invalid original filename.")
    if not isinstance(size_bytes, int) or isinstance(size_bytes, bool) or not 1 <= size_bytes <= MAX_MEDIA_BYTES:
        raise ResumableUploadError("Media size must be between 1 byte and 256 MiB.")
    if not _SHA.fullmatch(sha256):
        raise ResumableUploadError("Invalid expected SHA-256.")
    upload_id = secrets.token_urlsafe(32)
    metadata_path, payload_path = _paths(data_dir, upload_id, create=True)
    metadata = {"id": upload_id, "filename": safe_name, "size_bytes": size_bytes,
                "sha256": sha256, "offset": 0, "created_at": int(time.time()),
                "status": "uploading"}
    payload_path.touch(mode=0o600)
    _write_metadata(metadata_path, metadata)
    return {"upload_id": upload_id, "offset": 0, "chunk_size": _CHUNK_BYTES}


def get_upload(*, data_dir: Path, upload_id: str) -> dict[str, Any]:
    metadata_path, payload_path = _paths(data_dir, upload_id, create=False)
    if not metadata_path.is_file() or metadata_path.is_symlink():
        raise ResumableUploadError("Upload session not found.")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("status") == "uploading" and (not payload_path.is_file() or payload_path.is_symlink()):
        raise ResumableUploadError("Upload payload is missing or unsafe.")
    return {"upload_id": upload_id, "offset": int(metadata["offset"]),
            "size_bytes": int(metadata["size_bytes"]), "sha256": metadata["sha256"], "status": metadata["status"]}


def append_upload_chunk(*, data_dir: Path, upload_id: str, offset: int,
                        chunk: bytes, chunk_sha256: str) -> dict[str, Any]:
    if not chunk or len(chunk) > _CHUNK_BYTES:
        raise ResumableUploadError("Chunk must be between 1 byte and 4 MiB.")
    if not _SHA.fullmatch(chunk_sha256) or hashlib.sha256(chunk).hexdigest() != chunk_sha256:
        raise ResumableUploadError("Chunk SHA-256 verification failed.")
    with _session_lock(data_dir, upload_id):
        metadata_path, payload_path = _paths(data_dir, upload_id, create=False)
        if not metadata_path.is_file() or metadata_path.is_symlink() or payload_path.is_symlink():
            raise ResumableUploadError("Upload session not found or unsafe.")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("status") != "uploading":
            raise ResumableUploadError("Upload session is not accepting chunks.")
        expected = int(metadata["offset"])
        if offset != expected:
            raise ResumableUploadError(f"Offset conflict; server expects {expected}.")
        if expected + len(chunk) > int(metadata["size_bytes"]):
            raise ResumableUploadError("Chunk exceeds declared upload size.")
        with payload_path.open("r+b") as output:
            output.seek(expected)
            output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        metadata["offset"] = expected + len(chunk)
        _write_metadata(metadata_path, metadata)
        return {"upload_id": upload_id, "offset": metadata["offset"],
                "size_bytes": metadata["size_bytes"]}


def complete_upload(*, data_dir: Path, upload_id: str,
                    content_type: str = "application/octet-stream") -> dict[str, Any]:
    with _session_lock(data_dir, upload_id):
        metadata_path, payload_path = _paths(data_dir, upload_id)
        if not metadata_path.is_file() or metadata_path.is_symlink() or payload_path.is_symlink():
            raise ResumableUploadError("Upload session not found or unsafe.")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("status") == "completed":
            return {"media": metadata["media"], "duplicate": metadata["media"]["duplicate"]}
        if int(metadata["offset"]) != int(metadata["size_bytes"]):
            raise ResumableUploadError("Upload is incomplete.")
        digest = hashlib.sha256()
        with payload_path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != metadata["sha256"]:
            raise ResumableUploadError("Final media SHA-256 verification failed.")
        staging_path = payload_path.with_name("finalizing.part")
        if staging_path.is_symlink():
            raise ResumableUploadError("Upload finalization path is unsafe.")
        staging_path.unlink(missing_ok=True)
        shutil.copyfile(payload_path, staging_path)
        try:
            record = import_media_file(data_dir=data_dir, source_path=staging_path,
                                       filename=metadata["filename"], content_type=content_type)
        except OfflineMediaError as exc:
            staging_path.unlink(missing_ok=True)
            raise ResumableUploadError(str(exc)) from None
        metadata["status"] = "completed"
        metadata["media"] = record
        _write_metadata(metadata_path, metadata)
        payload_path.unlink(missing_ok=True)
        return {"media": record, "duplicate": record["duplicate"]}
