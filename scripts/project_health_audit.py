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
             "format=duration,size:stream=codec_type,width,height", "-of", "json", str(video)],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if probe.returncode:
            results.append({"check": f"media:{video.name}", "status": "FAIL",
                            "output": probe.stderr[-2000:]})
            ok = False
            continue
        try:
            data = json.loads(probe.stdout)
            duration = float(data.get("format", {}).get("duration", 0))
            streams = data.get("streams", [])
            video_stream = next((x for x in streams if x.get("codec_type") == "video"), None)
            if not video_stream or duration < 1 or int(video_stream.get("width", 0)) < 64 or int(video_stream.get("height", 0)) < 64:
                raise ValueError("missing video stream, duration < 1s, or resolution below 64px")
        except (ValueError, TypeError, StopIteration) as exc:
            results.append({"check": f"media:{video.name}", "status": "FAIL", "output": str(exc)})
            ok = False
            continue
        black = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(video), "-vf",
             "blackdetect=d=0.5:pix_th=0.10", "-an", "-f", "null", "-"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        intervals = [(float(a), float(b)) for a, b in re.findall(
            r"black_start:([0-9.]+)\s+black_end:([0-9.]+)", black.stderr)]
        full_black = any(start <= 0.1 and end >= duration * 0.95 for start, end in intervals)
        status = "FAIL" if full_black else "PASS"
        results.append({"check": f"media:{video.name}", "status": status,
                        "duration_seconds": round(duration, 2),
                        "resolution": f"{video_stream['width']}x{video_stream['height']}",
                        "black_intervals": intervals})
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
