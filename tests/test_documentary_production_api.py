"""HTTP-level acceptance for the real Production Factory documentary media route."""
from __future__ import annotations

import json
import math
import shutil
import struct
import subprocess
import wave
from pathlib import Path

from PIL import Image

import pytest
from fastapi.testclient import TestClient

from app import main, video_renderer


def _write_test_tone(path: Path, seconds: float, frequency: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 48_000
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(2)
        stream.setsampwidth(2)
        stream.setframerate(sample_rate)
        frames = bytearray()
        for index in range(int(sample_rate * seconds)):
            sample = int(1800 * math.sin(2 * math.pi * frequency * index / sample_rate))
            frames.extend(struct.pack("<hh", sample, sample))
        stream.writeframes(frames)


def test_documentary_factory_api_renders_real_animated_mp4_with_audio_and_subtitles(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Exercise POST /produce-media through FastAPI, not just renderer helpers."""
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe") or not shutil.which("fc-match"):
        pytest.skip("The API render acceptance test requires FFmpeg, FFprobe and fontconfig.")
    font = subprocess.run(
        ["fc-match", "-f", "%{family}", "Noto Sans Devanagari"],
        capture_output=True, text=True, timeout=10, check=False,
    )
    if font.returncode or "Noto Sans Devanagari" not in font.stdout:
        pytest.skip("Run this integration test in the CI offline-video job with Noto Sans Devanagari installed.")
    run_id = "a" * 32
    data_dir = tmp_path / "data"
    output_dir = data_dir / "generated_videos"
    audio_dir = data_dir / "generated_audio"
    music_dir = data_dir / "generated_music"
    image_dir = data_dir / "generated_images"
    output_dir.mkdir(parents=True)
    audio_dir.mkdir(parents=True)
    music_dir.mkdir(parents=True)
    image_dir.mkdir(parents=True)

    prompts = [
        "Map animation: an illustrated map traces the ancient trade route across India.",
        "Timeline animation: a chronological timeline reveals the fort's construction and later events.",
        "Diagram animation: an architectural cutaway diagram explains the hidden water system.",
        "Character animation: a historical guide walks through the palace courtyard.",
        "Environment animation: a cinematic environment shows the fort above a moving river at sunrise.",
        "Map animation: a regional map locates the fort among nearby rivers and settlements.",
        "Timeline animation: archival eras transition across a chronological ruler.",
        "Diagram animation: a layered cutaway reveals gates, walls and defensive passages.",
        "Character animation: an artisan demonstrates traditional stone construction.",
        "Environment animation: monsoon clouds move over the fort's mountain ridge.",
        "Map animation: a siege route is traced around the outer fortifications.",
        "Timeline animation: rulers and restoration periods appear in sequence.",
        "Diagram animation: a water harvesting system is shown in cross-section.",
        "Character animation: a guide walks through a restored palace courtyard.",
        "Environment animation: a wide cinematic sunrise reveals the complete fort panorama.",
    ]
    captions = [
        "भारत में यह प्राचीन मार्ग व्यापार को जोड़ता था।",
        "समय के साथ किले का निर्माण और विस्तार हुआ।",
        "इस जल प्रणाली से वर्षा का पानी सुरक्षित रखा जाता था।",
        "इतिहास का यह अध्याय आज भी प्रेरित करता है।",
        "नदी के किनारे यह किला अपनी कहानी सुनाता है।",
        "मानचित्र किले की भौगोलिक स्थिति दिखाता है।",
        "समयरेखा निर्माण के अलग-अलग काल बताती है।",
        "दीवारें और द्वार सुरक्षा का हिस्सा थे।",
        "कारीगर पत्थर पर बारीक नक्काशी करते थे।",
        "मानसून में पहाड़ी का दृश्य बदल जाता है।",
        "घेराबंदी के रास्ते रक्षा रणनीति दिखाते हैं।",
        "शासकों ने समय-समय पर किले का विस्तार किया।",
        "वर्षा जल संग्रह जीवन के लिए जरूरी था।",
        "महल का आँगन इतिहास की झलक देता है।",
        "सूर्योदय में किले का विशाल दृश्य उभरता है।",
    ]
    narration = "भारत में यह प्राचीन मार्ग व्यापार को जोड़ता था। समय के साथ किले का निर्माण और विस्तार हुआ। इस जल प्रणाली से वर्षा का पानी सुरक्षित रखा जाता था। इतिहास का यह अध्याय आज भी प्रेरित करता है। नदी के किनारे यह किला अपनी कहानी सुनाता है।"

    voice_id = "b" * 32
    music_id = "c" * 32
    _write_test_tone(audio_dir / "voice.wav", 10, 220)
    _write_test_tone(music_dir / f"{music_id}.wav", 10, 440)

    run = {
        "status": "completed",
        "format_id": "documentary",
        "topic": "भारत के ऐतिहासिक किले",
        "result": {"deliverables": {}},
        "pipeline_stages": [{"stage_id": "owner_review", "status": "completed"}],
    }
    monkeypatch.setattr(main, "DATA_DIR", data_dir)
    monkeypatch.setattr(main, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(main, "AUDIO_DIR", audio_dir)
    monkeypatch.setattr(main, "MUSIC_DIR", music_dir)
    monkeypatch.setattr(main, "IMAGE_DIR", image_dir)
    monkeypatch.setattr(main, "image_status", lambda: {
        "ai_available": True, "local_available": True, "ai_engine": "ComfyUI (local generative AI)",
    })
    image_counter = {"value": 0}

    def fake_generate_ai_image(prompt, _kind, _aspect):
        image_counter["value"] += 1
        image_id = f"{image_counter['value']:032x}"
        image = Image.new("RGB", (256, 256), (
            (image_counter["value"] * 37) % 255,
            (image_counter["value"] * 71) % 255,
            (image_counter["value"] * 113) % 255,
        ))
        image.save(image_dir / f"{image_id}.jpg", format="JPEG")
        return {"image_id": image_id, "provider": "ComfyUI (local AI)", "metadata": {"prompt": prompt}}

    monkeypatch.setattr(main, "generate_image", fake_generate_ai_image)
    monkeypatch.setattr(video_renderer, "DATA_DIR", data_dir)
    monkeypatch.setattr(video_renderer, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(main, "get_production_run", lambda *_args: run)
    monkeypatch.setattr(main, "get_research_evidence", lambda *_args: {
        "package": {"schema_version": 1}, "sha256": "evidence-sha256",
    })
    monkeypatch.setattr(main, "validate_documentary_evidence_for_production", lambda _package: {
        "valid": True, "sha256": "evidence-sha256",
    })
    monkeypatch.setattr(main, "format_render_profile", lambda _format: {
        "generic_export_available": True, "default_resolution": "720x1280", "limitations": [],
    })
    monkeypatch.setattr(main, "_approve_owner_review_for_media", lambda *_args: None)
    monkeypatch.setattr(main, "voice_status", lambda: {"local_available": True, "local_engine": "Piper TTS"})
    monkeypatch.setattr(main, "generate_voiceover", lambda _text: {
        "audio_id": voice_id, "filename": "voice.wav", "provider": "Local TTS", "voice": "Piper TTS",
    })
    monkeypatch.setattr(main, "generate_music", lambda *_args: {
        "music_id": music_id, "provider": "Local procedural test music",
    })
    monkeypatch.setattr(main, "transition_owner_media_stage", lambda *_args, **_kwargs: None)

    def fake_write_render_manifest(**_kwargs):
        manifest_path = data_dir / "production_manifests" / "test-manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps({
            "engines": {
                "image": "ComfyUI (local AI)",
                "image_providers_by_scene": ["ComfyUI (local AI)"] * len(prompts),
            },
        }), encoding="utf-8")
        return {"manifest_path": "production_manifests/test-manifest.json"}

    monkeypatch.setattr(main, "write_render_manifest", fake_write_render_manifest)
    monkeypatch.setattr(main, "create_delivery_package", lambda **_kwargs: {
        "verified": True, "path": "production_packages/test-delivery.zip",
        "filename": "test-delivery.zip", "size_bytes": 1024, "sha256": "delivery-sha256",
        "file_count": 4, "captions_included": True, "thumbnail_included": True,
        "translations_included": False, "editable_project_included": False,
        "rights_certificates_included": False, "translation_languages": [],
        "platform_metadata_status": "pending", "platform_metadata_missing_fields": [],
    })
    monkeypatch.setattr(main, "attach_render_result", lambda *_args: {"status": "completed"})

    # Use the app's explicit local-owner mode while keeping both HTTP middlewares active.
    monkeypatch.setenv("SINTU_AUTH_REQUIRED", "false")
    # Keep the normal application middleware and the actual registered API route.
    monkeypatch.setattr(main, "client_address_allowed", lambda *_args: True)
    monkeypatch.setattr(main, "production_actions_allowed", lambda: True)
    monkeypatch.setattr(main, "recover_interrupted_runs", lambda: None)
    monkeypatch.setattr(main.durable_render_queue, "recover_expired_leases", lambda: None)
    monkeypatch.setattr(main.production_factory_supervisor, "start", lambda: None)
    monkeypatch.setattr(main.production_factory_supervisor, "stop", lambda: None)
    monkeypatch.setattr(main, "start_flow_auto_import", lambda *_args: None)
    monkeypatch.setattr(main, "stop_flow_auto_import", lambda: None)

    with TestClient(main.app) as client:
        response = client.post(
            f"/api/production/runs/{run_id}/produce-media",
            json={
                "scene_prompts": prompts,
                "narration": narration,
                "subtitles": captions,
                "burn_subtitles": True,
                "sound_effects_enabled": True,
                "seconds_per_scene": 2,
                "resolution": "720x1280",
                "fps": 24,
                "quality": "standard",
            },
        )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["video_rendered"] is True
    assert result["published"] is False
    assert result["captions_burned_in"] is True
    assert len(result["subtitles"]) == 15
    assert result["render"]["animation_mode"] == "scene-aware 2D documentary animation"
    animation = result["render"]["animation_report"]
    assert animation["scene_count"] == 15
    assert animation["all_scenes_animated"] is True
    assert animation["scene_image_count"] == len(prompts)
    assert animation["scene_images_used_as_full_frame_backplates"] is True
    assert animation["scene_image_provider_summary"] == {"ComfyUI (local AI)": len(prompts)}
    assert image_counter["value"] == len(prompts)
    assert {scene["visual_type"] for scene in animation["scenes"]} == {
        "map", "timeline", "diagram", "character", "environment",
    }
    assert all(scene["motion_verified"] for scene in animation["scenes"])
    assert result["render"]["subtitles_burned_in"] is True
    assert result["render"]["brand_watermark"] == "SINTU AI YOUTUBE STUDIO"
    assert result["render"]["sound_effects"] is True
    assert result["render"]["sound_effect_cue_count"] >= 1
    assert "sound-effects" in result["render"]["audio"]
    assert "voiceover" in result["render"]["audio"]
    assert "music" in result["render"]["audio"]
    assert result["render"]["quality_report"]["verified"] is True
    documentary_qa = result["render"]["documentary_qa"]
    assert documentary_qa["passed"] is True
    assert documentary_qa["audio_quality"]["passed"] is True
    assert documentary_qa["audio_quality"]["true_peak_dbfs"] <= -1.0
    assert documentary_qa["subtitle_pixel_audit"]["cue_count"] == 15
    assert all(cue["passed"] for cue in documentary_qa["subtitle_pixel_audit"]["cues"])
    assert Path(documentary_qa["report_path"]).is_file()
    rendered_file = output_dir / result["render"]["filename"]
    assert rendered_file.is_file() and rendered_file.stat().st_size > 10_000
    assert result["delivery_package"]["verified"] is True
    manifest_path = data_dir / result["render"]["provenance_manifest"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["engines"]["image"] == "ComfyUI (local AI)"
    assert manifest["engines"]["image_providers_by_scene"] == ["ComfyUI (local AI)"] * len(prompts)
    assert result["research_evidence"]["human_fact_check_required"] is True
    assert result["render"]["quality_report"]["documentary_qa"]["passed"] is True


def test_documentary_scene_count_gate_requires_exactly_15_prompts():
    prompts = [f"Distinct documentary scene {index}" for index in range(15)]
    assert main._documentary_scene_count_error("documentary", prompts) is None
    assert "exactly 15" in main._documentary_scene_count_error("documentary", prompts[:14])
    assert "exactly 15" in main._documentary_scene_count_error("documentary", prompts + ["extra scene"])
    assert "unique scene prompts" in main._documentary_scene_count_error("documentary", prompts[:-1] + [prompts[0]])
    assert main._documentary_scene_count_error("shorts", prompts[:5]) is None


def test_documentary_image_gate_rejects_procedural_and_stock_fallbacks():
    assert main._documentary_image_requirement_error({
        "ai_available": False,
        "local_available": True,
        "local_engine": "SINTU Procedural Art (offline)",
        "local_diagnostics": {"reason": "ComfyUI is unavailable."},
    }) == (
        "Documentary production requires real local ComfyUI AI images for every scene; "
        "procedural artwork is not accepted as AI. ComfyUI is unavailable."
    )
    assert main._documentary_image_requirement_error({
        "ai_available": True,
        "local_available": True,
        "ai_engine": "ComfyUI (local generative AI)",
    }) is None


def test_documentary_voice_gate_rejects_espeak_and_accepts_piper():
    assert main._documentary_voice_requirement_error(
        "documentary", {"local_available": True, "local_engine": "eSpeak NG Hindi"}
    )
    assert main._documentary_voice_requirement_error(
        "documentary", {"local_available": True, "local_engine": "Piper TTS"}
    ) is None
    assert main._documentary_voice_requirement_error(
        "2d-cartoon", {"local_available": True, "local_engine": "eSpeak NG Hindi"}
    ) is None
