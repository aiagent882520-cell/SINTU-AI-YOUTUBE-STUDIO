#!/usr/bin/env python3
"""Free, local-first SINTU project health audit for CI and Termux.

Checks Python compilation, the test suite, media tool availability, and every
MP4 in generated_videos (container metadata, video stream, duration, and
near-total black-frame detection). No network, paid API, or publishing action.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_check(name: str, command: list[str], results: list[dict], cwd: Path = ROOT) -> bool:
    proc = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, check=False)
    results.append({"check": name, "status": "PASS" if proc.returncode == 0 else "FAIL",
                    "exit_code": proc.returncode, "output": proc.stdout[-12000:]})
    return proc.returncode == 0


def validate_mp4_metadata(data: dict) -> dict:
    """Validate the Android-friendly MP4 profile used by the renderer."""
    import math

    if not isinstance(data, dict):
        raise ValueError("ffprobe metadata is not an object")
    format_info = data.get("format") or {}
    format_names = str(format_info.get("format_name", "")).lower().split(",")
    if not ({"mp4", "mov"} & set(format_names)):
        raise ValueError("container is not MP4/MOV")
    try:
        duration = float(format_info.get("duration", 0))
    except (TypeError, ValueError):
        duration = 0
    if not math.isfinite(duration) or duration < 1:
        raise ValueError("duration is missing, invalid, or below 1 second")

    streams = data.get("streams") or []
    video_stream = next((item for item in streams if item.get("codec_type") == "video"), None)
    if not video_stream:
        raise ValueError("missing video stream")
    try:
        width, height = int(video_stream.get("width", 0)), int(video_stream.get("height", 0))
    except (TypeError, ValueError):
        width, height = 0, 0
    if width < 64 or height < 64:
        raise ValueError("video resolution is missing or below 64px")
    if str(video_stream.get("codec_name", "")).lower() != "h264":
        raise ValueError("video codec must be H.264")
    if str(video_stream.get("pix_fmt", "")).lower() != "yuv420p":
        raise ValueError("video pixel format must be yuv420p")

    audio_stream = next((item for item in streams if item.get("codec_type") == "audio"), None)
    audio_details = None
    if audio_stream:
        try:
            sample_rate = int(audio_stream.get("sample_rate", 0))
            channels = int(audio_stream.get("channels", 0))
        except (TypeError, ValueError):
            sample_rate, channels = 0, 0
        if str(audio_stream.get("codec_name", "")).lower() != "aac":
            raise ValueError("audio codec must be AAC")
        if sample_rate != 48000:
            raise ValueError("audio sample rate must be 48000 Hz")
        if channels != 2:
            raise ValueError("audio must be 2-channel stereo")
        audio_details = {"codec": "aac", "sample_rate": sample_rate, "channels": channels}

    return {
        "duration_seconds": round(duration, 2),
        "resolution": f"{width}x{height}",
        "video_codec": "h264",
        "pixel_format": "yuv420p",
        "audio": audio_details,
    }


def audit_media(path: Path, results: list[dict]) -> bool:
    ffprobe = shutil.which("ffprobe")
    ffmpeg = shutil.which("ffmpeg")
    if not ffprobe or not ffmpeg:
        results.append({"check": "media-tools", "status": "WARN",
                        "output": "ffmpeg/ffprobe unavailable; media audit skipped"})
        return True
    ok = True
    for video in sorted(path.glob("*.mp4")):
        probe = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries",
             "format=duration,size,format_name:stream=codec_type,codec_name,width,height,pix_fmt,sample_rate,channels",
             "-of", "json", str(video)],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if probe.returncode:
            results.append({"check": f"media:{video.name}", "status": "FAIL",
                            "output": probe.stderr[-2000:]})
            ok = False
            continue
        try:
            metadata = validate_mp4_metadata(json.loads(probe.stdout))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            results.append({"check": f"media:{video.name}", "status": "FAIL",
                            "output": str(exc)})
            ok = False
            continue
        black = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(video), "-vf",
             "blackdetect=d=0.5:pix_th=0.10", "-an", "-f", "null", "-"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if black.returncode != 0:
            results.append({"check": f"media:{video.name}", "status": "FAIL",
                            "output": black.stderr[-2000:]})
            ok = False
            continue
        intervals = [(float(a), float(b)) for a, b in re.findall(
            r"black_start:([0-9.]+)\s+black_end:([0-9.]+)", black.stderr)]
        full_black = any(start <= 0.1 and end >= metadata["duration_seconds"] * 0.95
                         for start, end in intervals)
        status = "FAIL" if full_black else "PASS"
        results.append({"check": f"media:{video.name}", "status": status,
                        **metadata, "black_intervals": intervals})
        ok = ok and not full_black
    if not any(path.glob("*.mp4")):
        results.append({"check": "generated-videos", "status": "INFO",
                        "output": "No generated MP4 files present; nothing to inspect"})
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-tests", action="store_true",
                        help="Skip pytest (useful for a fast on-device media-only check)")
    parser.add_argument("--media-dir", type=Path, default=ROOT / "generated_videos")
    parser.add_argument("--report", type=Path, default=None, help="Also write the JSON report to this path")
    args = parser.parse_args()
    results: list[dict] = []
    ok = run_check("python-compile", [sys.executable, "-m", "compileall", "-q", "app", "scripts"], results)
    if not args.skip_tests:
        ok = run_check("pytest", [sys.executable, "-m", "pytest", "-q"], results) and ok
    ok = audit_media(args.media_dir, results) and ok
    summary = {"project": "SINTU AI YOUTUBE STUDIO", "status": "PASS" if ok else "FAIL",
               "checks": results, "paid_services_used": False, "publishing_performed": False}
    rendered = json.dumps(summary, ensure_ascii=False, indent=2)
    print(rendered)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
