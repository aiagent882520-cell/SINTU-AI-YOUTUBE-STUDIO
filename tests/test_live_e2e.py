import json

import pytest

from scripts import live_e2e


def test_preflight_never_returns_oauth_secret_values(monkeypatch):
    monkeypatch.setenv("YOUTUBE_CLIENT_ID", "private-client-id")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET", "private-client-secret")
    monkeypatch.setenv("YOUTUBE_REDIRECT_URI", "https://example.test/oauth/callback")
    monkeypatch.setenv("YOUTUBE_TOKEN_ENCRYPTION_KEY", "private-encryption-key")
    monkeypatch.setattr(live_e2e, "provider_status", lambda: {
        "local": {"service_running": True, "model_available": True, "model": "qwen2.5:3b"}
    })
    monkeypatch.setattr(live_e2e, "image_status", lambda: {
        "local_available": True, "local_workflow_configured": True,
        "local_diagnostics": {"server_reachable": True, "workflow_valid": True},
    })
    monkeypatch.setattr(live_e2e, "video_status", lambda: {
        "local_available": True, "local_workflow_configured": True,
        "local_diagnostics": {"server_reachable": True, "workflow_valid": True},
    })
    monkeypatch.setattr(live_e2e, "voice_status", lambda: {"local_available": True, "local_model_configured": True})
    monkeypatch.setattr(live_e2e, "music_status", lambda: {"local_available": True})
    monkeypatch.setattr(live_e2e.shutil, "which", lambda name: "/usr/bin/" + name)

    report = json.dumps(live_e2e.preflight())
    assert "private-client-id" not in report
    assert "private-client-secret" not in report
    assert "private-encryption-key" not in report
    parsed = json.loads(report)
    assert parsed["youtube_oauth"]["credentials_configured"] is True
    assert parsed["youtube_oauth"]["token_encryption_configured"] is True


def test_deployment_health_rejects_plain_http_remote_and_hostname_prefix(monkeypatch):
    monkeypatch.setattr(
        live_e2e.urllib.request,
        "urlopen",
        lambda *args, **kwargs: pytest.fail("untrusted HTTP URL must be rejected before network access"),
    )
    with pytest.raises(ValueError):
        live_e2e._deployment_health("http://example.test/api/health")
    with pytest.raises(ValueError):
        live_e2e._deployment_health("http://localhost.attacker.test/api/health")


def test_deployment_health_accepts_https_and_checks_health_payload(monkeypatch):
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            return b'{"status":"ok"}'

    monkeypatch.setattr(live_e2e.urllib.request, "urlopen", lambda *args, **kwargs: FakeResponse())
    assert live_e2e._deployment_health("https://studio.example.test/api/health") == {
        "status_code": 200, "health": "ok"
    }

def test_live_agent_catalog_requires_every_registered_worker_checker_and_reviewer(monkeypatch):
    from app.agent_orchestrator import CATALOG_WORKER_ROLES
    from app.production_runtime import REVIEWERS

    steps = []
    expected_workers = list(CATALOG_WORKER_ROLES)
    for role in expected_workers:
        steps.append({"step_type": "builder", "role": role, "status": "completed"})
        steps.append({"step_type": "checker", "role": role + " Checker", "status": "pass"})
    steps.extend(
        {"step_type": "reviewer", "role": role, "status": "pass"}
        for role in REVIEWERS
    )
    monkeypatch.setattr(live_e2e, "create_run", lambda *args: {"id": "catalog-run"})
    monkeypatch.setattr(live_e2e, "execute_run", lambda *args: None)
    monkeypatch.setattr(live_e2e, "get_run", lambda *args: {
        "status": "completed", "steps": steps, "error": None
    })

    result = live_e2e._live_agent_catalog("Role coverage test")
    assert result["registered_agent_roles"] == len(CATALOG_WORKER_ROLES) == 158
    assert result["core_agent_roles"] == 61
    assert result["specialist_roles"] == 112
    assert result["senior_manager_roles"] == 5
    assert result["completed_workers"] == len(CATALOG_WORKER_ROLES)
    assert result["passed_checkers"] == len(CATALOG_WORKER_ROLES)
    assert result["final_reviewers"] == 5
    assert result["worker_role_coverage"] == len(CATALOG_WORKER_ROLES)
    assert result["checker_role_coverage"] == len(CATALOG_WORKER_ROLES)
    assert result["reviewer_role_coverage"] == 5



def test_live_agent_catalog_rejects_missing_senior_manager_coverage(monkeypatch):
    from app.agent_orchestrator import CATALOG_WORKER_ROLES
    from app.production_runtime import REVIEWERS

    steps = []
    for role in [name for name in CATALOG_WORKER_ROLES if name != "Owner Agent"]:
        steps.append({"step_type": "builder", "role": role, "status": "completed"})
        steps.append({"step_type": "checker", "role": role + " Checker", "status": "pass"})
    steps.extend(
        {"step_type": "reviewer", "role": role, "status": "pass"}
        for role in REVIEWERS
    )
    monkeypatch.setattr(live_e2e, "create_run", lambda *args: {"id": "missing-manager-run"})
    monkeypatch.setattr(live_e2e, "execute_run", lambda *args: None)
    monkeypatch.setattr(live_e2e, "get_run", lambda *args: {
        "status": "completed", "steps": steps, "error": None
    })

    with pytest.raises(RuntimeError, match="exact catalog coverage"):
        live_e2e._live_agent_catalog("Missing senior manager test")

def test_live_agent_catalog_rejects_incomplete_role_coverage(monkeypatch):
    from app.agent_orchestrator import CATALOG_WORKER_ROLES

    steps = []
    for role in CATALOG_WORKER_ROLES[:-1]:
        steps.append({"step_type": "builder", "role": role, "status": "completed"})
        steps.append({"step_type": "checker", "role": role + " Checker", "status": "pass"})
    monkeypatch.setattr(live_e2e, "create_run", lambda *args: {"id": "incomplete-run"})
    monkeypatch.setattr(live_e2e, "execute_run", lambda *args: None)
    monkeypatch.setattr(live_e2e, "get_run", lambda *args: {
        "status": "completed", "steps": steps, "error": None
    })

    with pytest.raises(RuntimeError, match="exact catalog coverage"):
        live_e2e._live_agent_catalog("Incomplete role coverage test")


def test_scene_prompt_parser_requires_six_to_twelve_numbered_prompts():
    from scripts.live_e2e import _extract_scene_prompts

    prompt_text = "Approved visual plan\nSCENE PROMPTS:\n" + "\n".join(
        f"{index}. Text-free cinematic scene {index}" for index in range(1, 7)
    )
    prompts = _extract_scene_prompts(prompt_text)
    assert len(prompts) == 6
    assert prompts[0] == "Text-free cinematic scene 1"
    with pytest.raises(RuntimeError, match="6 to 12"):
        _extract_scene_prompts("SCENE PROMPTS:\n1. Only one scene")
    with pytest.raises(RuntimeError, match="no SCENE PROMPTS"):
        _extract_scene_prompts("No approved scene section")


def test_full_studio_e2e_uses_approved_scene_and_attaches_branded_render(monkeypatch):
    scene_section = "SCENE PROMPTS:\n" + "\n".join(
        f"{index}. Approved cinematic scene {index}" for index in range(1, 7)
    )
    package = {
        "id": "full-e2e-run",
        "result": {"deliverables": {"AI Video Generator": scene_section}},
    }
    monkeypatch.setattr(live_e2e, "_live_agent_catalog", lambda topic, include_result=False: (
        {"status": "completed", "registered_agent_roles": 158}, package
    ))
    generated = []
    monkeypatch.setattr(live_e2e, "_live_video", lambda prompt: (
        generated.append(prompt) or {
            "final_render_id": "render-id",
            "render_result": {"video_id": "render-id", "brand_watermark": "SINTU AI YOUTUBE STUDIO"},
            "final_render_path": "/tmp/render.mp4",
        }
    ))
    monkeypatch.setattr(live_e2e, "attach_render_result", lambda *args: {
        "result": {"video_rendered": True, "published": False}
    })

    result = live_e2e._full_studio_e2e("Test topic")
    assert generated == [[f"Approved cinematic scene {index}" for index in range(1, 7)]]
    assert result["approved_scene_prompts"] == 6
    assert result["render_attached_to_production_run"] is True
    assert result["published"] is False


def test_full_studio_e2e_does_not_attach_if_render_is_not_approved(monkeypatch):
    package = {"id": "blocked-run", "result": {"deliverables": {
        "AI Video Generator": "SCENE PROMPTS:\n" + "\n".join(
            f"{index}. Scene {index}" for index in range(1, 7)
        )
    }}}
    monkeypatch.setattr(live_e2e, "_live_agent_catalog", lambda *args, **kwargs: ({}, package))
    monkeypatch.setattr(live_e2e, "_live_video", lambda prompt: {"render_result": {}})
    monkeypatch.setattr(live_e2e, "attach_render_result", lambda *args: {
        "result": {"video_rendered": False, "published": False}
    })
    with pytest.raises(RuntimeError, match="could not be attached"):
        live_e2e._full_studio_e2e("Test topic")


def test_live_diagnostics_load_project_env_without_overriding_process_values(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SINTU_TEST_DIAGNOSTIC_ENV=loaded-from-file\nSINTU_TEST_DIAGNOSTIC_PRECEDENCE=file-value\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("SINTU_TEST_DIAGNOSTIC_ENV", raising=False)
    monkeypatch.setenv("SINTU_TEST_DIAGNOSTIC_PRECEDENCE", "process-value")

    assert live_e2e._load_project_environment(env_file) is True
    assert live_e2e.os.environ["SINTU_TEST_DIAGNOSTIC_ENV"] == "loaded-from-file"
    assert live_e2e.os.environ["SINTU_TEST_DIAGNOSTIC_PRECEDENCE"] == "process-value"



def test_offline_storyboard_e2e_creates_verified_local_video(monkeypatch, tmp_path):
    from pathlib import Path

    image_dir = tmp_path / "images"
    audio_dir = tmp_path / "audio"
    music_dir = tmp_path / "music"
    output_dir = tmp_path / "videos"
    image_dir.mkdir()
    audio_dir.mkdir()
    music_dir.mkdir()
    output_dir.mkdir()
    for index in range(1, 16):
        (image_dir / f"image-{index}.jpg").write_bytes(b"image")
    (audio_dir / "voice.wav").write_bytes(b"audio")
    (music_dir / "music.wav").write_bytes(b"music")
    (output_dir / "final.mp4").write_bytes(b"x" * 2000)

    monkeypatch.setattr(live_e2e, "IMAGE_DIR", image_dir)
    monkeypatch.setattr(live_e2e, "AUDIO_DIR", audio_dir)
    monkeypatch.setattr(live_e2e, "MUSIC_DIR", music_dir)
    monkeypatch.setattr(live_e2e, "OUTPUT_DIR", output_dir)
    calls = []
    monkeypatch.setattr(live_e2e, "generate_image", lambda *args, **kwargs: (
        calls.append(args[0]) or {
            "image_id": f"image-{len(calls)}", "provider": "SINTU Procedural Art (offline)"
        }
    ))
    music_calls = []
    monkeypatch.setattr(live_e2e, "generate_music", lambda *args, **kwargs: (
        music_calls.append(kwargs) or {"music_id": "music", "provider": "local"}
    ))
    monkeypatch.setattr(live_e2e, "generate_voiceover", lambda text: {
        "filename": "voice.wav", "voice": "eSpeak NG Hindi", "format": "WAV"
    })
    visual_types = ["map", "timeline", "diagram", "character", "environment"]
    animation_report = {
        "engine": "SINTU scene-aware procedural 2D documentary animation",
        "scene_count": 15,
        "scene_image_count": 15,
        "scene_images_used_as_full_frame_backplates": True,
        "all_scenes_animated": True,
        "scenes": [
            {"visual_type": visual_types[index % len(visual_types)], "motion_verified": True}
            for index in range(15)
        ],
    }
    animation_calls = []
    monkeypatch.setattr(live_e2e, "render_documentary_animation_clips", lambda *args, **kwargs: (
        animation_calls.append((args, kwargs)) or ([Path(f"clip-{i}.mp4") for i in range(15)], animation_report)
    ))
    render_calls = []
    monkeypatch.setattr(live_e2e, "render_ai_clips", lambda clips, **kwargs: (
        render_calls.append((clips, kwargs)) or {
            "filename": "final.mp4", "video_id": "final-id", "duration_seconds": 60,
            "resolution": "720x1280", "brand_watermark": "SINTU AI YOUTUBE STUDIO",
            "subtitles_burned_in": True, "audio": "voiceover+music+sound-effects",
            "sound_effects": True, "sound_effect_cue_count": 29,
        }
    ))
    monkeypatch.setattr(live_e2e, "audit_documentary_mp4", lambda *args, **kwargs: {
        "passed": True, "subtitle_pixel_audit": {"passed": True, "cue_count": 15},
    })

    result = live_e2e._offline_storyboard_e2e("भारत के किले")
    assert len(calls) == 15
    assert result["scene_count"] == 15
    assert len(result["forts_covered"]) == 10
    assert len(result["research_sources"]) == 10
    assert result["research_source_count"] == 10
    assert result["research_method"] == "curated_official_sources"
    assert all(source.get("claim") and source.get("url") and source.get("source_type") for source in result["research_sources"])
    assert len({source["fort"] for source in result["research_sources"]}) == 10
    assert result["forts_covered"][0] == "भानगढ़ किला"
    assert any("Golconda" in source["fort"] for source in result["research_sources"])
    by_fort = {source["fort"]: source for source in result["research_sources"]}
    assert "curse accounts" in by_fort["Bhangarh Fort"]["claim"]
    assert "1588" in by_fort["Junagarh Fort"]["claim"]
    assert by_fort["Junagarh Fort"]["url"].endswith("/forts.html")
    assert "1459" in by_fort["Mehrangarh Fort"]["claim"]
    assert "seven gates" not in by_fort["Mehrangarh Fort"]["claim"]
    assert "folklore" in render_calls[0][1]["scene_descriptions"][1].lower()
    assert result["duration_seconds"] == 60
    assert result["subtitle_count"] == 15
    assert result["target_duration_seconds"] == 60
    assert result["subtitles_burned_in"] is True
    assert music_calls[0]["duration"] == 60
    assert animation_calls[0][0][1] == 4
    assert len(render_calls[0][0]) == 15
    assert len(render_calls[0][1]["subtitles"]) == 15
    assert render_calls[0][1]["audio_path"] == audio_dir / "voice.wav"
    assert render_calls[0][1]["music_path"] == music_dir / "music.wav"
    assert render_calls[0][1]["sound_effects_enabled"] is True
    assert render_calls[0][1]["sound_effects_volume"] == 0.18
    assert result["sound_effects"] is True
    assert result["sound_effect_cue_count"] == 29
    assert "sound-effects" in result["audio"]
    assert render_calls[0][1]["resolution"] == "720x1280"
    assert result["animation_visual_types"] == ["character", "diagram", "environment", "map", "timeline"]
    assert result["final_qa_report"]["passed"] is True
    assert result["voice_engine"] == "eSpeak NG Hindi"
    assert result["verified_by_renderer"] is True
    assert result["final_render_bytes"] == 2000


def test_offline_storyboard_e2e_rejects_missing_scene_image(monkeypatch, tmp_path):
    from pathlib import Path

    monkeypatch.setattr(live_e2e, "IMAGE_DIR", tmp_path)
    monkeypatch.setattr(live_e2e, "generate_image", lambda *args, **kwargs: {
        "image_id": "missing", "provider": "SINTU Procedural Art (offline)"
    })
    with pytest.raises(RuntimeError, match="scene image 1"):
        live_e2e._offline_storyboard_e2e("भारत के किले")

def test_preflight_does_not_report_procedural_fallback_as_comfyui(monkeypatch):
    image_status = {
        "available": True,
        "local_available": True,
        "local_engine": "SINTU Procedural Art (offline fallback)",
        "comfyui_available": False,
        "local_workflow_configured": False,
        "local_diagnostics": {
            "server_reachable": False,
            "workflow_valid": False,
            "nodes_verified": False,
            "missing_nodes": [],
            "missing_models": None,
            "reason": "API workflow file path is not configured.",
        },
    }
    report = live_e2e._safe_engine(image_status)
    assert report["available"] is False
    assert report["local_fallback_available"] is True
    assert report["local_engine"] == "SINTU Procedural Art (offline fallback)"
    assert report["workflow_configured"] is False


def test_preflight_reports_comfyui_only_when_workflow_is_ready():
    report = live_e2e._safe_engine({
        "available": True,
        "local_available": True,
        "local_engine": "ComfyUI",
        "comfyui_available": True,
        "local_workflow_configured": True,
        "local_diagnostics": {
            "server_reachable": True,
            "workflow_valid": True,
            "nodes_verified": True,
            "missing_nodes": [],
            "missing_models": [],
            "reason": None,
        },
    })
    assert report["available"] is True
    assert report["local_fallback_available"] is True




def test_preflight_missing_comfyui_flag_fails_closed_but_reports_local_fallback():
    report = live_e2e._safe_engine({
        "available": True,
        "local_available": True,
        "local_engine": "SINTU Procedural Art (offline fallback)",
        "procedural_fallback_available": True,
        "local_workflow_configured": False,
        "local_diagnostics": {
            "server_reachable": False,
            "workflow_valid": False,
            "nodes_verified": False,
            "missing_nodes": [],
            "missing_models": None,
            "reason": "Legacy status omitted the ComfyUI capability flag.",
        },
    })
    assert report["available"] is False
    assert report["local_fallback_available"] is True
    assert report["local_engine"] == "SINTU Procedural Art (offline fallback)"



def test_media_provider_acceptance_records_ai_and_piper_success():
    result = live_e2e._assert_media_provider_acceptance(
        [{"provider": "ComfyUI (local AI)"} for _ in range(15)],
        {"voice": "Piper TTS"},
        require_ai_images=True,
        require_piper_voice=True,
    )
    assert result["scene_count"] == 15
    assert result["ai_image_acceptance_passed"] is True
    assert result["piper_voice_acceptance_passed"] is True


def test_media_provider_acceptance_rejects_procedural_images_for_ai_acceptance():
    images = [
        {"provider": "ComfyUI (local AI)"},
        {"provider": "SINTU Procedural Art (offline)"},
    ]
    with pytest.raises(RuntimeError, match="every scene image"):
        live_e2e._assert_media_provider_acceptance(
            images, {"voice": "Piper TTS"}, require_ai_images=True
        )


def test_media_provider_acceptance_rejects_espeak_for_natural_voice_acceptance():
    with pytest.raises(RuntimeError, match="eSpeak is a synthetic fallback"):
        live_e2e._assert_media_provider_acceptance(
            [{"provider": "ComfyUI (local AI)"}],
            {"voice": "eSpeak NG"},
            require_piper_voice=True,
        )


def test_media_provider_acceptance_keeps_default_local_fallbacks_explicit():
    result = live_e2e._assert_media_provider_acceptance(
        [{"provider": "SINTU Procedural Art (offline)"}],
        {"voice": "eSpeak NG"},
    )
    assert result["ai_image_acceptance_required"] is False
    assert result["ai_image_acceptance_passed"] is None
    assert result["piper_voice_acceptance_required"] is False
    assert result["piper_voice_acceptance_passed"] is None
