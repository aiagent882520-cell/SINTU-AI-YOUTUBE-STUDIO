"""Crash-safe Google YouTube resumable-upload protocol helpers.

The caller owns durable state persistence and encryption. Session URLs must never
be logged or stored in plaintext. All offsets returned by this module are
server-acknowledged offsets, never locally guessed offsets.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

CHUNK_SIZE = 8 * 1024 * 1024  # Google resumable chunks: multiple of 256 KiB.
MAX_ATTEMPTS = 6
MAX_RESPONSE_BYTES = 1024 * 1024
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class UploadProtocolError(RuntimeError):
    def __init__(self, message: str, *, state: str = "ERROR", status: int | None = None):
        super().__init__(message)
        self.state = state
        self.status = status


def validate_session_uri(uri: str) -> str:
    parsed = urllib.parse.urlsplit(uri)
    if (parsed.scheme != "https" or parsed.hostname != "www.googleapis.com"
            or parsed.port not in (None, 443) or parsed.username or parsed.password
            or not parsed.path.startswith("/upload/youtube/") or parsed.fragment):
        raise UploadProtocolError("Google resumable session URI is invalid.")
    return uri


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_acknowledged_offset(headers, size: int) -> int:
    value = headers.get("Range") or headers.get("range")
    if value is None:
        return 0
    if not isinstance(value, str) or not value.startswith("bytes=0-"):
        raise UploadProtocolError("Google returned an invalid acknowledged byte range.")
    end = value[8:]
    if not end.isdigit():
        raise UploadProtocolError("Google returned an invalid acknowledged byte range.")
    offset = int(end) + 1
    if offset < 0 or offset > size:
        raise UploadProtocolError("Google acknowledged a byte range outside the file.")
    return offset


def _decode_completion(body: bytes) -> dict:
    try:
        result = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise UploadProtocolError("YouTube upload completion response was invalid.") from None
    if not isinstance(result, dict) or not result.get("id"):
        raise UploadProtocolError("YouTube upload completion did not include a video ID.")
    return result


def _default_request(method: str, url: str, data: bytes, headers: dict):
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            return response.status, response.headers, body
    except urllib.error.HTTPError as exc:
        body = exc.read(MAX_RESPONSE_BYTES + 1)
        return exc.code, exc.headers, body
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ConnectionError("YouTube upload network interruption.") from exc


def transfer_resumable_upload(
    path: str | Path,
    session_uri: str,
    access_token: str,
    *,
    request: Callable = _default_request,
    on_progress: Callable[[int, str], None] | None = None,
    chunk_size: int = CHUNK_SIZE,
    max_attempts: int = MAX_ATTEMPTS,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """Upload chunks, probing Google after ambiguous failures before resuming."""
    path = Path(path)
    validate_session_uri(session_uri)
    if not path.is_file() or path.is_symlink():
        raise UploadProtocolError("Upload source file is missing or unsafe.")
    size = path.stat().st_size
    if size <= 0:
        raise UploadProtocolError("Zero-byte videos cannot be uploaded.")
    if chunk_size < 256 * 1024 or chunk_size % (256 * 1024):
        raise ValueError("chunk_size must be a multiple of 256 KiB.")
    expected_hash = sha256_file(path)
    offset = 0
    attempt = 0
    if on_progress:
        on_progress(offset, "UPLOADING")

    def call(data: bytes, content_range: str):
        headers = {
            "Authorization": "Bearer " + access_token,
            "Content-Type": "video/mp4",
            "Content-Length": str(len(data)),
            "Content-Range": content_range,
        }
        status, response_headers, body = request("PUT", session_uri, data, headers)
        if len(body) > MAX_RESPONSE_BYTES:
            raise UploadProtocolError("YouTube upload response exceeded safety limit.")
        return status, response_headers, body

    with path.open("rb") as source:
        while offset < size:
            if sha256_file(path) != expected_hash:
                raise UploadProtocolError("Rendered MP4 changed during upload; session paused.", state="PAUSED")
            source.seek(offset)
            payload = source.read(min(chunk_size, size - offset))
            if not payload:
                raise UploadProtocolError("Upload source ended before the recorded file size.")
            end = offset + len(payload) - 1
            try:
                status, response_headers, body = call(payload, f"bytes {offset}-{end}/{size}")
            except (ConnectionError, TimeoutError, OSError):
                status, response_headers, body = 0, {}, b""

            if status in (200, 201):
                result = _decode_completion(body)
                if on_progress:
                    on_progress(size, "VERIFYING")
                return result
            if status == 308:
                acknowledged = parse_acknowledged_offset(response_headers, size)
                if acknowledged > end + 1:
                    raise UploadProtocolError("Google acknowledged bytes beyond the sent chunk.")
                if acknowledged < offset:
                    raise UploadProtocolError("Google upload offset moved backwards; refusing unsafe resume.")
                offset = acknowledged
                attempt = 0
                if on_progress:
                    on_progress(offset, "UPLOADING")
                continue
            if status in (404, 410):
                raise UploadProtocolError("Google resumable session expired; safe new session required.", state="EXPIRED", status=status)
            if status == 401:
                raise UploadProtocolError("Google authorization expired; reconnect or refresh OAuth before retry.", state="PAUSED", status=status)
            if status and status not in RETRYABLE_STATUS:
                raise UploadProtocolError(f"YouTube upload rejected the chunk (HTTP {status}).", status=status)

            # The request may have reached Google even when the client lost its
            # response. Probe the session and trust only Google's Range header.
            try:
                probe_status, probe_headers, probe_body = call(b"", f"bytes */{size}")
            except (ConnectionError, TimeoutError, OSError):
                probe_status, probe_headers, probe_body = 0, {}, b""
            if probe_status in (200, 201):
                result = _decode_completion(probe_body)
                if on_progress:
                    on_progress(size, "VERIFYING")
                return result
            if probe_status in (404, 410):
                raise UploadProtocolError("Google resumable session expired during recovery.", state="EXPIRED", status=probe_status)
            if probe_status == 308:
                acknowledged = parse_acknowledged_offset(probe_headers, size)
                if acknowledged > size or acknowledged < offset:
                    raise UploadProtocolError("Google returned an unsafe recovery offset.")
                offset = acknowledged
                if on_progress:
                    on_progress(offset, "RESUMING")
            attempt += 1
            if attempt >= max_attempts:
                raise UploadProtocolError("Upload retry limit reached; resumable session retained.", state="PAUSED", status=status or probe_status)
            sleep(min(2 ** (attempt - 1), 30))

    raise UploadProtocolError("Upload ended without a YouTube completion response.")

UPLOAD_STATES = {
    "QUEUED": {"INITIALIZING", "CANCELLED"},
    "INITIALIZING": {"UPLOADING", "PAUSED", "ERROR", "EXPIRED"},
    "UPLOADING": {"PAUSED", "RESUMING", "VERIFYING", "ERROR", "EXPIRED", "CANCELLED"},
    "PAUSED": {"RESUMING", "EXPIRED", "ERROR", "CANCELLED"},
    "RESUMING": {"UPLOADING", "VERIFYING", "PAUSED", "ERROR", "EXPIRED", "CANCELLED"},
    "VERIFYING": {"COMPLETED", "PAUSED", "ERROR"},
    "ERROR": {"INITIALIZING", "RESUMING", "CANCELLED"},
    "EXPIRED": {"INITIALIZING", "CANCELLED"},
    "COMPLETED": set(),
    "CANCELLED": set(),
}


def validate_state_transition(previous: str, next_state: str) -> None:
    if next_state == previous:
        return
    if next_state not in UPLOAD_STATES.get(previous, set()):
        raise UploadProtocolError(f"Invalid upload state transition: {previous} -> {next_state}.")
