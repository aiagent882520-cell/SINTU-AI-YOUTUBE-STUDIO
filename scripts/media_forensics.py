#!/usr/bin/env python3
"""Read-only forensic report for the five known black MP4s. Never edits media."""
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
        return {"returncode": result.returncode, "stdout": result.stdout[-12000:],
                "stderr": result.stderr[-12000:]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"returncode": None, "stdout": "", "stderr": str(exc)[:500]}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_black_intervals(stderr: str) -> list[list[float]]:
    return [[float(a), float(b)] for a, b in re.findall(
        r"black_start:([0-9.]+)\s+black_end:([0-9.]+)", stderr
    )]


def redact_secrets(value: str) -> str:
    value = re.sub(r'(?i)(Bearer\s+)[^\s,"]+', r'\1[REDACTED]', value)
    value = re.sub(r'(?i)(access_token|refresh_token|client_secret|api_key|upload_id)([=:][^&\s,"]+)', r'\1=[REDACTED]', value)
    value = re.sub(r'https://www\.googleapis\.com/upload/youtube/[^\s"]+', "[REDACTED_GOOGLE_UPLOAD_SESSION]", value)
    return value[:500]


def scan_text_logs(needles: tuple[str, ...]) -> list[dict]:
    matches = []
    roots = [DATA_DIR / item for item in LOG_DIRS]
    for base in roots:
        if not base.exists() or not base.is_dir():
            continue
        for path in base.rglob("*"):
            if len(matches) >= 80:
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
                    if len(matches) >= 80:
                        return matches
    return matches


def scan_database_records(needles: tuple[str, ...]) -> list[dict]:
    results = []
    for path in DATA_DIR.glob("*.sqlite*"):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            uri = "file:" + str(path) + "?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=3)
            conn.row_factory = sqlite3.Row
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            for table_row in tables:
                table = table_row["name"]
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
                    continue
                columns = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
                for column in columns:
                    name = column["name"]
                    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                        continue
                    if any(term in name.lower() for term in SECRET_TERMS):
                        continue
                    for needle in needles:
                        query = f'SELECT * FROM "{table}" WHERE CAST("{name}" AS TEXT) LIKE ? LIMIT 3'
                        for row in conn.execute(query, ("%" + needle + "%",)).fetchall():
                            safe = {key: redact_secrets(str(row[key])) for key in row.keys()
                                    if not any(term in key.lower() for term in SECRET_TERMS)}
                            results.append({"database": path.name, "table": table,
                                            "matched_column": name, "record": safe})
                            if len(results) >= 80:
                                conn.close()
                                return results
            conn.close()
        except (sqlite3.Error, OSError):
            continue
    return results


def nearby_assets(timestamp: float) -> list[dict]:
    found = []
    allowed = {".png", ".jpg", ".jpeg", ".webp", ".wav", ".mp3", ".m4a", ".aac", ".ogg", ".mp4"}
    for dirname in ASSET_DIRS:
        base = DATA_DIR / dirname
        if not base.exists() or not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.is_symlink() or path.suffix.lower() not in allowed:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            if abs(stat.st_mtime - timestamp) <= 900:
                found.append({"path": str(path.relative_to(DATA_DIR)), "size_bytes": stat.st_size,
                              "modified_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()})
                if len(found) >= 60:
                    return found
    return found


def inspect_video(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        return {"file": path.name, "exists": False, "safe_regular_file": False}
    stat = path.stat()
    probe = run(["ffprobe", "-v", "error", "-count_frames", "-show_streams",
                 "-show_format", "-of", "json", str(path)])
    metadata = {}
    if probe["returncode"] == 0:
        try:
            raw = json.loads(probe["stdout"])
            metadata = {"format": raw.get("format", {}),
                        "streams": [{k: s.get(k) for k in (
                            "index", "codec_type", "codec_name", "profile", "width", "height",
                            "pix_fmt", "r_frame_rate", "avg_frame_rate", "time_base",
                            "start_time", "duration", "nb_read_frames", "sample_rate", "channels"
                        )} for s in raw.get("streams", [])]}
        except json.JSONDecodeError:
            metadata = {"parse_error": "ffprobe JSON invalid"}
    black = run(["ffmpeg", "-hide_banner", "-i", str(path), "-vf",
                 "blackdetect=d=0.10:pix_th=0.10", "-an", "-f", "null", "-"])
    decode = run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"])
    duration = 0.0
    try:
        duration = float(metadata.get("format", {}).get("duration") or 0)
    except (TypeError, ValueError):
        pass
    intervals = parse_black_intervals(black["stderr"])
    full_black = bool(duration and any(start <= 0.1 and end >= duration * 0.95
                                       for start, end in intervals))
    frames = []
    for label, seek in (("start", 0), ("middle", max(0, duration / 2)), ("end", max(0, duration - 0.2))):
        sample = run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                      "-show_entries", "frame=best_effort_timestamp_time,pict_type",
                      "-read_intervals", f"{seek}%+#2", "-of", "csv=p=0", str(path)], timeout=30)
        frames.append({"sample": label, "seek_seconds": round(seek, 3),
                       "timestamps": sample["stdout"].strip().splitlines()[:2],
                       "error": sample["stderr"][:300] if sample["returncode"] else ""})
    needles = (path.name, path.stem)
    return {
        "file": path.name, "exists": True, "safe_regular_file": True,
        "size_bytes": stat.st_size, "sha256": sha256_file(path),
        "modified_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "ffprobe_returncode": probe["returncode"], "metadata": metadata,
        "blackdetect_returncode": black["returncode"], "black_intervals": intervals,
        "full_duration_black": full_black, "decode_returncode": decode["returncode"],
        "decode_errors": decode["stderr"][:4000], "frame_timestamp_samples": frames,
        "nearby_source_assets": nearby_assets(stat.st_mtime),
        "production_log_matches": scan_text_logs(needles),
        "production_database_matches": scan_database_records(needles),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = {
        "status": "READ_ONLY_FORENSICS",
        "data_dir": str(DATA_DIR),
        "media_dir": str(MEDIA_DIR),
        "targets": [inspect_video(MEDIA_DIR / name) for name in TARGETS],
        "safety": {"files_modified": False, "files_deleted": False, "files_moved": False,
                   "uploads_performed": False, "public_publishing_performed": False},
        "note": "This report identifies technical symptoms and matching local provenance. It does not repair or quarantine media.",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if all(item.get("exists") for item in report["targets"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
