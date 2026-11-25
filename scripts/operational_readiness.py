#!/usr/bin/env python3
"""One-command SINTU operational readiness doctor (no secrets are printed)."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_MODULES = ("fastapi", "uvicorn", "PIL", "cryptography", "dotenv")


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def probe(url: str, timeout: float = 3.0) -> tuple[bool, str]:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "SINTU-Readiness/1.0"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status == 200, f"HTTP {response.status}"
    except (OSError, urllib.error.URLError, TimeoutError, ValueError) as exc:
        return False, type(exc).__name__


def worker_process_matches(pid: int, proc_root: Path = Path("/proc")) -> bool:
    """Reject stale/reused PID files unless the process is the SINTU bridge worker."""
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return False
    try:
        raw = (proc_root / str(pid) / "cmdline").read_bytes()
    except OSError:
        return False
    arguments = [part.decode("utf-8", errors="replace") for part in raw.split(b"\0") if part]
    return any(Path(argument).name == "termux_bridge_worker.py" for argument in arguments)


def check(name: str, ok: bool, detail: str, required: bool = True) -> dict:
    return {"name": name, "status": "pass" if ok else ("fail" if required else "warn"),
            "detail": detail, "required": required}


def build_report(root: Path = ROOT, env: dict[str, str] | None = None,
                 check_network: bool = True) -> dict:
    env = dict(os.environ) if env is None else dict(env)
    file_env = read_env(root / ".env")
    file_env.update(env)
    checks = []
    checks.append(check("repository", (root / "app/main.py").is_file()
                        and (root / "requirements.txt").is_file(),
                        "SINTU source tree found"))
    missing = [name for name in REQUIRED_MODULES if importlib.util.find_spec(name) is None]
    checks.append(check("python_dependencies", not missing,
                        "All core modules available" if not missing else "Missing: " + ", ".join(missing)))
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    checks.append(check("ffmpeg", bool(ffmpeg), ffmpeg or "Install FFmpeg"))
    checks.append(check("ffprobe", bool(ffprobe), ffprobe or "Install FFprobe"))
    piper_name = file_env.get("PIPER_EXECUTABLE", "piper")
    piper_executable = shutil.which(piper_name) or (piper_name if Path(piper_name).is_file() else None)
    configured_model = file_env.get("PIPER_MODEL_PATH", "").strip()
    model_candidates = [
        Path(configured_model).expanduser() if configured_model else None,
        root / "models" / "voices" / "hi_IN-pratham-medium.onnx",
        root / "app" / "models" / "voices" / "hi_IN-pratham-medium.onnx",
    ]
    piper_model = next((candidate for candidate in model_candidates
                        if candidate is not None and candidate.is_file()), None)
    piper_ready = bool(piper_executable and piper_model)
    checks.append(check("piper_hindi_voice", piper_ready,
                        "Piper executable and Hindi neural model found" if piper_ready else
                        "Hindi neural voice unavailable; install Piper and configure PIPER_MODEL_PATH",
                        required=False))
    checks.append(check("private_environment", (root / ".env").is_file(),
                        ".env exists; values are never displayed"))
    checks.append(check("admin_auth", file_env.get("SINTU_AUTH_REQUIRED", "true").lower() == "true"
                        and len(file_env.get("SINTU_ADMIN_PASSWORD", "")) >= 16
                        and len(file_env.get("SINTU_SESSION_SECRET", "")) >= 32,
                        "Authentication and strong credentials configured"))
    bridge_ok = all(len(file_env.get(k, "")) >= 32 for k in
                    ("SINTU_BRIDGE_TOKEN", "SINTU_BRIDGE_WORKER_TOKEN"))
    checks.append(check("bridge_credentials", bridge_ok,
                        "Separate API and worker tokens configured"))
    worker_pid = Path.home() / ".sintu" / "bridge-worker.pid"
    worker_alive = False
    if worker_pid.is_file():
        try:
            pid = int(worker_pid.read_text().strip())
            worker_alive = worker_process_matches(pid)
        except (ValueError, OSError):
            pass
    checks.append(check("termux_bridge_worker", worker_alive,
                        "Worker process detected" if worker_alive else
                        "Worker not detected; run scripts/start_services.sh", required=False))
    api_url = file_env.get("SINTU_BRIDGE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    engine_results = {"local_ai_model": False, "comfyui": False}
    if check_network:
        api_ok, api_detail = probe(api_url + "/api/health")
        checks.append(check("api_health", api_ok, api_detail + " at /api/health", required=False))
        local_ai = file_env.get("LOCAL_OPENAI_BASE_URL", "http://127.0.0.1:8080/v1").rstrip("/")
        ai_ok, ai_detail = probe(local_ai + "/models")
        engine_results["local_ai_model"] = ai_ok
        checks.append(check("local_ai_model", ai_ok, ai_detail + " at /v1/models", required=False))
        comfy = file_env.get("COMFYUI_BASE_URL", "http://127.0.0.1:8188").rstrip("/")
        comfy_ok, comfy_detail = probe(comfy + "/system_stats")
        engine_results["comfyui"] = comfy_ok
        checks.append(check("comfyui", comfy_ok, comfy_detail + " at /system_stats", required=False))
    else:
        checks.extend([
            check("api_health", False, "Network probes skipped", required=False),
            check("local_ai_model", False, "Network probes skipped", required=False),
            check("comfyui", False, "Network probes skipped", required=False),
        ])
    pwa = (root / "app/static/index.html").is_file() and (root / "app/static/manifest.json").is_file()
    checks.append(check("mobile_pwa", pwa, "PWA entrypoint and manifest found"))

    failed = [item["name"] for item in checks if item["status"] == "fail"]
    warnings = [item["name"] for item in checks if item["status"] == "warn"]
    # "ready" remains the backward-compatible core-app readiness signal.
    # Production readiness is deliberately stricter: a procedural-art fallback,
    # FFmpeg alone, or a healthy API is not proof that AI production can run.
    production_requirements = {
        "local_ai_model": engine_results["local_ai_model"],
        "comfyui": engine_results["comfyui"],
        "ffmpeg": bool(ffmpeg),
        "ffprobe": bool(ffprobe),
        "piper_hindi_voice": piper_ready,
        "bridge_credentials": bridge_ok,
        "termux_bridge_worker": worker_alive,
    }
    production_blockers = [name for name, ok in production_requirements.items() if not ok]
    production_ready = not production_blockers and not failed
    return {
        "project": "SINTU AI YOUTUBE STUDIO",
        "ready": not failed,
        "core_ready": not failed,
        "production_ready": production_ready,
        "production_blockers": production_blockers,
        "production_readiness_note": (
            "Engine endpoints and local execution prerequisites are reachable. "
            "Configured ComfyUI workflows and a real end-to-end render still require a production E2E test."
            if production_ready else
            "AI production is NOT ready. Procedural fallback and FFmpeg rendering do not count as generative AI."
        ),
        "summary": {"passed": sum(x["status"] == "pass" for x in checks),
                    "warnings": len(warnings), "failed": len(failed)},
        "failed_checks": failed, "warnings": warnings, "checks": checks,
        "next_action": ("Core local requirements are ready." if not failed else
                        "Fix failed required checks, then rerun this doctor."),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check SINTU's real local operational readiness.")
    parser.add_argument("--no-network", action="store_true", help="Skip API/model/ComfyUI HTTP probes.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--strict-production", action="store_true",
                        help="Return failure unless local AI, ComfyUI, FFmpeg, bridge credentials and worker are ready.")
    args = parser.parse_args()
    report = build_report(check_network=not args.no_network)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"SINTU core readiness: {'READY' if report['core_ready'] else 'NOT READY'}")
        print(f"SINTU AI production readiness: {'READY' if report['production_ready'] else 'NOT READY'}")
        for item in report["checks"]:
            print(f"[{item['status'].upper():4}] {item['name']}: {item['detail']}")
        if report["production_blockers"]:
            print("Production blockers: " + ", ".join(report["production_blockers"]))
        print(f"Summary: {report['summary']}")
        print(report["production_readiness_note"])
        print(report["next_action"])
    if args.strict_production:
        return 0 if report["production_ready"] else 1
    return 0 if report["core_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
