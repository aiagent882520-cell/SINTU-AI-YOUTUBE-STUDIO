#!/usr/bin/env python3
"""Run SINTU readiness, unit tests, offline MP4 generation, and media quality audit."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TOPIC = "भारत के प्राचीन किले और उनकी विरासत"


def _run_step(name: str, command: list[str], timeout: int, env: dict[str, str]) -> dict:
    started = time.monotonic()
    try:
        result = subprocess.run(
            command, cwd=ROOT, env=env, capture_output=True,
            text=True, timeout=timeout, check=False,
        )
        code = int(result.returncode)
        return {
            "name": name,
            "status": "passed" if code == 0 else "failed",
            "return_code": code,
            "duration_seconds": round(time.monotonic() - started, 2),
        }
    except subprocess.TimeoutExpired:
        return {
            "name": name, "status": "failed", "return_code": None,
            "duration_seconds": round(time.monotonic() - started, 2),
            "error": f"Timed out after {timeout} seconds.",
        }
    except OSError as exc:
        return {
            "name": name, "status": "failed", "return_code": None,
            "duration_seconds": round(time.monotonic() - started, 2),
            "error": str(exc)[:240],
        }


def run_self_test(*, skip_tests: bool = False, skip_video: bool = False,
                  topic: str = DEFAULT_TOPIC, data_dir: Path | None = None) -> dict:
    from app.config import DATA_DIR

    target_dir = Path(data_dir or DATA_DIR).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    media_dir = target_dir / "generated_videos"
    media_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["SINTU_DATA_DIR"] = str(target_dir)
    python = sys.executable
    steps = []

    steps.append(_run_step(
        "operational_readiness",
        [python, "scripts/operational_readiness.py", "--json"],
        90, env,
    ))
    if skip_tests:
        steps.append({"name": "pytest", "status": "skipped", "reason": "--skip-tests"})
    else:
        steps.append(_run_step(
            "pytest", [python, "-m", "pytest", "-q"], 1200, env,
        ))
    if skip_video:
        steps.append({"name": "offline_video_e2e", "status": "skipped", "reason": "--skip-video"})
    else:
        steps.append(_run_step(
            "offline_video_e2e",
            [python, "scripts/live_e2e.py", "--offline-video", "--topic", topic],
            900, env,
        ))
    media_report = target_dir / "self_test_media_audit.json"
    steps.append(_run_step(
        "media_quality_audit",
        [python, "scripts/project_health_audit.py", "--skip-tests",
         "--media-dir", str(media_dir), "--report", str(media_report)],
        180, env,
    ))

    failed = [step["name"] for step in steps if step["status"] == "failed"]
    report = {
        "project": "SINTU AI YOUTUBE STUDIO",
        "status": "FAIL" if failed else "PASS",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "steps": steps,
        "failed_steps": failed,
        "report_path": str(target_dir / "sintu_self_test_report.json"),
        "media_audit_path": str(media_report),
        "paid_services_used": False,
        "publishing_performed": False,
    }
    report_path = target_dir / "sintu_self_test_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-tests", action="store_true", help="Skip the full pytest suite.")
    parser.add_argument("--skip-video", action="store_true", help="Skip offline MP4 generation.")
    parser.add_argument("--topic", default=DEFAULT_TOPIC, help="Hindi/English offline video topic (max 300 chars).")
    args = parser.parse_args()
    topic = args.topic.strip()
    if not topic or len(topic) > 300:
        parser.error("--topic must contain 1 to 300 characters.")
    report = run_self_test(skip_tests=args.skip_tests, skip_video=args.skip_video, topic=topic)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
