#!/usr/bin/env python3
"""Verify real Termux watchdog recovery after safely terminating SINTU worker and API processes."""
from __future__ import annotations

import argparse
import json
import os
import signal
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

LOG_DIR = Path.home() / ".sintu"
BASE_URL = os.getenv("SINTU_BRIDGE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
API_TOKEN = os.getenv("SINTU_BRIDGE_TOKEN", "").strip()


def _proc_identity(pid: int) -> tuple[int, str] | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        tail = raw.rsplit(")", 1)[1].strip().split()
        if tail[0] == "Z":
            return None
        start_ticks = tail[19]
        return pid, start_ticks
    except (OSError, IndexError):
        return None


def _command_line(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
    except OSError:
        return ""


def _read_pid(name: str, marker: str) -> tuple[int, tuple[int, str]]:
    pid_file = LOG_DIR / f"{name}.pid"
    if not pid_file.is_file():
        raise RuntimeError(f"{name} PID file is missing")
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        raise RuntimeError(f"{name} PID file is invalid") from None
    identity = _proc_identity(pid)
    if identity is None or marker not in _command_line(pid):
        raise RuntimeError(f"{name} PID does not identify the expected SINTU process; refusing to signal it")
    return pid, identity


def _terminate_known_process(name: str, marker: str) -> tuple[int, str]:
    pid, before = _read_pid(name, marker)
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if _proc_identity(pid) != before or marker not in _command_line(pid):
            return pid, before[1]
        time.sleep(0.25)
    # Escalate only if the exact same process identity and command are still present.
    if _proc_identity(pid) == before and marker in _command_line(pid):
        os.kill(pid, signal.SIGKILL)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and _proc_identity(pid) == before:
        time.sleep(0.25)
    if _proc_identity(pid) == before:
        raise RuntimeError(f"{name} did not terminate after SIGTERM/SIGKILL")
    return pid, before[1]


def _request(path: str, timeout: float = 4.0) -> dict:
    headers = {"User-Agent": "SINTU-Watchdog-Recovery-Test"}
    if API_TOKEN:
        headers["Authorization"] = "Bearer " + API_TOKEN
    request = urllib.request.Request(BASE_URL + path, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _wait_for_new_process(name: str, marker: str, old_identity: tuple[int, str],
                          timeout: int = 150) -> dict:
    deadline = time.monotonic() + timeout
    pid_file = LOG_DIR / f"{name}.pid"
    while time.monotonic() < deadline:
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
            identity = _proc_identity(pid)
            command = _command_line(pid)
            if identity and identity != old_identity and marker in command:
                return {"pid": pid, "recovered": True}
        except (OSError, ValueError):
            pass
        time.sleep(2)
    raise TimeoutError(f"{name} was not restarted by the watchdog within {timeout} seconds")


def _wait_for_api(timeout: int = 150) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(BASE_URL + "/api/health", timeout=4) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError, TimeoutError):
            pass
        time.sleep(2)
    raise TimeoutError(f"SINTU API did not recover within {timeout} seconds")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    results = []
    try:
        _read_pid("watchdog", "scripts/termux_watchdog.sh")
        _wait_for_api(timeout=10)
        status = _request("/api/termux-bridge/status")
        if not status.get("worker_online"):
            raise RuntimeError("Bridge worker is not online before the recovery test")

        worker_pid, worker_start = _terminate_known_process(
            "bridge-worker", "scripts/termux_bridge_worker.py"
        )
        worker_identity = (worker_pid, worker_start)
        worker_result = _wait_for_new_process(
            "bridge-worker", "scripts/termux_bridge_worker.py", worker_identity
        )
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            try:
                if _request("/api/termux-bridge/status").get("worker_online"):
                    break
            except (OSError, urllib.error.URLError, TimeoutError):
                pass
            time.sleep(2)
        else:
            raise TimeoutError("Recovered bridge worker did not restore its heartbeat")
        results.append({"process": "bridge-worker", "status": "recovered",
                        "old_pid": worker_pid, "new_pid": worker_result["pid"]})

        server_pid, server_start = _terminate_known_process("server", "uvicorn app.main:app")
        server_identity = (server_pid, server_start)
        server_result = _wait_for_new_process(
            "server", "uvicorn app.main:app", server_identity
        )
        _wait_for_api(timeout=30)
        if not _request("/api/termux-bridge/status").get("worker_online"):
            raise RuntimeError("Bridge worker heartbeat was not healthy after API recovery")
        results.append({"process": "server", "status": "recovered",
                        "old_pid": server_pid, "new_pid": server_result["pid"]})
        _read_pid("watchdog", "scripts/termux_watchdog.sh")
        report = {"status": "PASS", "checks": results,
                  "note": "Actual process termination and watchdog restart verified on this Termux session; device reboot is not tested."}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        report = {"status": "FAIL", "checks": results, "error": str(exc)[:1000]}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
