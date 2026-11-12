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
import shutil
import sys
import urllib.request
from urllib.parse import urlsplit

from app.ai_brain import generate_text, provider_status
from app.comfyui_client import image_workflow_status, video_workflow_status
from app.image_generator import image_status
from app.music_generator import music_status
from app.production_runtime import create_run, execute_run, get_run
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


def _live_video(prompt: str) -> dict:
    status = video_status()
    if not status.get("local_available"):
        raise RuntimeError(
            "Local ComfyUI video workflow is not ready. Check workflow, nodes, models and /system_stats first."
        )
    clip = generate_video(
        prompt=prompt,
        aspect_ratio="9:16",
        resolution="360p",
        style="cinematic",
        reference_image_id=None,
        duration_seconds=3,
    )
    clip_path = AI_VIDEO_DIR / clip["filename"]
    if not clip_path.is_file() or clip_path.stat().st_size <= 0:
        raise RuntimeError("ComfyUI did not leave a valid generated clip on disk.")
    rendered = render_ai_clips(
        [clip_path],
        resolution="720x1280",
        fps=24,
        quality="standard",
    )
    final_path = OUTPUT_DIR / rendered["filename"]
    if not final_path.is_file() or final_path.stat().st_size <= 0:
        raise RuntimeError("Final FFmpeg render was not created.")
    return {
        "generated_clip_id": clip["video_id"],
        "generated_clip_bytes": clip_path.stat().st_size,
        "final_render_id": rendered["video_id"],
        "final_render_path": str(final_path),
        "final_render_bytes": final_path.stat().st_size,
        "watermark": rendered["brand_watermark"],
        "subtitles_burned_in": rendered["subtitles_burned_in"],
        "verified_by_renderer": True,
    }


def _live_agent_catalog(topic: str) -> dict:
    run = create_run("__agent_catalog__", topic, "local")
    execute_run(run["id"], "local")
    result = get_run(run["id"], "local")
    if not result:
        raise RuntimeError("Agent catalog run disappeared from persistent storage.")
    summary = {
        "run_id": run["id"],
        "status": result["status"],
        "completed_workers": sum(
            step["step_type"] == "builder" and step["status"] == "completed"
            for step in result["steps"]
        ),
        "passed_checkers": sum(
            step["step_type"] == "checker" and step["status"] == "pass"
            for step in result["steps"]
        ),
        "final_reviewers": sum(step["step_type"] == "reviewer" for step in result["steps"]),
        "error": result.get("error"),
    }
    if result["status"] != "completed":
        raise RuntimeError("Full 61-role run did not complete: " + json.dumps(summary, ensure_ascii=False))
    return summary


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
