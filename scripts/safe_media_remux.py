#!/usr/bin/env python3
"""Safely remux an MP4 to a NEW file; never overwrites or repairs black pixels."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str], timeout: int = 600) -> dict:
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=timeout, check=False)
        return {"returncode": result.returncode, "stdout": result.stdout,
                "stderr": result.stderr}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"returncode": None, "stdout": "", "stderr": type(exc).__name__}


def probe(path: Path, ffprobe: str) -> dict:
    result = run([ffprobe, "-v", "error", "-show_streams", "-show_format",
                  "-of", "json", str(path)], timeout=60)
    if result["returncode"] != 0:
        raise RuntimeError("FFprobe could not inspect media.")
    try:
        data = json.loads(result["stdout"])
    except (TypeError, json.JSONDecodeError):
        raise RuntimeError("FFprobe returned invalid metadata.") from None
    streams = data.get("streams")
    fmt = data.get("format")
    if not isinstance(streams, list) or not isinstance(fmt, dict):
        raise RuntimeError("FFprobe metadata is incomplete.")
    duration = fmt.get("duration")
    try:
        duration_value = float(duration)
    except (TypeError, ValueError):
        raise RuntimeError("Media duration is missing or invalid.") from None
    if not (0 < duration_value < 24 * 60 * 60):
        raise RuntimeError("Media duration is outside safe bounds.")
    return {"streams": streams, "duration": duration_value}


def _stream_signature(metadata: dict) -> list[tuple]:
    signature = []
    for stream in metadata["streams"]:
        signature.append((
            stream.get("codec_type"), stream.get("codec_name"),
            stream.get("width"), stream.get("height"),
            stream.get("sample_rate"), stream.get("channels"),
        ))
    return sorted(signature, key=lambda item: (str(item[0]), str(item[1])))


def _publish_exclusive(source: Path, destination: Path, expected_sha256: str) -> None:
    """Copy a completed temporary file without hard links or destination overwrite."""
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output, Path(source).open("rb") as incoming:
            shutil.copyfileobj(incoming, output, length=1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        if sha256_file(destination) != expected_sha256:
            raise RuntimeError("Published remux failed SHA-256 verification.")
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def safe_remux(source: Path, destination: Path, *,
               ffmpeg: str | None = None, ffprobe: str | None = None) -> dict:
    """Copy streams into a new MP4, verifying output and source integrity.

    This is a container remux only. It cannot reconstruct missing/black video
    frames, fix corrupt encoded packets, or repair absent source imagery.
    """
    source = Path(source).expanduser()
    destination = Path(destination).expanduser()
    if source.is_symlink() or not source.is_file():
        raise ValueError("Source must be an existing regular file, not a symlink.")
    if source.suffix.lower() != ".mp4" or destination.suffix.lower() != ".mp4":
        raise ValueError("Source and destination must use the .mp4 extension.")
    if not destination.parent.is_dir():
        raise ValueError("Destination directory must already exist.")
    source_real = source.resolve(strict=True)
    destination_real = destination.parent.resolve(strict=True) / destination.name
    if source_real == destination_real:
        raise ValueError("Source and destination must be different files.")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("Destination already exists; refusing to overwrite.")
    if source.stat().st_size <= 0:
        raise ValueError("Source file is empty.")
    ffmpeg = ffmpeg or shutil.which("ffmpeg")
    ffprobe = ffprobe or shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("Both FFmpeg and FFprobe are required.")
    original_hash = sha256_file(source)
    original = probe(source, ffprobe)
    if not any(item.get("codec_type") == "video" for item in original["streams"]):
        raise ValueError("Source has no video stream; refusing remux.")
    fd, temporary_name = tempfile.mkstemp(
        prefix=".sintu-remux-", suffix=".mp4", dir=destination.parent
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        temporary.unlink()
        result = run([
            ffmpeg, "-n", "-hide_banner", "-loglevel", "error",
            "-i", str(source), "-map", "0", "-c", "copy",
            "-movflags", "+faststart", str(temporary),
        ])
        if result["returncode"] != 0 or not temporary.is_file() or temporary.stat().st_size <= 0:
            raise RuntimeError("FFmpeg remux failed; temporary output was discarded.")
        remuxed = probe(temporary, ffprobe)
        if _stream_signature(original) != _stream_signature(remuxed):
            raise RuntimeError("Remux changed the stream layout; output was discarded.")
        tolerance = max(0.25, original["duration"] * 0.01)
        if abs(original["duration"] - remuxed["duration"]) > tolerance:
            raise RuntimeError("Remux duration differs from source; output was discarded.")
        decoded = run([ffmpeg, "-v", "error", "-xerror", "-i", str(temporary),
                       "-map", "0:v:0", "-f", "null", "-"], timeout=600)
        if decoded["returncode"] != 0:
            raise RuntimeError("Remuxed video failed decode validation; output was discarded.")
        if sha256_file(source) != original_hash:
            raise RuntimeError("Source checksum changed during remux; output was discarded.")
        output_hash = sha256_file(temporary)
        # Exclusive creation prevents overwriting a destination, including on
        # Android/Termux builds where os.link may be unavailable.
        _publish_exclusive(temporary, destination, output_hash)
        temporary.unlink()
        return {
            "status": "REMUXED_TO_NEW_FILE",
            "source": str(source),
            "destination": str(destination),
            "source_sha256_before": original_hash,
            "source_sha256_after": sha256_file(source),
            "output_sha256": output_hash,
            "source_bytes": source.stat().st_size,
            "output_bytes": destination.stat().st_size,
            "duration_seconds": remuxed["duration"],
            "stream_signature": _stream_signature(remuxed),
            "source_modified": False,
            "black_frame_repair_performed": False,
            "note": "Container remux only. Black or missing visual frames are not reconstructed.",
        }
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path,
                        help="New MP4 path; must not already exist")
    args = parser.parse_args()
    try:
        report = safe_remux(args.source, args.destination)
    except (ValueError, FileExistsError, RuntimeError, OSError) as exc:
        print(json.dumps({"status": "FAILED", "reason": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
