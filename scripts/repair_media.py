#!/usr/bin/env python3
"""Backup-first repair of legacy SINTU MP4 audio streams to AAC 48 kHz stereo."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.getenv("SINTU_DATA_DIR", str(ROOT))).expanduser().resolve()
DEFAULT_MEDIA_DIR = DATA_DIR / "generated_videos"


def needs_audio_repair(metadata: dict) -> bool:
    """Return true only when an existing audio stream violates the SINTU MP4 profile."""
    streams = metadata.get("streams") or []
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    if audio is None:
        return False
    try:
        sample_rate = int(audio.get("sample_rate", 0))
        channels = int(audio.get("channels", 0))
    except (TypeError, ValueError):
        return True
    return (str(audio.get("codec_name", "")).lower() != "aac"
            or sample_rate != 48000 or channels != 2)


def probe(path: Path, ffprobe: str) -> dict:
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries",
         "format=format_name,duration:stream=codec_type,codec_name,width,height,pix_fmt,sample_rate,channels",
         "-of", "json", str(path)],
        capture_output=True, text=True, timeout=45, check=False,
    )
    if result.returncode:
        raise RuntimeError((result.stderr or "FFprobe failed")[-1000:])
    return json.loads(result.stdout)


def _backup_atomically(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError("Refusing to overwrite an existing media backup.")
    temporary = destination.with_name(destination.name + ".part")
    try:
        shutil.copy2(source, temporary)
        with temporary.open("rb+") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def repair_one(path: Path, *, apply: bool, backup_dir: Path, ffmpeg: str, ffprobe: str) -> dict:
    if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".mp4":
        return {"file": path.name, "status": "skipped_unsafe"}
    original = probe(path, ffprobe)
    streams = original.get("streams") or []
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    if not video:
        return {"file": path.name, "status": "failed", "reason": "missing video stream"}
    fmt_names = str((original.get("format") or {}).get("format_name", "")).lower().split(",")
    if not ({"mp4", "mov"} & set(fmt_names)):
        return {"file": path.name, "status": "failed", "reason": "not an MP4/MOV container"}
    if (str(video.get("codec_name", "")).lower() != "h264"
            or str(video.get("pix_fmt", "")).lower() != "yuv420p"):
        return {"file": path.name, "status": "failed",
                "reason": "video stream is outside the supported H.264/yuv420p repair profile"}
    if audio is None:
        return {"file": path.name, "status": "skipped_no_audio"}
    if not needs_audio_repair(original):
        return {"file": path.name, "status": "already_valid",
                "audio": {"codec": "aac", "sample_rate": 48000, "channels": 2}}
    try:
        duration = float((original.get("format") or {}).get("duration", 0))
    except (TypeError, ValueError):
        duration = 0
    if duration <= 0:
        return {"file": path.name, "status": "failed", "reason": "invalid source duration"}
    if not apply:
        return {"file": path.name, "status": "would_repair",
                "source_audio": {"codec": audio.get("codec_name"),
                                 "sample_rate": audio.get("sample_rate"),
                                 "channels": audio.get("channels")},
                "target_audio": {"codec": "aac", "sample_rate": 48000, "channels": 2}}
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".sintu-audio-repair-", suffix=".mp4",
            dir=path.parent, delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
        command = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(path),
            "-map", "0:v:0", "-map", "0:a:0", "-map", "0:s?",
            "-map_metadata", "0", "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-c:s", "mov_text", "-movflags", "+faststart", str(temporary_path),
        ]
        rendered = subprocess.run(
            command, capture_output=True, text=True, timeout=900, check=False,
        )
        if rendered.returncode or not temporary_path.is_file() or temporary_path.stat().st_size <= 1000:
            raise RuntimeError((rendered.stderr or "FFmpeg audio repair failed")[-1200:])
        repaired_metadata = probe(temporary_path, ffprobe)
        if needs_audio_repair(repaired_metadata):
            raise RuntimeError("repaired output did not meet AAC 48 kHz stereo profile")
        from scripts.project_health_audit import validate_mp4_metadata
        validate_mp4_metadata(repaired_metadata)
        backup_path = backup_dir / path.name
        _backup_atomically(path, backup_path)
        os.replace(temporary_path, path)
        temporary_path = None
        return {"file": path.name, "status": "repaired",
                "backup": str(backup_path),
                "audio": {"codec": "aac", "sample_rate": 48000, "channels": 2},
                "video_stream": "copied_without_re-encoding"}
    except Exception as exc:
        return {"file": path.name, "status": "failed", "reason": str(exc)[:1200]}
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--media-dir", type=Path, default=DEFAULT_MEDIA_DIR)
    parser.add_argument("--backup-dir", type=Path, default=None)
    parser.add_argument("--apply", action="store_true",
                        help="Apply repairs only after verifying a temporary output; originals are backed up first.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    requested_media_dir = args.media_dir.expanduser()
    if requested_media_dir.is_symlink():
        print(json.dumps({"status": "FAIL", "error": "media directory must not be a symlink"}))
        return 2
    media_dir = requested_media_dir.resolve()
    if not media_dir.is_dir():
        print(json.dumps({"status": "FAIL", "error": "media directory missing or unsafe"}))
        return 2
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        print(json.dumps({"status": "FAIL", "error": "FFmpeg and FFprobe are required"}))
        return 2
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_dir = (args.backup_dir.expanduser().resolve() if args.backup_dir
                  else DATA_DIR / "media_backups" / stamp)
    results = []
    for path in sorted(media_dir.glob("*.mp4")):
        try:
            results.append(repair_one(path, apply=args.apply, backup_dir=backup_dir,
                                      ffmpeg=ffmpeg, ffprobe=ffprobe))
        except Exception as exc:
            results.append({"file": path.name, "status": "failed", "reason": str(exc)[:1200]})
    failures = [item for item in results if item["status"] == "failed"]
    summary = {
        "status": "FAIL" if failures else "PASS",
        "mode": "apply" if args.apply else "dry_run",
        "media_dir": str(media_dir),
        "backup_dir": str(backup_dir) if args.apply else None,
        "total": len(results),
        "would_repair": sum(item["status"] == "would_repair" for item in results),
        "repaired": sum(item["status"] == "repaired" for item in results),
        "already_valid": sum(item["status"] == "already_valid" for item in results),
        "skipped_no_audio": sum(item["status"] == "skipped_no_audio" for item in results),
        "failed": len(failures),
        "results": results,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
