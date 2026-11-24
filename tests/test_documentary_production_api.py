"""HTTP-level acceptance for the real Production Factory documentary media route."""
from __future__ import annotations

import math
import shutil
import struct
import subprocess
import wave
from pathlib import Path

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
    output_dir.mkdir(parents=True)
    audio_dir.mkdir(parents=True)
    music_dir.mkdir(parents=True)

    prompts = [
        "Map animation: an illustrated map traces the ancient trade route across India.",
        "Timeline animation: a chronological timeline reveals the fort's construction and later events.",
        "Diagram animation: an architectural cutaway diagram explains the hidden water system.",
        "Character animation: a historical guide walks through the palace courtyard.",
        "Environment animation: a cinematic environment shows the fort above a moving river at sunrise.",
    ]
    captions = [
        "भारत में यह प्राचीन मार्ग व्यापार को जोड़ता था।",
        "समय के साथ किले का निर्माण और विस्तार हुआ।",
        "इस जल प्रणाली से वर्षा का पानी सुरक्षित रखा जाता था।",
        "इतिहास का यह अध्याय आज भी प्रेरित करता है।",
        "नदी के किनारे यह किला अपनी कहानी सुनाता है।",
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
    monkeypatch.setattr(main, "voice_status", lambda: {"local_available": True})
    monkeypatch.setattr(main, "generate_voiceover", lambda _text: {
        "audio_id": voice_id, "filename": "voice.wav", "provider": "Local test Hindi TTS",
    })
    monkeypatch.setattr(main, "generate_music", lambda *_args: {
        "music_id": music_id, "provider": "Local procedural test music",
    })
    monkeypatch.setattr(main, "transition_owner_media_stage", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "write_render_manifest", lambda **_kwargs: {
        "manifest_path": "production_manifests/test-manifest.json",
    })
    monkeypatch.setattr(main, "create_delivery_package", lambda **_kwargs: {
        "verified": True, "path": "production_packages/test-delivery.zip",
        "filename": "test-delivery.zip", "size_bytes": 1024, "sha256": "delivery-sha256",
        "file_count": 4, "captions_included": True, "thumbnail_included": True,
        "translations_included": False, "editable_project_included": False,
        "rights_certificates_included": False, "translation_languages": [],
        "platform_metadata_status": "pending", "platform_metadata_missing_fields": [],
    })
    monkeypatch.setattr(main, "attach_render_result", lambda *_args: {"status": "completed"})

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
    assert len(result["subtitles"]) == 5
    assert result["render"]["animation_mode"] == "scene-aware 2D documentary animation"
    animation = result["render"]["animation_report"]
    assert animation["scene_count"] == 5
    assert animation["all_scenes_animated"] is True
    assert {scene["visual_type"] for scene in animation["scenes"]} == {
        "map", "timeline", "diagram", "character", "environment",
    }
    assert all(scene["motion_verified"] for scene in animation["scenes"])
    assert result["render"]["subtitles_burned_in"] is True
    assert result["render"]["brand_watermark"] == "SINTU AI YOUTUBE STUDIO"
    assert result["render"]["sound_effects"] is True
    assert "voiceover" in result["render"]["audio"]
    assert "music" in result["render"]["audio"]
    assert result["render"]["quality_report"]["verified"] is True
    documentary_qa = result["render"]["documentary_qa"]
    assert documentary_qa["passed"] is True
    assert documentary_qa["subtitle_pixel_audit"]["cue_count"] == 5
    assert all(cue["passed"] for cue in documentary_qa["subtitle_pixel_audit"]["cues"])
    assert Path(documentary_qa["report_path"]).is_file()
    rendered_file = output_dir / result["render"]["filename"]
    assert rendered_file.is_file() and rendered_file.stat().st_size > 10_000
    assert result["delivery_package"]["verified"] is True
