#!/usr/bin/env python3
"""GitHub Issues relay: ChatGPT queues allowlisted jobs; Termux executes them locally.

The GitHub connector is the cloud-side mailbox. No public tunnel or arbitrary
shell endpoint is needed. Only issues authored by the configured owner and
bearing the queue label are accepted.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

REPOSITORY = os.getenv("SINTU_GITHUB_REPOSITORY", "aiagent882520-cell/SINTU-AI-YOUTUBE-STUDIO")
ALLOWED_ACTOR = os.getenv("SINTU_GITHUB_ALLOWED_ACTOR", REPOSITORY.split("/", 1)[0]).lower()
QUEUED_LABEL = "sintu-command-queued"
RUNNING_LABEL = "sintu-command-running"
DONE_LABEL = "sintu-command-done"
FAILED_LABEL = "sintu-command-failed"
PYTHON = str(ROOT / ".venv" / "bin" / "python")
if not Path(PYTHON).exists():
    PYTHON = sys.executable
ACTIONS = {
    "git_status", "git_pull_ff_only", "run_tests", "compile_check",
    "health_audit", "operational_readiness", "live_preflight",
    "offline_video_e2e", "full_self_test", "full_studio_e2e",
}


def github_token() -> str:
    """Read an already-authenticated GitHub CLI token; never print it."""
    result = subprocess.run(
        ["gh", "auth", "token"], cwd=ROOT, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15, check=False,
    )
    token = result.stdout.strip()
    if result.returncode or not token:
        raise RuntimeError("GitHub CLI is not authenticated. Run: gh auth login")
    return token


class GitHub:
    def __init__(self, token: str):
        self.token = token

    def request(self, method: str, path: str, payload=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            "https://api.github.com/repos/" + REPOSITORY + path,
            data=data, method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": "Bearer " + self.token,
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
                "User-Agent": "SINTU-Termux-Relay",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                raw = response.read(1_000_000)
                return json.loads(raw.decode("utf-8")) if raw else None
        except urllib.error.HTTPError as exc:
            detail = exc.read(2000).decode("utf-8", "replace")
            if method == "POST" and exc.code == 422 and "already_exists" in detail:
                return None
            raise RuntimeError(f"GitHub API HTTP {exc.code}: {detail}") from None

    def ensure_labels(self):
        for name, color, description in (
            (QUEUED_LABEL, "1f6feb", "Allowlisted SINTU jobs waiting for Termux"),
            (RUNNING_LABEL, "fbca04", "SINTU job claimed by Termux"),
            (DONE_LABEL, "2da44e", "SINTU job completed successfully"),
            (FAILED_LABEL, "d1242f", "SINTU job failed"),
        ):
            try:
                self.request("POST", "/labels", {
                    "name": name, "color": color, "description": description
                })
            except RuntimeError as exc:
                if "already_exists" not in str(exc):
                    raise

    def pending(self):
        # Recover a job whose Android process died after claiming it. The
        # longest allowed command is 30 minutes; a 40-minute lease is safe.
        running_query = urllib.parse.urlencode({
            "state": "open", "labels": RUNNING_LABEL, "per_page": "50"
        })
        running = self.request("GET", "/issues?" + running_query) or []
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=40)
        for issue in running:
            if (
                "pull_request" in issue
                or issue.get("user", {}).get("login", "").lower() != ALLOWED_ACTOR
                or not issue.get("title", "").startswith("SINTU-CMD:")
            ):
                continue
            try:
                updated = datetime.fromisoformat(issue["updated_at"].replace("Z", "+00:00"))
            except (KeyError, ValueError):
                continue
            if updated < cutoff:
                self.update_issue(int(issue["number"]), labels=[QUEUED_LABEL])
                self.comment(int(issue["number"]), "♻️ Recovered stale claim after the previous Termux worker stopped responding.")
        query = urllib.parse.urlencode({
            "state": "open", "labels": QUEUED_LABEL, "per_page": "50"
        })
        issues = self.request("GET", "/issues?" + query) or []
        return [
            issue for issue in issues
            if "pull_request" not in issue
            and issue.get("user", {}).get("login", "").lower() == ALLOWED_ACTOR
            and issue.get("title", "").startswith("SINTU-CMD:")
        ]

    def comment(self, number: int, body: str):
        return self.request("POST", f"/issues/{number}/comments", {"body": body})

    def update_issue(self, number: int, **fields):
        return self.request("PATCH", f"/issues/{number}", fields)


def command_for(action: str, payload: dict) -> list[str]:
    if action not in ACTIONS:
        raise ValueError("Action is not on the SINTU allowlist.")
    allowed_fields = (
        {"test_path"} if action == "run_tests"
        else {"topic"} if action in {"offline_video_e2e", "full_self_test", "full_studio_e2e"}
        else set()
    )
    if set(payload) - allowed_fields:
        raise ValueError("Payload fields are not valid for this action.")
    if action == "git_status":
        return ["git", "status", "--short", "--branch"]
    if action == "git_pull_ff_only":
        return ["git", "pull", "--ff-only", "origin", "main"]
    if action == "compile_check":
        return [PYTHON, "-m", "compileall", "-q", "app", "scripts"]
    if action == "health_audit":
        return [PYTHON, "scripts/project_health_audit.py"]
    if action == "operational_readiness":
        return [PYTHON, "scripts/operational_readiness.py", "--json"]
    if action == "live_preflight":
        return [PYTHON, "scripts/live_e2e.py"]
    if action in {"offline_video_e2e", "full_self_test", "full_studio_e2e"}:
        topic = payload.get("topic")
        if topic is not None and (
            not isinstance(topic, str) or not topic.strip() or len(topic.strip()) > 300
        ):
            raise ValueError("topic must contain 1 to 300 characters.")
        if action == "offline_video_e2e":
            topic = topic or "भारत के प्राचीन किले में सुबह का सिनेमाई दृश्य"
            return [PYTHON, "scripts/live_e2e.py", "--offline-video", "--topic", topic.strip()]
        if action == "full_studio_e2e":
            topic = topic or "भारत के प्राचीन किले में सुबह का सिनेमाई दृश्य"
            return [PYTHON, "scripts/live_e2e.py", "--full-studio-e2e", "--topic", topic.strip()]
        command = [PYTHON, "scripts/sintu_self_test.py"]
        if topic:
            command += ["--topic", topic.strip()]
        return command
    if action == "run_tests":
        test_path = payload.get("test_path")
        if test_path:
            candidate = Path(test_path)
            if (
                candidate.is_absolute() or ".." in candidate.parts
                or len(candidate.parts) != 2 or candidate.parts[0] != "tests"
                or candidate.suffix != ".py" or not (ROOT / candidate).is_file()
            ):
                raise ValueError("test_path must name an existing Python file directly inside tests/.")
            return [PYTHON, "-m", "pytest", test_path, "-q"]
        return [PYTHON, "-m", "pytest", "-q"]
    raise ValueError("Action is not on the SINTU allowlist.")


def process_issue(github: GitHub, issue: dict) -> None:
    number = int(issue["number"])
    # Claim first by changing the queue label. A single worker is expected per device.
    github.update_issue(number, labels=[RUNNING_LABEL])
    github.comment(number, "🤖 SINTU Termux worker claimed this job. Execution started.")
    try:
        body = json.loads(issue.get("body") or "{}")
        if not isinstance(body, dict) or set(body) - {"action", "topic", "test_path"}:
            raise ValueError("Issue body must be JSON with only action, topic, and test_path fields.")
        action = body.get("action")
        if not isinstance(action, str):
            raise ValueError("Missing string action.")
        payload = {key: body[key] for key in ("topic", "test_path") if key in body}
        command = command_for(action, payload)
        completed = subprocess.run(
            command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=1800, check=False,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        success = completed.returncode == 0
        output = (completed.stdout or "")[-8000:] or "(no command output)"
        status = "SUCCESS" if success else f"FAILED (exit {completed.returncode})"
        label = DONE_LABEL if success else FAILED_LABEL
    except subprocess.TimeoutExpired:
        success, output, status, label = False, "Execution exceeded the 30-minute safety timeout.", "FAILED (timeout)", FAILED_LABEL
    except Exception as exc:
        success, output, status, label = False, str(exc), "FAILED (validation/runtime error)", FAILED_LABEL

    github.comment(
        number,
        f"## SINTU Termux result: {status}\n\n"
        f"Device: Android Termux\n\n"
        f"\x60\x60\x60text\n{output}\n\x60\x60\x60",
    )
    github.update_issue(number, state="closed", labels=[label])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=15.0)
    args = parser.parse_args()
    if not 5 <= args.interval <= 300:
        print("--interval must be between 5 and 300 seconds.", file=sys.stderr)
        return 2
    try:
        github = GitHub(github_token())
        github.ensure_labels()
    except Exception as exc:
        print(f"SINTU GitHub relay unavailable: {exc}", file=sys.stderr)
        return 2
    print(f"SINTU GitHub relay watching {REPOSITORY} as {ALLOWED_ACTOR}", flush=True)
    while True:
        try:
            issues = github.pending()
            if not issues and args.once:
                return 0
            for issue in issues:
                process_issue(github, issue)
            if args.once:
                return 0
            time.sleep(args.interval if not issues else 1)
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            print(f"GitHub relay error: {exc}", file=sys.stderr, flush=True)
            if args.once:
                return 1
            time.sleep(max(args.interval, 15))


if __name__ == "__main__":
    raise SystemExit(main())
