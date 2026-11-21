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

from dotenv import load_dotenv

# Ensure the repository root is importable when invoked as `python scripts/live_e2e.py`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load_project_environment(env_path: Path | None = None) -> bool:
    """Load local credentials for diagnostics without overriding process config."""
    return load_dotenv(dotenv_path=env_path or PROJECT_ROOT / ".env", override=False)


_load_project_environment()

from app.ai_brain import generate_text, provider_status
from app.agents import AGENTS
from app.comfyui_client import image_workflow_status, video_workflow_status
from app.image_generator import IMAGE_DIR, generate_image, image_status
from app.voice_generator import AUDIO_DIR, generate_voiceover
from app.video_renderer import render_storyboard
from app.music_generator import MUSIC_DIR, generate_music, music_status
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



def _offline_storyboard_e2e(topic: str) -> dict:
    """Render a researched 60-second Hindi short covering ten named Indian forts."""
    clean_topic = topic.strip()
    if not clean_topic or len(clean_topic) > 300:
        raise ValueError("Offline video test topic must contain 1 to 300 characters.")

    forts = [
        "भानगढ़ किला",
        "कुंभलगढ़ किला",
        "गोलकोंडा किला",
        "चित्तौड़गढ़ किला",
        "दौलताबाद किला",
        "कांगड़ा किला",
        "मेहरानगढ़ किला",
        "जूनागढ़ किला",
        "जैसलमेर किला",
        "ग्वालियर किला",
    ]
    research_sources = [
        {"fort": "Bhangarh Fort", "claim": "Rajasthan Tourism describes the ruined palace, temples and marketplaces; curse accounts are presented as local legends, not verified supernatural evidence.", "source_type": "Rajasthan Tourism", "url": "https://www.tourism.rajasthan.gov.in/content/rajasthan-tourism/en/tourist-destinations/bhangarh-fort.html"},
        {"fort": "Kumbhalgarh Fort", "claim": "15th-century Mewar fort built by Rana Kumbha; its defensive wall stretches about 36 km.", "source_type": "Rajasthan Tourism", "url": "https://www.tourism.rajasthan.gov.in/kumbhalgarh-fort.html"},
        {"fort": "Golconda Fort", "claim": "Fateh Darwaza acoustics carry a clap from the gateway area to a hilltop pavilion almost one kilometre away.", "source_type": "Telangana Tourism", "url": "https://tourism.telangana.gov.in/attractions/golconda-fort"},
        {"fort": "Chittorgarh Fort", "claim": "The approach road passes seven gates; Vijay Stambh was built by Maharana Kumbha between 1440 and 1448.", "source_type": "Rajasthan Tourism", "url": "https://www.tourism.rajasthan.gov.in/content/rajasthan-tourism/en/tourist-destinations/chittorgarh-fort.html"},
        {"fort": "Daulatabad Fort", "claim": "A roughly 200-metre hill and a narrow winding rock-cut approach formed part of its layered defenses.", "source_type": "Maharashtra Tourism", "url": "https://maharashtratourism.gov.in/fort/devgiri-daulatabad/"},
        {"fort": "Kangra Fort", "claim": "The April 4, 1905 Kangra earthquake caused major structural damage; the fort is an ASI-protected monument.", "source_type": "District Kangra, Government of Himachal Pradesh", "url": "https://hpkangra.nic.in/tourist-place/kangra-fort/"},
        {"fort": "Mehrangarh Fort", "claim": "The Mehrangarh Museum Trust dates the fort's foundation by Rao Jodha to 1459.", "source_type": "Mehrangarh Museum Trust", "url": "https://www.mehrangarh.org/mehrangarh-2/architecture/"},
        {"fort": "Junagarh Fort", "claim": "Rajasthan Tourism dates the fort's construction to 1588 under Raja Rai Singh.", "source_type": "Rajasthan Tourism", "url": "https://www.tourism.rajasthan.gov.in/content/rajasthan-tourism/en/forts.html"},
        {"fort": "Jaisalmer Fort", "claim": "Founded in 1156 on Trikuta Hill; the golden sandstone fort is part of the UNESCO-listed Hill Forts of Rajasthan.", "source_type": "Incredible India and UNESCO", "url": "https://www.prod.incredibleindia.gov.in/content/incredible-india-v2/en/destinations/jaisalmer/jaisalmer-fort.html", "supporting_urls": ["https://whc.unesco.org/en/list/247/"]},
        {"fort": "Gwalior Fort", "claim": "The fortress stands on a steep sandstone hill and its outer walls extend about two miles.", "source_type": "District Gwalior, Government of Madhya Pradesh", "url": "https://gwalior.nic.in/en/tourist-place/the-fort/"},
    ]
    shot_specs = [
        "Bhangarh Fort in the Aravalli foothills, abandoned bazaar lanes and temple ruins, daylight cinematic wide shot",
        "Bhangarh Fort palace and Gopinath temple ruins, atmospheric folklore mood, no supernatural figures",
        "Kumbhalgarh Fort's long stone wall following the Aravalli mountain ridge, sweeping aerial view",
        "Kumbhalgarh ramparts and Badal Mahal above rugged hills, golden-hour documentary shot",
        "Golconda Fort Fateh Darwaza, acoustic gateway and distant hilltop pavilion, detailed architectural view",
        "Chittorgarh Fort with Vijay Stambh and monumental gates, vast hilltop fortress panorama",
        "Daulatabad Fort on its steep rocky hill, moat and shadowed rock-cut defensive passage",
        "Kangra Fort above the Himalayan valley, layered stone walls and distant Dhauladhar mountains",
        "Mehrangarh Fort's seven gates above the blue city of Jodhpur, dramatic high-angle view",
        "Junagarh Fort in Bikaner, red sandstone ramparts and ornate desert palace courtyards",
        "Jaisalmer's golden sandstone fort on Trikuta Hill, ornate havelis and narrow lanes at sunset",
        "Gwalior Fort on a steep sandstone hill, massive outer walls, palace facades and ancient temples",
        "Ancient Indian fort water tanks and stepwells, practical engineering for long sieges",
        "Massive bastions, iron-studded gates and winding defensive passages, historical architectural detail",
        "Cinematic closing montage of India's ten forts at dusk, heritage documentary atmosphere",
    ]
    scenes = [
        f"{clean_topic}. Historical scene: {shot}"
        for shot in shot_specs
    ]
    image_results = [generate_image(prompt, kind="scene", aspect="portrait") for prompt in scenes]
    image_paths = [IMAGE_DIR / f"{item['image_id']}.jpg" for item in image_results]
    for index, path in enumerate(image_paths, start=1):
        if not path.is_file() or path.stat().st_size <= 0:
            raise RuntimeError(f"Local scene image {index} was not saved.")

    narration = (
        "आज की यात्रा में दस ऐसे किले, जिनकी कहानियों में इतिहास और लोककथा साथ चलते हैं। "
        "भानगढ़ के महल, मंदिर और बाज़ार के खंडहर आज भी उसकी पुरानी बसावट दिखाते हैं; श्राप की बातें लोककथाएँ हैं, "
        "प्रमाणित अलौकिक घटना नहीं। कुंभलगढ़ की लगभग छत्तीस किलोमीटर दीवार अरावली पर फैली है। "
        "गोलकोंडा के फाटक पर ताली की गूँज लगभग एक किलोमीटर दूर मंडप तक पहुँचती है। "
        "चित्तौड़गढ़ की चढ़ाई सात द्वारों से गुजरती है; विजय स्तंभ महाराणा कुंभा ने बनवाया। "
        "दौलताबाद का दो सौ मीटर ऊँचा पहाड़ और चट्टान में कटा घुमावदार रास्ता रक्षा का हिस्सा थे। "
        "कांगड़ा किला उन्नीस सौ पाँच के भूकंप से बुरी तरह क्षतिग्रस्त हुआ। मेहरानगढ़ की नींव "
        "राव जोधा ने चौदह सौ उनसठ में रखी। बीकानेर का जूनागढ़ पंद्रह सौ अट्ठासी में राजा राय सिंह ने बनवाया। " +
        "जैसलमेर का सुनहरा किला ग्यारह सौ छप्पन में "
        "त्रिकूट पहाड़ी पर बसाया गया। ग्वालियर का दुर्ग बलुआ पत्थर की खड़ी पहाड़ी पर है। इनका असली रहस्य है इंजीनियरिंग, इतिहास और लोककथाओं का मेल।"
    )
    subtitles = [
        "दस किले—इतिहास, वास्तुकला और लोककथाओं का संगम।",
        "भानगढ़: महल और मंदिरों के खंडहर; श्राप की कहानी लोककथा है।",
        "कुंभलगढ़: अरावली पर लगभग 36 किलोमीटर लंबी दीवार।",
        "गोलकोंडा: फाटक की ताली की गूँज दूर मंडप तक।",
        "चित्तौड़गढ़: सात द्वार, विजय स्तंभ और वीरता की गाथाएँ।",
        "दौलताबाद: चट्टान काटकर बना घुमावदार रक्षा-पथ।",
        "कांगड़ा: हिमालयी दुर्ग, 1905 के भूकंप से क्षतिग्रस्त।",
        "मेहरानगढ़: राव जोधा ने 1459 में नींव रखी।",
        "जूनागढ़: 1588 में राजा राय सिंह ने बनवाया।",
        "जैसलमेर: 1156 में त्रिकूट पहाड़ी पर बना सुनहरा दुर्ग।",
        "ग्वालियर: खड़ी बलुआ-पत्थर पहाड़ी पर विशाल दुर्ग।",
        "खाइयाँ और जलाशय घेराबंदी में सहारा बने।",
        "बुर्ज और मीनारें दूर तक निगरानी रखते थे।",
        "किंवदंतियों को प्रमाणित इतिहास से अलग पहचानें।",
        "असली रहस्य—इंजीनियरिंग, साहस और समय।",
    ]
    voice = generate_voiceover(narration)
    audio_path = AUDIO_DIR / voice["filename"]
    if not audio_path.is_file() or audio_path.stat().st_size <= 0:
        raise RuntimeError("Local Hindi voiceover was not saved.")

    seconds_per_scene = 4
    target_duration = len(scenes) * seconds_per_scene
    music = generate_music(
        f"cinematic Indian historical documentary background score, orchestral atmosphere, "
        f"subtle suspense, warm strings and deep percussion, topic: {clean_topic}",
        duration=target_duration,
    )
    music_path = MUSIC_DIR / (music["music_id"] + ".wav")
    if not music_path.is_file() or music_path.stat().st_size <= 0:
        raise RuntimeError("Local cinematic background soundtrack was not saved.")

    rendered = render_storyboard(
        title=clean_topic,
        scenes=scenes,
        seconds_per_scene=seconds_per_scene,
        image_paths=image_paths,
        audio_path=audio_path,
        subtitles=subtitles,
        music_path=music_path,
        music_volume=0.12,
        transition="fade",
        motion="slow-zoom-in",
        resolution="720x1280",
        fps=24,
        quality="high",
    )
    final_path = OUTPUT_DIR / rendered["filename"]
    if not final_path.is_file() or final_path.stat().st_size <= 1000:
        raise RuntimeError("Offline storyboard MP4 was not created.")
    if rendered.get("brand_watermark") != "SINTU AI YOUTUBE STUDIO":
        raise RuntimeError("Offline storyboard MP4 is missing the mandatory SINTU watermark.")
    if rendered.get("subtitles_burned_in") is not True:
        raise RuntimeError("60-second Hindi acceptance MP4 must contain burned-in subtitles.")
    if rendered.get("audio") != "voiceover+music":
        raise RuntimeError("Offline storyboard MP4 must contain Hindi narration and background music.")
    if abs(float(rendered.get("duration_seconds", 0)) - target_duration) > 0.1:
        raise RuntimeError("Offline storyboard MP4 duration does not match the 60-second acceptance target.")

    return {
        "topic": clean_topic,
        "forts_covered": forts,
        "research_sources": research_sources,
        "research_method": "curated_official_sources",
        "research_source_count": len(research_sources),
        "scene_count": len(scenes),
        "image_providers": sorted({item.get("provider", "unknown") for item in image_results}),
        "voice_engine": voice.get("voice"),
        "voice_format": voice.get("format"),
        "music_provider": music.get("provider"),
        "subtitle_count": len(subtitles),
        "target_duration_seconds": target_duration,
        "final_render_id": rendered["video_id"],
        "final_render_path": str(final_path),
        "final_render_bytes": final_path.stat().st_size,
        "duration_seconds": rendered["duration_seconds"],
        "resolution": rendered["resolution"],
        "watermark": rendered["brand_watermark"],
        "audio": rendered["audio"],
        "subtitles_burned_in": rendered["subtitles_burned_in"],
        "verified_by_renderer": True,
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
    parser.add_argument("--offline-video", action="store_true", help="Generate procedural scene images, local Hindi voiceover and a verified branded MP4 without ComfyUI or paid APIs.")
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
        if args.offline_video:
            report["live_tests"]["offline_storyboard_video"] = _offline_storyboard_e2e(args.topic)
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
