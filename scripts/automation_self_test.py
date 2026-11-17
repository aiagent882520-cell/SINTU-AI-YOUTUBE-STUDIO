#!/usr/bin/env python3
"""Read-only diagnostic for the ChatGPT -> GitHub -> Termux -> SINTU control plane."""
from __future__ import annotations
import argparse, fcntl, json, os, shutil, subprocess, sys, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

def run_check(name, fn):
    try:
        return {"name": name, "ok": True, "detail": fn()}
    except Exception as exc:
        return {"name": name, "ok": False, "detail": str(exc)[:400]}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    results = []
    def git_root():
        value = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=ROOT, text=True).strip()
        if Path(value).resolve() != ROOT.resolve():
            raise RuntimeError("Unexpected repository root")
        return value
    results.append(run_check("repository", git_root))
    def git_origin():
        value = subprocess.check_output(["git", "remote", "get-url", "origin"], cwd=ROOT, text=True).strip()
        if "aiagent882520-cell/SINTU-AI-YOUTUBE-STUDIO" not in value:
            raise RuntimeError("origin does not point to the expected SINTU repository")
        return "expected GitHub origin"
    results.append(run_check("git_origin", git_origin))
    def python_env():
        exe = ROOT / ".venv" / "bin" / "python"
        if not exe.is_file():
            raise RuntimeError("Project .venv is missing")
        return subprocess.check_output([str(exe), "--version"], text=True).strip()
    results.append(run_check("python_environment", python_env))
    def github_auth():
        if not shutil.which("gh"):
            raise RuntimeError("GitHub CLI is not installed")
        p = subprocess.run(["gh", "auth", "status"], cwd=ROOT, text=True, capture_output=True)
        if p.returncode:
            raise RuntimeError("GitHub CLI authentication unavailable")
        return "authenticated; credentials hidden"
    results.append(run_check("github_cli_auth", github_auth))
    def api_health():
        # /openapi.json is intentionally behind the admin-session firewall.
        # Use the dedicated public liveness endpoint for an unauthenticated probe.
        with urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=5) as response:
            if response.status != 200:
                raise RuntimeError("Studio API did not return HTTP 200")
            data = json.load(response)
        if data.get("status") != "ok" or data.get("app") != "SINTU AI YOUTUBE STUDIO":
            raise RuntimeError("Studio API health payload is invalid")
        return {"status": data["status"], "version": data.get("version")}
    results.append(run_check("studio_api", api_health))
    def bridge_worker():
        token = os.getenv("SINTU_BRIDGE_TOKEN", "").strip()
        if len(token) < 32:
            raise RuntimeError("SINTU_BRIDGE_TOKEN missing or weak")
        request = urllib.request.Request(
            "http://127.0.0.1:8000/api/termux-bridge/status",
            headers={"Authorization": "Bearer " + token},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            data = json.load(response)
        if not data.get("automation_only"):
            raise RuntimeError("Automation-only safety gate is OFF")
        if not data.get("worker_online"):
            raise RuntimeError("Bridge worker heartbeat is offline")
        return {"worker_online": True, "automation_only": True, "jobs": data.get("jobs", {})}
    results.append(run_check("bridge_and_worker", bridge_worker))
    def relay_lock():
        lock = Path.home() / ".sintu" / "github-relay.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        with lock.open("a+") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return "relay singleton lock held"
            raise RuntimeError("GitHub relay lock is free; relay is not running")
    results.append(run_check("github_relay_singleton", relay_lock))
    report = {"ok": all(item["ok"] for item in results), "checks": results}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
