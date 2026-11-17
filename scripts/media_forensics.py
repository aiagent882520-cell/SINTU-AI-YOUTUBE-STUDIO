#!/usr/bin/env python3
"""Compact, read-only forensic report for the five known black MP4s."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
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
SECRET_TERMS = ("token", "secret", "password", "credential", "authorization", "api_key", "oauth")


def run(command: list[str], timeout: int = 120) -> dict:
    try:
        result = subprocess.run(command, cwd=DATA_DIR, text=True, capture_output=True,
                                timeout=timeout, check=False)
        return {"returncode": result.returncode, "stdout": result.stdout[-16000:],
                "stderr": result.stderr[-6000:]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"returncode": None, "stdout": "", "stderr": str(exc)[:300]}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def redact_secrets(value: str) -> str:
    value = re.sub(r'(?i)(Bearer\s+)[^\s,"]+', r'\1[REDACTED]', value)
    value = re.sub(r'(?i)(access_token|refresh_token|client_secret|api_key|upload_id)([=:][^&\s,"]+)', r'\1=[REDACTED]', value)
    value = re.sub(r'https://www\.googleapis\.com/upload/youtube/[^\s"]+', "[REDACTED_GOOGLE_UPLOAD_SESSION]", value)
    return value[:350]


def parse_black_intervals(stderr: str) -> list[list[float]]:
    return [[float(a), float(b)] for a, b in re.findall(
        r"black_start:([0-9.]+)\s+black_end:([0-9.]+)", stderr
    )]


def scan_text_logs(needles: tuple[str, ...]) -> list[dict]:
    matches = []
    for dirname in LOG_DIRS:
        base = DATA_DIR / dirname
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if len(matches) >= 20:
                return matches
            if (not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES
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
            info["duration_seconds"] = float(fmt.get("duration") or 0)
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
                 "blackdetect=d=0.10:pix_th=0.10", "-an", "-f", "null", "-"])
    decode = run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"])
    intervals = parse_black_intervals(black["stderr"])
    duration = info["duration_seconds"] or 0
    full_black = bool(duration and any(a <= 0.1 and b >= duration * 0.95 for a, b in intervals))

    frames_result = run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                         "-show_frames", "-show_entries", "frame=best_effort_timestamp_time,pict_type",
                         "-of", "csv=p=0", str(path)], timeout=45)
    frame_lines = frames_result["stdout"].splitlines()
    samples = []
    if frame_lines:
        for label, index in (("first", 0), ("middle", len(frame_lines) // 2), ("last", len(frame_lines) - 1)):
            parts = frame_lines[index].split(",")
            samples.append({"sample": label, "timestamp": parts[0] if parts else "",
                            "picture_type": parts[1] if len(parts) > 1 else ""})

    backups = find_backups(path)
    creation_epoch = parse_creation_time(info.get("container_creation_time"))
    if backups:
        reference_epoch = parse_creation_time(backups[0]["pre_repair_mtime_utc"])
        reference_source = "pre-repair-backup-mtime"
    elif creation_epoch is not None:
        reference_epoch = creation_epoch
        reference_source = "container-creation-time"
    else:
        reference_epoch = stat.st_mtime
        reference_source = "current-file-mtime-may-reflect-audio-repair"
    return {
        "file": path.name, "exists": True, "size_bytes": stat.st_size,
        "sha256": sha256_file(path),
        "modified_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "pre_repair_backups": backups,
        "asset_reference_time_utc": datetime.fromtimestamp(reference_epoch, timezone.utc).isoformat() if reference_epoch else None,
        "asset_reference_time_source": reference_source,
        "ffprobe_exit": probe["returncode"], "metadata": info,
        "blackdetect_exit": black["returncode"], "black_intervals": intervals,
        "full_duration_black": full_black, "decode_exit": decode["returncode"],
        "decode_errors": redact_secrets(decode["stderr"]) if decode["stderr"] else "",
        "decoded_frame_samples": samples, "frame_probe_exit": frames_result["returncode"],
        "frame_probe_error": frames_result["stderr"][:250] if frames_result["returncode"] else "",
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
    report = {
        "status": "READ_ONLY_FORENSICS",
        "targets": videos,
        "candidate_source_assets": list(assets.values()),
        "production_log_matches": scan_text_logs(needles),
        "production_database_matches": scan_database_records(needles),
        "safety": {"files_modified": False, "files_deleted": False, "files_moved": False,
                   "uploads_performed": False, "public_publishing_performed": False},
        "note": "The audio repair used copy2 backups before replacing MP4s; backup mtimes are preferred for source correlation because current MP4 mtimes may reflect audio repair. Technical evidence only; no repair, quarantine, deletion, regeneration, or upload was performed.",
    }
    print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    return 0 if all(item.get("exists") for item in videos) else 1


if __name__ == "__main__":
    raise SystemExit(main())
