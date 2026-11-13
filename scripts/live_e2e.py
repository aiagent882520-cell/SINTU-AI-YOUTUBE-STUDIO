#!/usr/bin/env python3
"""Live, local-first SINTU Studio end-to-end smoke runner.

Default mode reports readiness. Explicit flags perform real local model inference,
ComfyUI video generation, final branded rendering, or a deployment health probe.
No paid provider, OAuth consent, upload, or public publish is initiated.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import urllib.request
from urllib.parse import urlsplit
from pathlib import Path

# Ensure the repository root is importable when invoked as `python scripts/live_e2e.py`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.ai_brain import generate_text, provider_status
from app.agents import AGENTS
from app.comfyui_client import image_workflow_status, video_workflow_status
from app.image_generator import image_status
from app.music_generator import music_status
from app.production_runtime import REVIEWERS, attach_render_result, create_run, execute_run, get_run
from app.video_generator import AI_VIDEO_DIR, generate_video, video_status
from app.video_renderer import OUTPUT_DIR, render_ai_clips
from app.voice_generator import voice_status


def _safe_engine(status: dict) -> dict:
    diagnostics = status.get("local_diagnostics") or {}
    return {
        "available": bool(status.get("local_available", status.get("available", False))),
        "workflow_configured": status.get("local_workflow_configured"),
        "server_reachable": diagnostics.get("server_reachable"),
        "workflow_valid": diagnostics.get("workflow_valid"),
        "nodes_verified": diagnostics.get("nodes_verified"),
        "missing_nodes": diagnostics.get("missing_nodes", []),
        "missing_models": diagnostics.get("missing_models", []),
        "reason": diagnostics.get("reason"),
    }


def preflight() -> dict:
    local_ai = provider_status()["local"]
    image = image_status()
    video = video_status()
    voice = voice_status()
    music = music_status()
    return {
        "local_ai": {
            "service_running": bool(local_ai.get("service_running")),
            "model_available": bool(local_ai.get("model_available")),
            "model": local_ai.get("model"),
        },
        "comfyui_image": _safe_engine(image),
        "comfyui_video": _safe_engine(video),
        "piper_voice": {
            "available": bool(voice.get("local_available")),
            "model_configured": bool(voice.get("local_model_configured")),
            "provider": voice.get("local_engine"),
        },
        "music": {
            "available": bool(music.get("local_available")),
            "provider": music.get("local_engine"),
        },
        "rendering": {
            "ffmpeg": bool(shutil.which("ffmpeg")),
            "ffprobe": bool(shutil.which("ffprobe")),
        },
        "youtube_oauth": {
            "credentials_configured": bool(
                os.getenv("YOUTUBE_CLIENT_ID")
                and os.getenv("YOUTUBE_CLIENT_SECRET")
                and os.getenv("YOUTUBE_REDIRECT_URI")
            ),
            "token_encryption_configured": bool(os.getenv("YOUTUBE_TOKEN_ENCRYPTION_KEY")),
            "connected_channel": "Check /api/admin/youtube/status after owner OAuth consent.",
        },
        "deployment": {
            "health_probe": "Use --deployment-url https://your-host/api/health",
            "public_uploads": "Never performed by this script.",
        },
    }


def _live_video(prompt: str | list[str]) -> dict:
    status = video_status()
    if not status.get("local_available"):
        raise RuntimeError(
            "Local ComfyUI video workflow is not ready. Check workflow, nodes, models and /system_stats first."
        )
    prompts = [prompt] if isinstance(prompt, str) else list(prompt)
    prompts = [item.strip() for item in prompts if isinstance(item, str) and item.strip()]
    if not prompts or len(prompts) > 25:
        raise ValueError("Live video test needs 1 to 25 non-empty approved scene prompts.")

    clip_paths = []
    clip_ids = []
    clip_sizes = []
    for scene_index, scene_prompt in enumerate(prompts, start=1):
        clip = generate_video(
            prompt=scene_prompt,
            aspect_ratio="9:16",
            resolution="360p",
            style="cinematic",
            reference_image_id=None,
            duration_seconds=3,
        )
        clip_path = AI_VIDEO_DIR / clip["filename"]
        if not clip_path.is_file() or clip_path.stat().st_size <= 0:
            raise RuntimeError(f"ComfyUI did not leave a valid MP4 for scene {scene_index}.")
        clip_paths.append(clip_path)
        clip_ids.append(clip["video_id"])
        clip_sizes.append(clip_path.stat().st_size)

    rendered = render_ai_clips(
        clip_paths,
        resolution="720x1280",
        fps=24,
        quality="standard",
    )
    final_path = OUTPUT_DIR / rendered["filename"]
    if not final_path.is_file() or final_path.stat().st_size <= 0:
        raise RuntimeError("Final FFmpeg render was not created.")
    if rendered.get("brand_watermark") != "SINTU AI YOUTUBE STUDIO":
        raise RuntimeError("Final MP4 is missing the mandatory SINTU watermark.")
    if rendered.get("subtitles_burned_in") is not False:
        raise RuntimeError("Final MP4 violates the no-subtitles/no-text-overlay policy.")
    return {
        "generated_clip_ids": clip_ids,
        "generated_clip_bytes": clip_sizes,
        "scene_count": len(clip_paths),
        "final_render_id": rendered["video_id"],
        "final_render_path": str(final_path),
        "final_render_bytes": final_path.stat().st_size,
        "duration_seconds": rendered["duration_seconds"],
        "watermark": rendered["brand_watermark"],
        "subtitles_burned_in": rendered["subtitles_burned_in"],
        "verified_by_renderer": True,
        "render_result": rendered,
    }


def _live_agent_catalog(topic: str, include_result: bool = False):
    run = create_run("__agent_catalog__", topic, "local")
    execute_run(run["id"], "local")
    result = get_run(run["id"], "local")
    if not result:
        raise RuntimeError("Agent catalog run disappeared from persistent storage.")

    steps = result["steps"]
    workers = [step for step in steps if step["step_type"] == "builder"]
    checkers = [step for step in steps if step["step_type"] == "checker"]
    reviewers = [step for step in steps if step["step_type"] == "reviewer"]
    worker_roles = {step["role"] for step in workers}
    checker_roles = {step["role"].removesuffix(" Checker") for step in checkers}
    reviewer_roles = {step["role"] for step in reviewers}
    summary = {
        "run_id": run["id"],
        "status": result["status"],
        "registered_agent_roles": len(AGENTS),
        "completed_workers": sum(step["status"] == "completed" for step in workers),
        "passed_checkers": sum(step["status"] == "pass" for step in checkers),
        "final_reviewers": sum(step["status"] == "pass" for step in reviewers),
        "worker_role_coverage": len(worker_roles),
        "checker_role_coverage": len(checker_roles),
        "reviewer_role_coverage": len(reviewer_roles),
        "error": result.get("error"),
    }
    expected_workers = set(AGENTS)
    expected_reviewers = set(REVIEWERS)
    if (
        result["status"] != "completed"
        or worker_roles != expected_workers
        or checker_roles != expected_workers
        or reviewer_roles != expected_reviewers
        or len(workers) != len(AGENTS)
        or len(checkers) != len(AGENTS)
        or len(reviewers) != len(REVIEWERS)
        or summary["completed_workers"] != len(AGENTS)
        or summary["passed_checkers"] != len(AGENTS)
        or summary["final_reviewers"] != len(REVIEWERS)
    ):
        raise RuntimeError(
            "Full role validation did not pass exact catalog coverage: "
            + json.dumps(summary, ensure_ascii=False)
        )
    return (summary, result) if include_result else summary


def _extract_scene_prompts(deliverable: str) -> list[str]:
    if not isinstance(deliverable, str):
        raise RuntimeError("AI Video Generator deliverable is missing.")
    match = re.search(r"(?im)^\s*SCENE PROMPTS\s*:?[ \t]*\n([\s\S]*)$", deliverable)
    if not match:
        raise RuntimeError("Approved AI Video Generator output has no SCENE PROMPTS section.")
    prompts = [
        item.strip()
        for item in re.findall(r"(?m)^\s*\d+[.)]\s*(.+?)\s*$", match.group(1))
        if item.strip()
    ]
    if not 6 <= len(prompts) <= 12:
        raise RuntimeError(f"Expected 6 to 12 approved scene prompts; received {len(prompts)}.")
    return prompts


def _full_studio_e2e(topic: str) -> dict:
    role_summary, run = _live_agent_catalog(topic, include_result=True)
    deliverables = (run.get("result") or {}).get("deliverables") or {}
    prompts = _extract_scene_prompts(deliverables.get("AI Video Generator", ""))
    media = _live_video(prompts)
    attached = attach_render_result(run["id"], media["render_result"], "local")
    if not attached or not attached.get("result", {}).get("video_rendered"):
        raise RuntimeError("Rendered MP4 could not be attached to the quality-approved production run.")
    if attached.get("result", {}).get("published") is not False:
        raise RuntimeError("E2E test unexpectedly changed publishing state.")
    return {
        "agent_catalog": role_summary,
        "approved_scene_prompts": len(prompts),
        "rendered_scene_prompts": len(prompts),
        "video": {key: value for key, value in media.items() if key != "render_result"},
        "production_run_id": run["id"],
        "render_attached_to_production_run": True,
        "published": False,
    }


def _deployment_health(url: str) -> dict:
    parsed = urlsplit(url)
    secure_remote = parsed.scheme == "https" and bool(parsed.hostname)
    local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if not (secure_remote or local_http) or parsed.username or parsed.password:
        raise ValueError("Deployment health URL must use HTTPS or HTTP loopback without embedded credentials.")
    with urllib.request.urlopen(url, timeout=10) as response:
        body = json.loads(response.read(1024 * 1024).decode("utf-8"))
        if response.status != 200 or body.get("status") != "ok":
            raise RuntimeError("Deployment health endpoint did not return status=ok.")
        return {"status_code": response.status, "health": body.get("status")}


def main() -> int:
    parser = argparse.ArgumentParser(description="SINTU local/live end-to-end checks")
    parser.add_argument("--live-text", action="store_true", help="Make one real local Ollama text inference.")
    parser.add_argument("--live-agent-catalog", action="store_true", help="Run all 61 workers, 61 checkers and five reviewers using local Ollama.")
    parser.add_argument("--generate-video", action="store_true", help="Generate a real 3-second ComfyUI clip and render a branded MP4.")
    parser.add_argument("--full-studio-e2e", action="store_true", help="Run all 61 workers/checkers and five reviewers, use the approved AI Video Generator scene prompt, render a branded MP4, and attach it to the production run.")
    parser.add_argument("--topic", default="भारत के प्राचीन किले में सुबह का सिनेमाई दृश्य")
    parser.add_argument("--deployment-url", help="Probe a deployed /api/health URL.")
    args = parser.parse_args()

    report = {"preflight": preflight(), "live_tests": {}}
    failed = False
    try:
        if args.live_text:
            response = generate_text(
                "एक वाक्य में बताइए कि SINTU Studio का लोकल मॉडल चालू है।",
                "content",
                "local",
            )
            report["live_tests"]["local_text"] = {
                "passed": bool(response.get("output")),
                "model": response.get("model"),
            }
        if args.live_agent_catalog:
            report["live_tests"]["agent_catalog"] = _live_agent_catalog(args.topic)
        if args.full_studio_e2e:
            report["live_tests"]["full_studio_e2e"] = _full_studio_e2e(args.topic)
        if args.generate_video:
            report["live_tests"]["comfyui_video_and_branded_render"] = _live_video(args.topic)
        if args.deployment_url:
            report["live_tests"]["deployment_health"] = _deployment_health(args.deployment_url)
    except Exception as exc:
        failed = True
        report["live_tests"]["failure"] = f"{type(exc).__name__}: {str(exc)[:700]}"

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
