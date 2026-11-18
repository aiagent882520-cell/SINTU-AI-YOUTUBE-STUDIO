#!/usr/bin/env python3
"""Read-only consolidated SINTU Termux/device diagnostic.

Writes timestamped JSON and human-readable reports. It never installs software,
downloads models, starts rendering, changes services, modifies media, or uploads.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.getenv("SINTU_DATA_DIR", str(ROOT))).expanduser().resolve()
MEDIA_DIR = DATA_DIR / "generated_videos"
ANDROID_APK_DIRS = (ROOT / "android/app/build/outputs/apk", ROOT / "dist")


def run(command: list[str], timeout: int = 20, cwd: Path = ROOT) -> dict:
    try:
        result = subprocess.run(command, cwd=cwd, text=True, capture_output=True,
                                timeout=timeout, check=False)
        return {"exit_code": result.returncode,
                "stdout": result.stdout[-4000:], "stderr": result.stderr[-2000:]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"exit_code": None, "error": f"{type(exc).__name__}: {str(exc)[:240]}"}


def version(binary: str) -> dict:
    path = shutil.which(binary)
    if not path:
        return {"available": False, "path": None, "version": None}
    result = run([path, "-version"], timeout=8)
    output = result.get("stdout") or result.get("stderr") or ""
    return {"available": result.get("exit_code") == 0, "path": path,
            "version": output.splitlines()[0][:240] if output else None,
            "exit_code": result.get("exit_code")}


def backend_probe() -> dict:
    base = os.getenv("SINTU_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    url = base + "/api/health"
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "SINTU-Termux-Diagnostic/1.0"})
        with urllib.request.urlopen(request, timeout=3) as response:
            body = response.read(16_384).decode("utf-8", "replace")
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = {"body_preview": body[:500]}
            return {"url": url, "reachable": response.status == 200,
                    "http_status": response.status, "response": payload}
    except (OSError, urllib.error.URLError, TimeoutError, ValueError) as exc:
        return {"url": url, "reachable": False, "error": type(exc).__name__}


def media_inventory() -> dict:
    files = []
    if MEDIA_DIR.is_dir():
        for path in sorted(MEDIA_DIR.glob("*.mp4")):
            try:
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                stat = path.stat()
                files.append({"name": path.name, "bytes": stat.st_size,
                              "sha256": digest.hexdigest(),
                              "modified_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()})
            except OSError as exc:
                files.append({"name": path.name, "error": type(exc).__name__})
    return {"directory": str(MEDIA_DIR), "count": len(files), "files": files}


def build_report() -> dict:
    git_head = run(["git", "rev-parse", "HEAD"])
    git_status = run(["git", "status", "--short", "--branch"])
    pip_check = run([sys.executable, "-m", "pip", "check"], timeout=60)
    apk_files = []
    for directory in ANDROID_APK_DIRS:
        if directory.is_dir():
            apk_files.extend(str(path.relative_to(ROOT)) for path in directory.rglob("*.apk"))
    engine = run([sys.executable, "scripts/engine_probe.py"], timeout=15)
    engine_json = None
    if engine.get("exit_code") == 0:
        try:
            engine_json = json.loads(engine.get("stdout", ""))
        except json.JSONDecodeError:
            engine_json = {"parse_error": True}
    return {
        "project": "SINTU AI YOUTUBE STUDIO",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "device": {"platform": platform.platform(), "machine": platform.machine(),
                   "python": sys.version.split()[0], "termux": bool(os.getenv("PREFIX", "").startswith("/data/data/com.termux"))},
        "repository": {"commit": (git_head.get("stdout") or "").strip() or None,
                       "working_tree": (git_status.get("stdout") or git_status.get("error") or "").strip(),
                       "git_status_exit": git_status.get("exit_code")},
        "dependencies": {"pip_check": pip_check},
        "media_tools": {"ffmpeg": version("ffmpeg"), "ffprobe": version("ffprobe")},
        "backend": backend_probe(),
        "engine_probe": engine_json if engine_json is not None else engine,
        "android": {"apk_files_found": apk_files,
                    "note": "APK presence is not installation or physical-device verification."},
        "media": media_inventory(),
        "automation_self_test": {"status": "NOT_RUN",
            "instruction": "Run scripts/automation_self_test.py --json separately; this diagnostic is read-only."},
        "safety": {"models_downloaded": False, "render_started": False,
                   "services_changed": False, "media_modified": False,
                   "uploads_performed": False, "publishing_performed": False},
    }


def render_text(report: dict) -> str:
    repo = report["repository"]
    device = report["device"]
    lines = [
        "SINTU AI YOUTUBE STUDIO — DEVICE DIAGNOSTIC",
        f"Created: {report['created_at']}",
        f"Device: {device['platform']} ({device['machine']}) | Python {device['python']} | Termux={device['termux']}",
        f"Commit: {repo['commit']}",
        f"Git status: {repo['working_tree'] or '(clean)'}",
        f"pip check exit: {report['dependencies']['pip_check'].get('exit_code')}",
        f"FFmpeg: {report['media_tools']['ffmpeg'].get('version') or 'UNAVAILABLE'}",
        f"FFprobe: {report['media_tools']['ffprobe'].get('version') or 'UNAVAILABLE'}",
        f"Backend reachable: {report['backend']['reachable']} ({report['backend']['url']})",
        f"Android APK files found: {len(report['android']['apk_files_found'])}",
        f"MP4 inventory: {report['media']['count']} files in {report['media']['directory']}",
        "Automation self-test: " + str(report["automation_self_test"].get("status")),
        "Safety: read-only; no model download, render, service change, media modification or upload.",
        "",
        "Full evidence is in the matching JSON report.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DATA_DIR / "diagnostics")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = build_report(run_automation=args.run_automation_self_test)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = args.output_dir / f"sintu_device_diagnostic_{stamp}.json"
    text_path = args.output_dir / f"sintu_device_diagnostic_{stamp}.txt"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    text_path.write_text(render_text(report), encoding="utf-8")
    print(render_text(report), end="")
    print(f"JSON report: {json_path}")
    print(f"Text report: {text_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
