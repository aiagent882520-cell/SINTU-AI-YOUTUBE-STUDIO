#!/usr/bin/env python3
"""Compact, read-only forensic report for the five known black MP4s."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageStat

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("SINTU_DATA_DIR", str(ROOT))).expanduser().resolve()
MEDIA_DIR = DATA_DIR / "generated_videos"
TARGETS = (
    "3f4c2151e8e640109f464b2c2e9b7569.mp4",
    "59430f1fb7fd4bdf80cf8b7d9f456098.mp4",
    "8cfe9da88d5c43d184f3572e371ff4a6.mp4",
    "adf9268e5d5543a587defdde5d4c4edd.mp4",
    "afa4c87e3c1e42a197b7092e0e24040d.mp4",
)
LOG_DIRS = ("logs", "data", ".sintu", "production_runs", "runs")
ASSET_DIRS = ("generated_images", "generated_audio", "generated_assets", "assets")
TEXT_SUFFIXES = {".log", ".txt", ".json", ".jsonl"}
SECRET_TERMS = ("token", "secret", "password", "credential", "authorization", "api_key", "oauth", "session_uri")


def _bounded_text(value: str, limit: int) -> str:
    """Keep bounded head and tail so tool listings and final diagnostics both survive."""
    if len(value) <= limit:
        return value
    half = limit // 2
    return value[:half] + "\n...[output truncated]...\n" + value[-half:]


def run(command: list[str], timeout: int = 120) -> dict:
    try:
        result = subprocess.run(command, cwd=DATA_DIR, text=True, capture_output=True,
                                timeout=timeout, check=False)
        return {"returncode": result.returncode,
                "stdout": _bounded_text(result.stdout, 512_000),
                "stderr": _bounded_text(result.stderr, 128_000)}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"returncode": None, "stdout": "", "stderr": str(exc)[:300]}


def inspect_environment() -> dict:
    """Record Termux/Python/FFmpeg versions, executable paths and temp storage readiness."""
    def tool_details(name: str) -> dict:
        executable = shutil.which(name)
        if not executable:
            return {"available": False, "path": None, "version": None, "version_exit": None}
        version_result = run([executable, "-version"], timeout=10)
        lines = (version_result.get("stdout") or version_result.get("stderr") or "").splitlines()
        return {
            "available": version_result.get("returncode") == 0,
            "path": executable,
            "version": lines[0][:240] if lines else None,
            "version_exit": version_result.get("returncode"),
        }

    ffmpeg = tool_details("ffmpeg")
    ffprobe = tool_details("ffprobe")
    filter_result = (
        run([ffmpeg["path"], "-hide_banner", "-filters"], timeout=10)
        if ffmpeg.get("path") else {"returncode": None, "stdout": "", "stderr": "ffmpeg not found"}
    )
    filter_text = (filter_result.get("stdout") or "") + "\n" + (filter_result.get("stderr") or "")
    ffmpeg["filters"] = {
        name: bool(re.search(r"\b" + re.escape(name) + r"\b", filter_text))
        for name in ("blackdetect", "blackframe", "fps", "scale")
    }
    ffmpeg["filters_exit"] = filter_result.get("returncode")

    temp_path = Path(tempfile.gettempdir())
    temp_storage = {
        "path": str(temp_path),
        "exists": temp_path.is_dir(),
        "writable": bool(temp_path.is_dir() and os.access(temp_path, os.W_OK)),
        "write_test": False,
        "free_bytes": None,
        "error": "",
    }
    try:
        if temp_storage["writable"]:
            with tempfile.NamedTemporaryFile(
                prefix="sintu-forensic-", dir=temp_path, delete=True
            ) as temporary:
                temporary.write(b"sintu-forensic-temp-check")
                temporary.flush()
                temp_storage["write_test"] = True
    except OSError as exc:
        temp_storage["error"] = str(exc)[:250]
    try:
        if temp_path.exists():
            temp_storage["free_bytes"] = shutil.disk_usage(temp_path).free
    except OSError as exc:
        if not temp_storage["error"]:
            temp_storage["error"] = str(exc)[:250]

    return {
        "python": {"version": sys.version.split()[0], "executable": sys.executable},
        "platform": platform.platform(),
        "termux_version": os.environ.get("TERMUX_VERSION"),
        "ffmpeg": ffmpeg,
        "ffprobe": ffprobe,
        "frame_sampling": "Five FFprobe timestamp samples plus FFmpeg-extracted 64x64 PNG pixel verification; temporary thumbnails are removed after analysis",
        "temporary_storage": temp_storage,
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def redact_secrets(value: str) -> str:
    value = re.sub(r'(?i)(Bearer\s+)[^\s,"]+', r'\1[REDACTED]', value)
    value = re.sub(r'(?i)(access_token|refresh_token|client_secret|api_key|upload_id|session_uri|session_url)([=:][^&\s,"]+)', r'\1=[REDACTED]', value)
    value = re.sub(r'https://www\.googleapis\.com/upload/youtube/[^\s"]+', "[REDACTED_GOOGLE_UPLOAD_SESSION]", value)
    return value[:350]


def parse_black_intervals(stderr: str) -> list[list[float]]:
    return [[float(a), float(b)] for a, b in re.findall(
        r"black_start:([0-9.]+)\s+black_end:([0-9.]+)", stderr
    )]



def parse_black_frame_percentages(stderr: str) -> list[int]:
    """Extract FFmpeg blackframe pblack percentages from sampled decoded frames."""
    return [int(value) for value in re.findall(r"\bpblack:(\d+)\b", stderr)]


def summarize_black_frame_percentages(values: list[int]) -> dict:
    """Summarize evenly distributed blackframe samples; >=98% black pixels is a black frame."""
    if not values:
        return {
            "sampled_frame_count": 0,
            "black_frame_count": 0,
            "black_frame_percentage": None,
            "mean_black_pixel_percentage": None,
            "black_pixel_threshold": 16,
            "black_frame_cutoff_percent": 98,
            "pblack_values": [],
        }
    black_count = sum(value >= 98 for value in values)
    return {
        "sampled_frame_count": len(values),
        "black_frame_count": black_count,
        "black_frame_percentage": round(black_count / len(values) * 100, 2),
        "mean_black_pixel_percentage": round(sum(values) / len(values), 2),
        "black_pixel_threshold": 32,
        "black_frame_cutoff_percent": 98,
        "pblack_values": values[:30],
    }


def scan_text_logs(needles: tuple[str, ...]) -> list[dict]:
    matches = []
    for dirname in LOG_DIRS:
        base = DATA_DIR / dirname
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if len(matches) >= 20:
                return matches
            if (not path.is_file() or path.is_symlink() or path.suffix.lower() not in TEXT_SUFFIXES
                    or any(term in path.name.lower() for term in SECRET_TERMS)):
                continue
            try:
                if path.stat().st_size > 2 * 1024 * 1024:
                    continue
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for number, line in enumerate(lines, 1):
                if any(needle in line for needle in needles):
                    matches.append({"path": str(path.relative_to(DATA_DIR)),
                                    "line": number, "excerpt": redact_secrets(line)})
                    if len(matches) >= 20:
                        return matches
    return matches


def scan_database_records(needles: tuple[str, ...]) -> list[dict]:
    results = []
    for path in DATA_DIR.glob("*.sqlite*"):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            conn = sqlite3.connect("file:" + str(path) + "?mode=ro", uri=True, timeout=3)
            conn.row_factory = sqlite3.Row
            for table_row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                table = table_row["name"]
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
                    continue
                for column in conn.execute(f'PRAGMA table_info("{table}")'):
                    name = column["name"]
                    if (not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)
                            or any(term in name.lower() for term in SECRET_TERMS)):
                        continue
                    for needle in needles:
                        query = f'SELECT * FROM "{table}" WHERE CAST("{name}" AS TEXT) LIKE ? LIMIT 2'
                        for row in conn.execute(query, ("%" + needle + "%",)):
                            safe = {key: redact_secrets(str(row[key])) for key in row.keys()
                                    if not any(term in key.lower() for term in SECRET_TERMS)}
                            results.append({"db": path.name, "table": table,
                                            "column": name, "record": safe})
                            if len(results) >= 20:
                                conn.close()
                                return results
            conn.close()
        except (sqlite3.Error, OSError):
            continue
    return results


def inspect_asset(path: Path) -> dict:
    stat = path.stat()
    item = {"path": str(path.relative_to(DATA_DIR)), "size_bytes": stat.st_size,
            "modified_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()}
    if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
        try:
            with Image.open(path) as image:
                gray = image.convert("L").resize((32, 32))
                stats = ImageStat.Stat(gray)
                item.update({"image_size": list(image.size), "mean_luma": round(stats.mean[0], 2),
                             "luma_stddev": round(stats.stddev[0], 2),
                             "near_black": stats.mean[0] < 12 and stats.stddev[0] < 8})
        except (OSError, ValueError):
            item["image_error"] = "unreadable"
    return item


def nearby_assets(timestamp: float) -> list[dict]:
    found = []
    allowed = {".png", ".jpg", ".jpeg", ".webp", ".wav", ".mp3", ".m4a", ".aac", ".ogg", ".mp4"}
    for dirname in ASSET_DIRS:
        base = DATA_DIR / dirname
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.is_symlink() or path.suffix.lower() not in allowed:
                continue
            try:
                stat = path.stat()
                if abs(stat.st_mtime - timestamp) <= 900:
                    found.append(inspect_asset(path))
            except OSError:
                continue
            if len(found) >= 20:
                return found
    return found


def find_backups(path: Path) -> list[dict]:
    base = DATA_DIR / "media_backups"
    found = []
    if not base.is_dir():
        return found
    for candidate in base.glob("*/" + path.name):
        if not candidate.is_file() or candidate.is_symlink():
            continue
        try:
            stat = candidate.stat()
            found.append({
                "path": str(candidate.relative_to(DATA_DIR)),
                "size_bytes": stat.st_size,
                "sha256": sha256_file(candidate),
                "pre_repair_mtime_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            })
        except OSError:
            continue
    return sorted(found, key=lambda item: item["pre_repair_mtime_utc"], reverse=True)


def parse_creation_time(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def sample_decoded_frame(path: Path, seek_seconds: float, label: str) -> dict:
    """Find a decoded frame at/after a timestamp, recovering from inaccurate demuxer seeks."""
    seek = max(0.0, float(seek_seconds))
    sample = {"sample": label, "seek_seconds": round(seek, 6),
              "timestamp": None, "picture_type": None, "error": "",
              "sampling_method": "independent_seek"}
    result = run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-read_intervals", f"{seek:.6f}%+1",
        "-show_frames",
        "-show_entries", "frame=best_effort_timestamp_time,pict_type",
        "-of", "json", str(path),
    ], timeout=30)
    if result["returncode"] != 0:
        sample["error"] = (result["stderr"] or "ffprobe frame sample failed")[:250]
        return sample
    try:
        frames = json.loads(result["stdout"]).get("frames", [])
    except (TypeError, ValueError, json.JSONDecodeError):
        sample["error"] = "invalid ffprobe frame-sample JSON"
        return sample

    def closest_at_or_after(items):
        timed = []
        for frame in items:
            try:
                timestamp = float(frame.get("best_effort_timestamp_time"))
            except (TypeError, ValueError):
                continue
            if timestamp >= seek - 0.001:
                timed.append((abs(timestamp - seek), timestamp, frame))
        return min(timed, key=lambda item: item[0])[2] if timed else None

    chosen = closest_at_or_after(frames)
    if chosen is None:
        # FFprobe documents that interval seeking is not frame-accurate: some
        # demuxers seek back to an earlier keyframe, and the +1s window can end
        # before the requested timestamp. Retry from t=0 so decoding advances
        # sequentially through the target rather than trusting that seek point.
        fallback = run([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-read_intervals", f"0%+{seek + 1.0:.6f}",
            "-show_frames",
            "-show_entries", "frame=best_effort_timestamp_time,pict_type",
            "-of", "csv=p=0", str(path),
        ], timeout=120)
        if fallback["returncode"] != 0:
            detail = (fallback["stderr"] or "sequential ffprobe frame scan failed")[:180]
            sample["error"] = f"timestamp seek found no usable frame; sequential fallback failed: {detail}"
            return sample
        try:
            # Compact CSV avoids a large JSON array. The previous bounded
            # subprocess capture could cut the beginning of JSON for late
            # timestamps, making otherwise valid scans unparsable.
            fallback_frames = []
            for row in csv.reader(fallback["stdout"].splitlines()):
                if not row or not row[0].strip():
                    continue
                frame = {"best_effort_timestamp_time": row[0].strip()}
                if len(row) > 1 and row[1].strip():
                    frame["pict_type"] = row[1].strip()
                fallback_frames.append(frame)
        except (TypeError, ValueError, csv.Error):
            sample["error"] = "invalid sequential ffprobe frame-scan CSV"
            return sample
        chosen = closest_at_or_after(fallback_frames)
        if chosen is None:
            sample["error"] = (
                "no decoded frame found at requested timestamp" if not fallback_frames
                else "no decoded frame at or after the requested timestamp"
            )
            return sample
        sample["sampling_method"] = "sequential_fallback_from_start"

    sample["timestamp"] = chosen.get("best_effort_timestamp_time")
    sample["picture_type"] = chosen.get("pict_type")
    return sample


def extract_frame_pixel_verification(path: Path, timestamp: str, label: str) -> dict:
    """Extract a real decoded thumbnail and measure its pixels; temp PNG is always removed."""
    try:
        seek = float(timestamp)
        if not math.isfinite(seek) or seek < 0:
            raise ValueError("sample timestamp is not finite and non-negative")
        with tempfile.TemporaryDirectory(prefix="sintu-frame-") as temporary_dir:
            frame_path = Path(temporary_dir) / f"{label}.png"
            result = run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
                "-ss", f"{seek:.6f}", "-frames:v", "1",
                "-vf", "scale=64:64:flags=area", "-an", "-y", str(frame_path),
            ], timeout=120)
            if result["returncode"] != 0 or not frame_path.is_file() or frame_path.stat().st_size <= 0:
                detail = (result.get("stderr") or "FFmpeg did not create a decoded frame thumbnail")[:220]
                return {"status": "FAIL", "extraction_exit": result.get("returncode"),
                        "error": detail}
            with Image.open(frame_path) as extracted:
                gray = extracted.convert("L")
                stats = ImageStat.Stat(gray)
                histogram = gray.histogram()
                total = sum(histogram)
                if total <= 0:
                    return {"status": "FAIL", "extraction_exit": 0,
                            "error": "decoded frame thumbnail contains no pixels"}
                black_threshold = 16
                black_pixels = sum(histogram[:black_threshold + 1])
                mean_luma = float(stats.mean[0])
                luma_stddev = float(stats.stddev[0])
                black_percentage = black_pixels * 100.0 / total
                return {
                    "status": "PASS",
                    "extraction_exit": 0,
                    "resolution": f"{gray.width}x{gray.height}",
                    "mean_luma": round(mean_luma, 3),
                    "luma_stddev": round(luma_stddev, 3),
                    "black_pixel_threshold": black_threshold,
                    "black_pixel_percentage": round(black_percentage, 3),
                    "near_black": bool(mean_luma <= 2.0 and luma_stddev <= 2.0
                                       and black_percentage >= 99.5),
                    "method": "FFmpeg sequential timestamp decode -> 64x64 grayscale PNG -> Pillow pixel histogram",
                }
    except (OSError, TypeError, ValueError) as exc:
        return {"status": "FAIL", "extraction_exit": None, "error": str(exc)[:220]}


def analyze_av_sync(streams: list[dict], tolerance_seconds: float = 0.25) -> dict:
    """Compare decoded container stream timelines; this is timestamp sync evidence, not lip-sync perception."""
    video = next((item for item in streams if item.get("type") == "video"), None)
    audio = next((item for item in streams if item.get("type") == "audio"), None)
    if not video:
        return {"status": "missing_video_stream"}
    if not audio:
        return {"status": "missing_audio_stream"}
    try:
        video_start = float(video["start_time"])
        audio_start = float(audio["start_time"])
        video_duration = float(video["duration"])
        audio_duration = float(audio["duration"])
    except (KeyError, TypeError, ValueError):
        return {"status": "insufficient_stream_timing_metadata"}
    start_delta = audio_start - video_start
    end_delta = (audio_start + audio_duration) - (video_start + video_duration)
    duration_delta = audio_duration - video_duration
    in_sync = abs(start_delta) <= tolerance_seconds and abs(end_delta) <= max(tolerance_seconds, 0.5)
    return {
        "status": "within_tolerance" if in_sync else "out_of_sync",
        "audio_minus_video_start_seconds": round(start_delta, 6),
        "audio_minus_video_end_seconds": round(end_delta, 6),
        "audio_minus_video_duration_seconds": round(duration_delta, 6),
        "tolerance_seconds": tolerance_seconds,
        "method": "ffprobe stream start_time and duration comparison; not perceptual lip-sync validation",
    }


def inspect_video(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        return {"file": path.name, "exists": False, "safe_regular_file": False}
    stat = path.stat()
    probe = run(["ffprobe", "-v", "error", "-count_frames", "-show_streams",
                 "-show_format", "-of", "json", str(path)])
    info = {"format": None, "duration_seconds": None, "streams": []}
    if probe["returncode"] == 0:
        try:
            raw = json.loads(probe["stdout"])
            fmt = raw.get("format", {})
            info["format"] = fmt.get("format_name")
            parsed_duration = float(fmt.get("duration") or 0)
            if math.isfinite(parsed_duration) and parsed_duration > 0:
                info["duration_seconds"] = parsed_duration
            else:
                info["duration_seconds"] = None
                info["duration_error"] = "duration is not finite and positive"
            info["container_creation_time"] = (fmt.get("tags") or {}).get("creation_time")
            for stream in raw.get("streams", []):
                info["streams"].append({
                    "type": stream.get("codec_type"), "codec": stream.get("codec_name"),
                    "profile": stream.get("profile"), "resolution": (
                        f'{stream.get("width")}x{stream.get("height")}' if stream.get("width") else None),
                    "pixel_format": stream.get("pix_fmt"), "frame_rate": stream.get("avg_frame_rate"),
                    "frame_count": stream.get("nb_read_frames"), "sample_rate": stream.get("sample_rate"),
                    "channels": stream.get("channels"), "duration": stream.get("duration"),
                    "start_time": stream.get("start_time"),
                })
        except (ValueError, TypeError, json.JSONDecodeError):
            info["parse_error"] = "invalid ffprobe JSON"

    black = run(["ffmpeg", "-hide_banner", "-i", str(path), "-vf",
                 "blackdetect=d=0.10:pix_th=0.03", "-an", "-f", "null", "-"])
    decode = run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"])
    intervals = parse_black_intervals(black["stderr"])
    duration = info["duration_seconds"] or 0
    duration_valid = isinstance(duration, (int, float)) and math.isfinite(duration) and duration > 0
    if duration_valid:
        sample_fps = 30.0 / duration
        blackframe = run([
            "ffmpeg", "-hide_banner", "-i", str(path), "-vf",
            f"fps={sample_fps:.8f},blackframe=amount=0:threshold=16",
            "-an", "-frames:v", "30", "-f", "null", "-",
        ])
        blackframe_values = parse_black_frame_percentages(blackframe["stderr"])
        black_frame_metrics = summarize_black_frame_percentages(blackframe_values)
        blackframe_error = (
            "" if blackframe["returncode"] == 0 and blackframe_values
            else (blackframe["stderr"] or "no blackframe samples decoded")[:250]
        )
    else:
        blackframe = {"returncode": None, "stderr": "invalid or missing video duration"}
        black_frame_metrics = summarize_black_frame_percentages([])
        blackframe_error = "invalid or missing video duration; black-frame sampling skipped"
    blackdetect_full_black = bool(
        duration_valid and any(a <= 0.1 and b >= duration * 0.95 for a, b in intervals)
    )

    fps = 0.0
    for stream in info["streams"]:
        if stream.get("type") == "video":
            try:
                numerator, denominator = (int(part) for part in str(stream.get("frame_rate", "0/1")).split("/", 1))
                fps = numerator / denominator if denominator else 0.0
            except (TypeError, ValueError, ZeroDivisionError):
                fps = 0.0
            break
    if duration_valid:
        end_seek = max(0.0, duration - (1.0 / fps if fps > 0 else 0.1))
        # Five evenly distributed sample points catch black/blank intervals
        # that a first/middle/last-only probe can miss.
        sample_points = [
            ("first", 0.0),
            ("quarter", duration * 0.25),
            ("middle", duration * 0.50),
            ("three_quarter", duration * 0.75),
            ("last", end_seek),
        ]
        samples = [
            sample_decoded_frame(path, timestamp, label)
            for label, timestamp in sample_points
        ]
        for sample in samples:
            if sample.get("error") or not sample.get("timestamp"):
                sample["pixel_verification"] = {
                    "status": "NOT_ATTEMPTED",
                    "extraction_exit": None,
                    "error": sample.get("error") or "decoded timestamp unavailable",
                }
            else:
                sample["pixel_verification"] = extract_frame_pixel_verification(
                    path, sample["timestamp"], sample["sample"]
                )
    else:
        samples = [{
            "sample": label, "seek_seconds": None, "timestamp": None,
            "picture_type": None, "sampling_method": "not_attempted",
            "error": "invalid or missing video duration; frame sampling skipped",
        } for label in ("first", "quarter", "middle", "three_quarter", "last")]
        for sample in samples:
            sample["pixel_verification"] = {
                "status": "NOT_ATTEMPTED", "extraction_exit": None,
                "error": sample["error"],
            }

    pixel_probe_exit = 0 if len(samples) == 5 and all(
        sample.get("pixel_verification", {}).get("status") == "PASS"
        for sample in samples
    ) else 1
    pixel_summary = {
        "sampled_frame_count": sum(
            sample.get("pixel_verification", {}).get("status") == "PASS"
            for sample in samples
        ),
        "near_black_sample_count": sum(
            sample.get("pixel_verification", {}).get("near_black") is True
            for sample in samples
        ),
        "samples": [
            {
                "sample": sample.get("sample"),
                "timestamp": sample.get("timestamp"),
                "mean_luma": (sample.get("pixel_verification") or {}).get("mean_luma"),
                "luma_stddev": (sample.get("pixel_verification") or {}).get("luma_stddev"),
                "black_pixel_percentage": (sample.get("pixel_verification") or {}).get("black_pixel_percentage"),
                "near_black": (sample.get("pixel_verification") or {}).get("near_black"),
                "status": (sample.get("pixel_verification") or {}).get("status"),
            }
            for sample in samples
        ],
    }

    full_black = bool(
        blackdetect_full_black
        and black_frame_metrics.get("black_frame_count", 0) >= 29
        and pixel_summary.get("near_black_sample_count", 0) == 5
    )

    backups = find_backups(path)
    creation_epoch = parse_creation_time(info.get("container_creation_time"))
    if creation_epoch is not None:
        reference_epoch = creation_epoch
        reference_source = "container-creation-time-preserved-by-map-metadata"
    elif backups:
        reference_epoch = parse_creation_time(backups[0]["pre_repair_mtime_utc"])
        reference_source = "pre-repair-backup-mtime"
    else:
        reference_epoch = stat.st_mtime
        reference_source = "current-file-mtime-may-reflect-audio-repair"
    return {
        "file": path.name, "exists": True, "safe_regular_file": True,
        "readable": os.access(path, os.R_OK),
        "permissions_octal": oct(stat.st_mode & 0o777),
        "size_bytes": stat.st_size,
        "sha256": sha256_file(path),
        "modified_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "pre_repair_backups": backups,
        "asset_reference_time_utc": datetime.fromtimestamp(reference_epoch, timezone.utc).isoformat() if reference_epoch else None,
        "asset_reference_time_source": reference_source,
        "ffprobe_exit": probe["returncode"], "metadata": info,
        "av_sync": analyze_av_sync(info["streams"]),
        "blackdetect_exit": black["returncode"], "black_intervals": intervals,
        "blackframe_exit": blackframe["returncode"],
        "black_frame_metrics": black_frame_metrics, "blackframe_error": blackframe_error,
        "blackdetect_full_duration_black": blackdetect_full_black,
        "full_duration_black": full_black, "decode_exit": decode["returncode"],
        "decode_errors": redact_secrets(decode["stderr"]) if decode["stderr"] else "",
        "decoded_frame_samples": samples,
        "frame_probe_exit": 0 if all(not sample["error"] for sample in samples) else 1,
        "frame_probe_error": "; ".join(sample["error"] for sample in samples if sample["error"])[:250],
        "pixel_probe_exit": pixel_probe_exit,
        "pixel_verification": pixel_summary,
    }


def has_forensic_tool_failure(item: dict) -> bool:
    """Distinguish a completed black-video finding from failed forensic tooling."""
    if not item.get("exists") or not item.get("safe_regular_file"):
        return True
    for key in ("ffprobe_exit", "blackdetect_exit", "blackframe_exit", "decode_exit", "frame_probe_exit", "pixel_probe_exit"):
        if item.get(key) != 0:
            return True
    metadata = item.get("metadata") or {}
    try:
        duration = float(metadata.get("duration_seconds"))
    except (TypeError, ValueError):
        return True
    if (metadata.get("parse_error") or not metadata.get("format")
            or not math.isfinite(duration) or duration <= 0):
        return True
    if not any(stream.get("type") == "video" for stream in metadata.get("streams", [])):
        return True
    black_metrics = item.get("black_frame_metrics") or {}
    if black_metrics.get("sampled_frame_count") != 30:
        return True
    samples = item.get("decoded_frame_samples") or []
    return len(samples) != 5 or any(
        sample.get("error") or not sample.get("timestamp")
        or (sample.get("pixel_verification") or {}).get("status") != "PASS"
        for sample in samples
    )


def compact_forensic_summary(report: dict) -> dict:
    """Build a compact five-target footer for the Termux relay's bounded comment tail."""
    targets = []
    for item in report.get("targets", []):
        metadata = item.get("metadata") or {}
        streams = [
            {
                "type": stream.get("type"), "codec": stream.get("codec"),
                "res": stream.get("resolution"), "pix": stream.get("pixel_format"),
                "frames": stream.get("frame_count"), "rate": stream.get("sample_rate"),
                "ch": stream.get("channels"),
            }
            for stream in metadata.get("streams", [])
        ]
        metrics = item.get("black_frame_metrics") or {}
        targets.append({
            "file": item.get("file"),
            "readable": item.get("readable"),
            "permissions": item.get("permissions_octal"),
            "bytes": item.get("size_bytes"),
            "sha256": item.get("sha256"),
            "duration": metadata.get("duration_seconds"),
            "streams": streams,
            "full_black": item.get("full_duration_black"),
            "blackdetect_full_black": item.get("blackdetect_full_duration_black"),
            "black_intervals": item.get("black_intervals", []),
            "exit": [
                item.get("ffprobe_exit"), item.get("blackdetect_exit"),
                item.get("blackframe_exit"), item.get("decode_exit"),
                item.get("frame_probe_exit"), item.get("pixel_probe_exit"),
            ],
            "black_frames": {
                "count": metrics.get("sampled_frame_count"),
                "black": metrics.get("black_frame_count"),
                "pct": metrics.get("black_frame_percentage"),
                "mean": metrics.get("mean_black_pixel_percentage"),
                "pblack": metrics.get("pblack_values", [])[:30],
                "err": str(item.get("blackframe_error", ""))[:60],
            },
            "samples": [
                [sample.get("sample"), sample.get("seek_seconds"), sample.get("timestamp"),
                 str(sample.get("error", ""))[:60],
                 (sample.get("pixel_verification") or {}).get("status"),
                 (sample.get("pixel_verification") or {}).get("mean_luma"),
                 (sample.get("pixel_verification") or {}).get("black_pixel_percentage"),
                 (sample.get("pixel_verification") or {}).get("near_black")]
                for sample in item.get("decoded_frame_samples", [])
            ],
            "backups": [
                [str(backup.get("path", ""))[-100:], backup.get("size_bytes"), backup.get("sha256")]
                for backup in item.get("pre_repair_backups", [])
            ],
            "reference_time": item.get("asset_reference_time_utc"),
        })
    environment = report.get("environment") or {}
    ffmpeg = environment.get("ffmpeg") or {}
    ffprobe = environment.get("ffprobe") or {}
    temporary = environment.get("temporary_storage") or {}
    compact_environment = {
        "python": (environment.get("python") or {}).get("version"),
        "platform": environment.get("platform"),
        "termux": environment.get("termux_version"),
        "ffmpeg": [ffmpeg.get("path"), ffmpeg.get("version"), ffmpeg.get("filters")],
        "ffprobe": [ffprobe.get("path"), ffprobe.get("version")],
        "temp": [temporary.get("path"), temporary.get("write_test"), temporary.get("free_bytes")],
    }
    return {
        "status": report.get("status"),
        "environment": compact_environment,
        "summary": {
            "targets": (report.get("summary") or {}).get("target_count"),
            "black": (report.get("summary") or {}).get("full_duration_black_count"),
            "tool_failures": (report.get("summary") or {}).get("forensic_tool_failure_count"),
        },
        "targets": targets,
        "assets": [
            [str(asset.get("path", ""))[-64:], asset.get("mean_luma"),
             asset.get("near_black"), asset.get("modified_utc")]
            for asset in report.get("candidate_source_assets", [])[:3]
        ],
        "logs": [
            [str(match.get("path", ""))[-64:], match.get("line"),
             str(match.get("excerpt", ""))[:60]]
            for match in report.get("production_log_matches", [])[:2]
        ],
        "db": [
            [str(match.get("db", ""))[-48:], match.get("table"), match.get("column"),
             str((match.get("record") or {}).get("status", ""))[:32]]
            for match in report.get("production_database_matches", [])[:2]
        ],
        "safety": report.get("safety", {}),
    }

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.parse_args()
    videos = [inspect_video(MEDIA_DIR / name) for name in TARGETS]
    assets = {}
    for video in videos:
        if video.get("exists"):
            reference_time = video.get("asset_reference_time_utc") or video["modified_utc"]
            for asset in nearby_assets(datetime.fromisoformat(reference_time).timestamp()):
                assets[asset["path"]] = asset
    needles = tuple(value for name in TARGETS for value in (name, Path(name).stem))
    tool_failures = sum(1 for item in videos if has_forensic_tool_failure(item))
    report = {
        "status": "READ_ONLY_FORENSICS",
        "environment": inspect_environment(),
        "summary": {
            "target_count": len(videos),
            "inspected_count": sum(1 for item in videos if item.get("exists")),
            "full_duration_black_count": sum(1 for item in videos if item.get("full_duration_black")),
            "av_sync_failure_count": sum(1 for item in videos if item.get("av_sync", {}).get("status") != "within_tolerance"),
            "forensic_tool_failure_count": tool_failures,
        },
        "targets": videos,
        "candidate_source_assets": list(assets.values()),
        "production_log_matches": scan_text_logs(needles),
        "production_database_matches": scan_database_records(needles),
        "safety": {"files_modified": False, "files_deleted": False, "files_moved": False,
                   "uploads_performed": False, "public_publishing_performed": False},
        "note": "The audio repair used copy2 backups before replacing MP4s; backup mtimes are preferred for source correlation because current MP4 mtimes may reflect audio repair. Technical evidence only; no repair, quarantine, deletion, regeneration, or upload was performed.",
    }
    print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    # The GitHub Termux relay retains only the final 8,000 output characters.
    # Keep per-file hashes, streams, black intervals, samples, backups and safety
    # flags in a compact footer so no target's evidence is lost to truncation.
    footer = compact_forensic_summary(report)
    print("SINTU_FORENSICS_SUMMARY=" + json.dumps(footer, ensure_ascii=False, separators=(",", ":")))
    return 1 if tool_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
