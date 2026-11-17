#!/usr/bin/env python3
"""Poll SINTU's authenticated bridge queue and run only fixed safe actions."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

BASE_URL = os.getenv("SINTU_BRIDGE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
TOKEN = os.getenv("SINTU_BRIDGE_WORKER_TOKEN", "").strip()
AUTOMATION_ONLY = os.getenv("SINTU_AUTOMATION_ONLY", "true").strip().lower() in {"1", "true", "yes", "on"}
PRODUCTION_ACTIONS = {"offline_video_e2e", "full_self_test", "full_studio_e2e"}
PYTHON = str(ROOT / ".venv" / "bin" / "python")
if not Path(PYTHON).exists():
    PYTHON = sys.executable


def request_json(path: str, method: str = "GET", payload: dict | None = None):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        BASE_URL + path, data=body, method=method,
        headers={"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.status == 204:
                return None
            raw = response.read(25000)
            return json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as exc:
        if exc.code == 204:
            return None
        detail = exc.read(2000).decode("utf-8", "replace")
        raise RuntimeError(f"Bridge HTTP {exc.code}: {detail}") from None


def command_for(job: dict) -> list[str]:
    action = job.get("action")
    payload = job.get("payload") or {}
    if AUTOMATION_ONLY and action in PRODUCTION_ACTIONS:
        raise ValueError("Production actions are paused in SINTU automation-only mode.")
    if action == "git_status":
        return ["git", "status", "--short", "--branch"]
    if action == "git_pull_ff_only":
        return ["git", "pull", "--ff-only", "origin", "main"]
    if action == "automation_self_test":
        return [PYTHON, "scripts/automation_self_test.py", "--json"]
    if action == "compile_check":
        return [PYTHON, "-m", "compileall", "-q", "app", "scripts"]
    if action == "health_audit":
        return [PYTHON, "scripts/project_health_audit.py"]
    if action == "operational_readiness":
        return [PYTHON, "scripts/operational_readiness.py", "--json"]
    if action == "live_preflight":
        return [PYTHON, "scripts/live_e2e.py"]
    if action == "engine_probe":
        return [PYTHON, "scripts/engine_probe.py"]
    if action == "safe_optional_install":
        return ["bash", "scripts/termux_safe_optional_install.sh"]
    if action == "restart_services":
        return ["bash", "scripts/start_services.sh"]
    if action == "media_repair":
        return [PYTHON, "scripts/repair_media.py", "--apply", "--json"]
    if action == "watchdog_recovery_test":
        return [PYTHON, "scripts/watchdog_recovery_test.py", "--json"]
    if action == "offline_video_e2e":
        topic = payload.get("topic", "भारत के प्राचीन किले में सुबह का सिनेमाई दृश्य")
        if not isinstance(topic, str) or not topic.strip() or len(topic.strip()) > 300:
            raise ValueError("Rejected offline video topic.")
        return [PYTHON, "scripts/live_e2e.py", "--offline-video", "--topic", topic.strip()]
    if action == "full_studio_e2e":
        topic = payload.get("topic")
        if topic is not None and (not isinstance(topic, str) or not topic.strip() or len(topic.strip()) > 300):
            raise ValueError("Rejected full studio topic.")
        command = [PYTHON, "scripts/live_e2e.py", "--full-studio-e2e"]
        if topic:
            command += ["--topic", topic.strip()]
        return command
    if action == "full_self_test":
        topic = payload.get("topic")
        if topic is not None and (not isinstance(topic, str) or not topic.strip() or len(topic.strip()) > 300):
            raise ValueError("Rejected full self-test topic.")
        command = [PYTHON, "scripts/sintu_self_test.py"]
        if topic:
            command += ["--topic", topic.strip()]
        return command
    if action == "run_tests":
        test_path = payload.get("test_path")
        if test_path:
            candidate = Path(test_path)
            if (candidate.is_absolute() or ".." in candidate.parts
                    or len(candidate.parts) != 2 or candidate.parts[0] != "tests"
                    or candidate.suffix != ".py" or not (ROOT / candidate).is_file()):
                raise ValueError("Rejected test path.")
            return [PYTHON, "-m", "pytest", test_path, "-q"]
        return [PYTHON, "-m", "pytest", "-q"]
    raise ValueError("Action is not on the Termux bridge allowlist.")


def execute(job: dict) -> tuple[int, str]:
    command = command_for(job)
    completed = subprocess.run(
        command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, timeout=1800, check=False,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    return completed.returncode, completed.stdout[-20000:]


def run_once() -> bool:
    job = request_json("/api/termux-bridge/jobs/next")
    if not job:
        return False
    job_id = job["job_id"]
    try:
        code, output = execute(job)
        status = "succeeded" if code == 0 else "failed"
    except subprocess.TimeoutExpired as exc:
        code, output, status = 124, (exc.stdout or "")[-20000:] if isinstance(exc.stdout, str) else "Command timed out.", "failed"
    except Exception as exc:
        code, output, status = 1, str(exc), "failed"
    request_json(
        f"/api/termux-bridge/jobs/{job_id}/complete", "POST",
        {"status": status, "exit_code": code, "output": output},
    )
    print(f"{job_id}: {status} (exit {code})", flush=True)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Claim and execute at most one queued job.")
    parser.add_argument("--interval", type=float, default=3.0, help="Polling interval in seconds.")
    args = parser.parse_args()
    if len(TOKEN) < 32:
        print("SINTU_BRIDGE_WORKER_TOKEN missing or shorter than 32 characters.", file=sys.stderr)
        return 2
    if args.interval < 1 or args.interval > 60:
        print("--interval must be between 1 and 60 seconds.", file=sys.stderr)
        return 2
    if args.once:
        try:
            run_once()
            return 0
        except Exception as exc:
            print(str(exc), file=sys.stderr)
            return 1
    print(f"SINTU Termux Bridge worker connected to {BASE_URL}", flush=True)
    while True:
        try:
            if not run_once():
                time.sleep(args.interval)
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            print(f"Bridge worker error: {exc}", file=sys.stderr, flush=True)
            time.sleep(max(5, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
