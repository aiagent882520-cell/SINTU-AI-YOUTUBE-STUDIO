#!/usr/bin/env python3
"""Read-only Android/Termux readiness diagnostic for the native SINTU client."""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def command_output(command: list[str], timeout: int = 3) -> dict:
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=timeout, check=False)
        return {"exit_code": result.returncode,
                "output": (result.stdout or result.stderr or "").strip()[:240]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"exit_code": None, "output": str(exc)[:160]}


def memory_available_mb() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def package_installed(package: str) -> bool | None:
    if not shutil.which("pm"):
        return None
    result = command_output(["pm", "path", package], timeout=5)
    return result["exit_code"] == 0 and result["output"].startswith("package:")


def backend_health(base_url: str) -> dict:
    parsed = urllib.parse.urlparse(base_url)
    host = (parsed.hostname or "").lower()
    loopback = host in {"127.0.0.1", "localhost", "::1"}
    if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
        return {"status": "BLOCKED", "reason": "invalid URL or embedded credentials"}
    if parsed.scheme != "https" and not loopback:
        return {"status": "BLOCKED", "reason": "remote backend requires HTTPS"}
    url = base_url.rstrip("/") + "/api/health"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return {"status": "PASS" if 200 <= response.status < 300 else "FAIL",
                    "http_status": response.status}
    except urllib.error.HTTPError as exc:
        return {"status": "FAIL", "http_status": exc.code}
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        return {"status": "UNREACHABLE", "reason": type(exc).__name__}


def collect_report(base_url: str) -> dict:
    home = Path.home()
    disk = shutil.disk_usage(home) if home.exists() else None
    binaries = {}
    for name in ("ffmpeg", "ffprobe", "espeak-ng", "espeak", "piper", "curl"):
        path = shutil.which(name)
        binaries[name] = {"available": bool(path), "path": path}
    app_packages = {
        package: package_installed(package)
        for package in ("com.sintu.studio", "com.sintu.studio.debug")
    }
    return {
        "diagnostic": "SINTU_ANDROID_READ_ONLY",
        "platform": platform.platform(),
        "android_release": command_output(["getprop", "ro.build.version.release"]),
        "device_abi": command_output(["getprop", "ro.product.cpu.abi"]),
        "available_ram_mb": memory_available_mb(),
        "home_storage": None if disk is None else {
            "free_bytes": disk.free, "total_bytes": disk.total,
        },
        "native_app_packages": app_packages,
        "binaries": binaries,
        "backend_health": backend_health(base_url),
        "limitations": [
            "Does not submit credentials or test authenticated login.",
            "Does not create, modify, move or delete user media.",
            "Does not prove gallery download, background recovery, timeline editing or AI model readiness.",
            "Run on the actual phone; a hosted CI result is not device evidence.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000",
                        help="SINTU backend URL; remote hosts must use HTTPS")
    args = parser.parse_args()
    print(json.dumps(collect_report(args.base_url), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
