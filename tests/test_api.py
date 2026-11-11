from fastapi.testclient import TestClient
import json
import shutil
import subprocess
import pytest

from app import main, video_renderer

def client_for_test(tmp_path, monkeypatch):
    monkeypatch.setenv("SINTU_AUTH_REQUIRED", "false")
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "test.sqlite3")
    main.init_db()
    return TestClient(main.app)

def test_health_and_catalog(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/agents").json()["total"] == 61
    workflows = client.get("/api/workflows").json()
    assert workflows["total"] >= 8
    assert "shorts" in [item["id"] for item in workflows["workflows"]]

def test_generate_save_detail_and_export(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "generate_text", lambda prompt, workflow: {
        "provider": "test", "model": "test-model", "output": "Sample production script"
    })
    result = client.post("/api/generate", json={
        "prompt": "Make a Hindi mystery short", "workflow": "shorts"
    })
    assert result.status_code == 200
    body = result.json()
    assert body["status"] == "Completed"
    task = client.get(f"/api/tasks/{body['id']}")
    assert task.status_code == 200
    assert task.json()["output"] == "Sample production script"
    exported = client.get(f"/api/export/{body['id']}")
    assert exported.status_code == 200
    assert "Sample production script" in exported.text
    markdown = client.get(f"/api/export/{body['id']}?format=md")
    assert markdown.status_code == 200
    assert "## Production package" in markdown.text
    bundle = client.get(f"/api/export/{body['id']}?format=json")
    assert bundle.status_code == 200
    assert bundle.json()["task"]["output"] == "Sample production script"
    assert "not a rendered" in bundle.json()["notice"]
    assert client.get(f"/api/export/{body['id']}?format=exe").status_code == 400

def test_invalid_prompt_is_rejected(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    result = client.post("/api/generate", json={"prompt": "   ", "workflow": "shorts"})
    assert result.status_code == 400

def test_installable_app_shell(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    page = client.get("/")
    assert page.status_code == 200
    assert 'rel="manifest"' in page.text
    assert 'navigator.serviceWorker.register("/sw.js")' in page.text
    manifest = client.get("/static/manifest.json")
    assert manifest.status_code == 200
    assert manifest.json()["display"] == "standalone"
    worker = client.get("/sw.js")
    assert worker.status_code == 200
    assert worker.headers["Service-Worker-Allowed"] == "/"
    assert client.get("/static/icon.svg").status_code == 200

def test_agent_orchestration_catalog_and_teams(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    agents = client.get("/api/agents").json()
    assert agents["total"] == 61
    assert agents["orchestration"]["workflow_teams"] == 8
    assert agents["orchestration"]["independent_agents_running"] == 0
    team = client.get("/api/workflows/shorts/team")
    assert team.status_code == 200
    names = [role["name"] for role in team.json()["team"]]
    assert "Script Writer" in names
    assert "Fact Checker" in names
    assert client.get("/api/workflows/not-real/team").status_code == 404

def test_capabilities_never_expose_provider_secrets(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    response = client.get("/api/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert body["safety"]["public_actions_require_approval"] is True
    assert "OPENAI_API_KEY" not in str(body)

def test_security_headers_are_present(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    response = client.get("/api/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in response.headers["content-security-policy"]


def test_unknown_workflow_is_rejected(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    response = client.post("/api/generate", json={"prompt": "Test", "workflow": "unknown-workflow"})
    assert response.status_code == 400


def test_storyboard_render_api_contract(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setattr(main.shutil, "which", lambda name: None)
    capability = client.get("/api/render/capabilities")
    assert capability.status_code == 200
    assert capability.json()["available"] is False
    blocked = client.post("/api/render", json={"title": "Test", "scenes": ["First scene"]})
    assert blocked.status_code == 503
    assert client.get("/api/videos/not-a-valid-id").status_code == 400


def test_storyboard_render_success_contract(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "render_storyboard", lambda title, scenes, seconds, **kwargs: {
        "video_id": "a" * 32, "url": "/api/videos/" + "a" * 32,
        "scenes": len(scenes), "duration_seconds": len(scenes) * seconds,
        "resolution": "720x1280", "format": "MP4 / H.264",
        "audio": "none", "note": "Silent text storyboard video."
    })
    result = client.post("/api/render", json={
        "title": "My Short", "scenes": ["Hook", "Main point", "CTA"], "seconds_per_scene": 3
    })
    assert result.status_code == 200
    assert result.json()["duration_seconds"] == 9
    assert result.json()["resolution"] == "720x1280"


def test_render_export_profile_validation_and_forwarding(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    captured = {}
    def fake_render(title, scenes, seconds, **kwargs):
        captured.update(kwargs)
        return {"video_id": "f" * 32, "url": "/api/videos/" + "f" * 32,
                "resolution": kwargs["resolution"], "fps": kwargs["fps"],
                "quality": kwargs["quality"], "format": "MP4 / H.264"}
    monkeypatch.setattr(main, "render_storyboard", fake_render)
    response = client.post("/api/render", json={
        "title": "Landscape test", "scenes": ["Opening"],
        "resolution": "1920x1080", "fps": 60, "quality": "maximum"
    })
    assert response.status_code == 200
    assert response.json()["resolution"] == "1920x1080"
    assert response.json()["fps"] == 60
    assert response.json()["quality"] == "maximum"
    assert captured["resolution"] == "1920x1080"
    assert captured["fps"] == 60
    assert captured["quality"] == "maximum"
    assert client.post("/api/render", json={
        "title": "Bad", "scenes": ["Opening"], "resolution": "7680x4320"
    }).status_code == 400
    assert client.post("/api/render", json={
        "title": "Bad", "scenes": ["Opening"], "fps": 48
    }).status_code == 400
    assert client.post("/api/render", json={
        "title": "Bad", "scenes": ["Opening"], "quality": "ultra"
    }).status_code == 400


def test_render_capabilities_list_export_profiles(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    profiles = client.get("/api/render/capabilities").json()["profiles"]
    assert "1080x1920" in profiles["resolutions"]
    assert profiles["fps"] == [24, 30, 60]
    assert profiles["quality"] == ["standard", "high", "maximum"]


def test_voiceover_is_disabled_by_default(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.delenv("ENABLE_PAID_MEDIA_GENERATION", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("MEDIA_GENERATION_TOKEN", "test-token")
    info = client.get("/api/voice/capabilities")
    assert info.status_code == 200
    assert info.json()["available"] is False
    result = client.post("/api/voice", json={"text": "Namaste", "voice": "alloy"},
                         headers={"X-Media-Token": "test-token"})
    assert result.status_code == 503


def test_voiceover_invalid_voice_is_rejected(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setenv("ENABLE_PAID_MEDIA_GENERATION", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("MEDIA_GENERATION_TOKEN", "test-token")
    monkeypatch.setattr(main, "generate_voiceover", lambda text, voice: (_ for _ in ()).throw(ValueError("Unsupported voice selection.")))
    result = client.post("/api/voice", json={"text": "Hello", "voice": "bad-voice"}, headers={"X-Media-Token": "test-token"})
    assert result.status_code == 400


def test_subtitle_srt_generation(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    result = client.post("/api/subtitles", json={
        "scenes": ["Namaste dosto", "Aaj hum seekhenge"], "seconds_per_scene": 4
    })
    assert result.status_code == 200
    lines = result.text.splitlines()
    assert lines[0] == "1"
    assert lines[1] == "00:00:00,000 --> 00:00:04,000"
    assert lines[2] == "Namaste dosto"
    assert lines[4] == "2"
    assert lines[5] == "00:00:04,000 --> 00:00:08,000"
    assert lines[6] == "Aaj hum seekhenge"


def test_voiceover_requires_media_access_token(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setenv("ENABLE_PAID_MEDIA_GENERATION", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("MEDIA_GENERATION_TOKEN", "expected-token")
    response = client.post("/api/voice", json={"text": "Hello", "voice": "alloy"})
    assert response.status_code == 403
    monkeypatch.setattr(main, "generate_voiceover", lambda text, voice: {
        "audio_id": "a" * 32, "url": "/api/audio/" + "a" * 32,
        "format": "MP3", "voice": voice, "size_bytes": 123
    })
    allowed = client.post("/api/voice", json={"text": "Hello", "voice": "alloy"},
                          headers={"X-Media-Token": "expected-token"})
    assert allowed.status_code == 200
    assert allowed.json()["format"] == "MP3"


def test_image_generation_is_disabled_by_default(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.delenv("ENABLE_PAID_MEDIA_GENERATION", raising=False)
    assert client.get("/api/images/capabilities").json()["available"] is False
    monkeypatch.setenv("MEDIA_GENERATION_TOKEN", "test-token")
    response = client.post("/api/images", json={"prompt": "A cinematic mountain", "kind": "scene", "aspect": "portrait"},
                           headers={"X-Media-Token": "test-token"})
    assert response.status_code == 503


def test_image_generation_requires_access_token(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setenv("ENABLE_PAID_MEDIA_GENERATION", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("MEDIA_GENERATION_TOKEN", "expected-token")
    response = client.post("/api/images", json={"prompt": "A cinematic mountain"})
    assert response.status_code == 403


def test_image_generation_endpoint_contract(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setenv("ENABLE_PAID_MEDIA_GENERATION", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("MEDIA_GENERATION_TOKEN", "expected-token")
    monkeypatch.setattr(main, "generate_image", lambda prompt, kind, aspect: {
        "image_id": "b" * 32, "url": "/api/images/" + "b" * 32,
        "kind": kind, "aspect": aspect, "width": 1536, "height": 1024,
        "format": "JPEG", "size_bytes": 1234, "model": "test-image-model"
    })
    response = client.post("/api/images", json={
        "prompt": "Cinematic mystery scene", "kind": "thumbnail", "aspect": "landscape"
    }, headers={"X-Media-Token": "expected-token"})
    assert response.status_code == 200
    assert response.json()["kind"] == "thumbnail"
    assert response.json()["width"] == 1536
    assert client.get("/api/images/" + "b" * 32).status_code == 404
    assert client.get("/api/images/not-valid").status_code == 400


def test_final_video_rejects_mismatched_image_ids(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    response = client.post("/api/render", json={
        "title": "Test", "scenes": ["One", "Two"],
        "image_ids": ["a" * 32]
    })
    assert response.status_code == 400


def test_final_video_requires_existing_audio_and_images(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    missing_image = client.post("/api/render", json={
        "title": "Test", "scenes": ["One"], "image_ids": ["a" * 32]
    })
    assert missing_image.status_code == 404
    missing_audio = client.post("/api/render", json={
        "title": "Test", "scenes": ["One"], "audio_id": "b" * 32
    })
    assert missing_audio.status_code == 404


def test_final_video_passes_assets_to_renderer(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    image_dir = tmp_path / "images"
    audio_dir = tmp_path / "audio"
    image_dir.mkdir()
    audio_dir.mkdir()
    monkeypatch.setattr(main, "IMAGE_DIR", image_dir)
    monkeypatch.setattr(main, "AUDIO_DIR", audio_dir)
    image_id, audio_id = "c" * 32, "d" * 32
    (image_dir / (image_id + ".jpg")).write_bytes(b"image-placeholder")
    (audio_dir / (audio_id + ".mp3")).write_bytes(b"audio-placeholder")
    captured = {}
    def fake_render(title, scenes, seconds, **kwargs):
        captured.update(kwargs)
        return {"video_id": "e" * 32, "url": "/api/videos/" + "e" * 32}
    monkeypatch.setattr(main, "render_storyboard", fake_render)
    result = client.post("/api/render", json={
        "title": "Final", "scenes": ["Hook"], "image_ids": [image_id],
        "audio_id": audio_id, "subtitles": ["Namaste"]
    })
    assert result.status_code == 200
    assert captured["image_paths"] == [image_dir / (image_id + ".jpg")]
    assert captured["audio_path"] == audio_dir / (audio_id + ".mp3")
    assert captured["subtitles"] == ["Namaste"]


def test_music_upload_requires_token_and_valid_extension(tmp_path, monkeypatch):
    import base64
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setenv("MEDIA_GENERATION_TOKEN", "secure-token")
    payload = {"filename": "track.mp3", "data_base64": base64.b64encode(b"fake").decode()}
    assert client.post("/api/music/upload", json=payload).status_code == 403
    bad = client.post("/api/music/upload", json={"filename": "track.exe", "data_base64": "ZmFrZQ=="},
                      headers={"X-Media-Token": "secure-token"})
    assert bad.status_code == 400
    invalid = client.post("/api/music/upload", json=payload,
                          headers={"X-Media-Token": "secure-token"})
    assert invalid.status_code in {400, 503}


def test_render_rejects_invalid_music_and_transition(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    invalid_transition = client.post("/api/render", json={
        "title": "Test", "scenes": ["One"], "transition": "explode"
    })
    assert invalid_transition.status_code == 400
    invalid_music = client.post("/api/render", json={
        "title": "Test", "scenes": ["One"], "music_id": "f" * 32
    })
    assert invalid_music.status_code == 404


def test_render_passes_music_options(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    monkeypatch.setattr(main, "MUSIC_DIR", music_dir)
    music_id = "f" * 32
    (music_dir / (music_id + ".mp3")).write_bytes(b"placeholder")
    captured = {}
    def fake_render(title, scenes, seconds, **kwargs):
        captured.update(kwargs)
        return {"video_id": "1" * 32, "url": "/api/videos/" + "1" * 32}
    monkeypatch.setattr(main, "render_storyboard", fake_render)
    response = client.post("/api/render", json={
        "title": "Music test", "scenes": ["One"], "music_id": music_id,
        "music_volume": 0.25, "transition": "fade"
    })
    assert response.status_code == 200
    assert captured["music_path"] == music_dir / (music_id + ".mp3")
    assert captured["music_volume"] == 0.25
    assert captured["transition"] == "fade"


def test_music_upload_accepts_validated_audio(tmp_path, monkeypatch):
    import base64
    import subprocess
    from types import SimpleNamespace
    client = client_for_test(tmp_path, monkeypatch)
    music_dir = tmp_path / "generated_music"
    monkeypatch.setattr(main, "MUSIC_DIR", music_dir)
    monkeypatch.setenv("MEDIA_GENERATION_TOKEN", "secure-token")
    monkeypatch.setattr(main.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout="3.5\\n", stderr=""
    ))
    response = client.post("/api/music/upload", json={
        "filename": "background.mp3",
        "data_base64": base64.b64encode(b"test-audio").decode()
    }, headers={"X-Media-Token": "secure-token"})
    assert response.status_code == 200
    body = response.json()
    assert body["format"] == "MP3"
    assert (music_dir / (body["music_id"] + ".mp3")).is_file()


def test_renderer_builds_music_mix_and_fade_filter(tmp_path, monkeypatch):
    from app import video_renderer
    from types import SimpleNamespace
    output_dir = tmp_path / "videos"
    output_dir.mkdir()
    voice = tmp_path / "voice.mp3"
    music = tmp_path / "music.mp3"
    voice.write_bytes(b"voice")
    music.write_bytes(b"music")
    captured = {}
    def fake_run(command, **kwargs):
        captured["command"] = command
        Path(command[-1]).write_bytes(b"fake-mp4")
        return SimpleNamespace(returncode=0, stderr="")
    from pathlib import Path
    monkeypatch.setattr(video_renderer, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(video_renderer.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(video_renderer.subprocess, "run", fake_run)
    result = video_renderer.render_storyboard(
        "Cinematic", ["Scene one", "Scene two"], 3,
        audio_path=voice, music_path=music, music_volume=0.2, transition="fade",
        resolution="1920x1080", fps=24, quality="maximum"
    )
    command = captured["command"]
    assert "-filter_complex" in command
    filter_graph = command[command.index("-filter_complex") + 1]
    assert "[1:a]volume=1[voice]" in filter_graph
    assert "[2:a]volume=0.2,afade=t=in:st=0:d=1.5" in filter_graph
    assert "afade=t=out:st=4:d=2" in filter_graph
    video_filter = command[command.index("-vf") + 1]
    assert "fade=t=out" in video_filter and "fade=t=in" in video_filter
    assert result["audio"] == "voiceover+music"
    assert result["transition"] == "fade"
    assert command[command.index("-r") + 1] == "24"
    assert command[command.index("-crf") + 1] == "18"
    assert result["resolution"] == "1920x1080"
    assert result["fps"] == 24
    assert result["quality"] == "maximum"


def test_render_accepts_cinematic_motion_presets(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    captured = {}
    def fake_render(title, scenes, seconds, **kwargs):
        captured.update(kwargs)
        return {"video_id": "2" * 32, "url": "/api/videos/" + "2" * 32,
                "motion": kwargs.get("motion"), "transition": kwargs.get("transition")}
    monkeypatch.setattr(main, "render_storyboard", fake_render)
    response = client.post("/api/render", json={
        "title": "Motion test", "scenes": ["Opening"],
        "motion": "slow-zoom-in", "transition": "fade"
    })
    assert response.status_code == 200
    assert captured["motion"] == "slow-zoom-in"
    assert response.json()["motion"] == "slow-zoom-in"
    invalid = client.post("/api/render", json={
        "title": "Motion test", "scenes": ["Opening"], "motion": "3d-flight"
    })
    assert invalid.status_code == 400


def test_renderer_builds_slow_zoom_filter(tmp_path, monkeypatch):
    from app import video_renderer
    from types import SimpleNamespace
    from pathlib import Path
    output_dir = tmp_path / "videos"
    output_dir.mkdir()
    captured = {}
    def fake_run(command, **kwargs):
        captured["command"] = command
        Path(command[-1]).write_bytes(b"fake-mp4")
        return SimpleNamespace(returncode=0, stderr="")
    monkeypatch.setattr(video_renderer, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(video_renderer.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(video_renderer.subprocess, "run", fake_run)
    result = video_renderer.render_storyboard(
        "Motion", ["Scene one"], 3, motion="slow-zoom-in"
    )
    command = captured["command"]
    video_filter = command[command.index("-vf") + 1]
    assert "zoompan=" in video_filter
    assert "min(zoom+0.0008,1.12)" in video_filter
    assert result["motion"] == "slow-zoom-in"


def test_ai_music_generation_is_disabled_by_default(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.delenv("ENABLE_PAID_MEDIA_GENERATION", raising=False)
    monkeypatch.delenv("STABILITY_API_KEY", raising=False)
    assert client.get("/api/music/capabilities").json()["available"] is False
    monkeypatch.setenv("MEDIA_GENERATION_TOKEN", "media-secret")
    response = client.post("/api/music/generate", json={
        "prompt": "Cinematic orchestral mystery score", "duration_seconds": 20
    }, headers={"X-Media-Token": "media-secret"})
    assert response.status_code == 503


def test_ai_music_generation_requires_media_token(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setenv("ENABLE_PAID_MEDIA_GENERATION", "true")
    monkeypatch.setenv("STABILITY_API_KEY", "stability-test-key")
    monkeypatch.setenv("MEDIA_GENERATION_TOKEN", "media-secret")
    response = client.post("/api/music/generate", json={"prompt": "Ambient score"})
    assert response.status_code == 403


def test_ai_music_generation_endpoint_contract(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setenv("ENABLE_PAID_MEDIA_GENERATION", "true")
    monkeypatch.setenv("STABILITY_API_KEY", "stability-test-key")
    monkeypatch.setenv("MEDIA_GENERATION_TOKEN", "media-secret")
    monkeypatch.setattr(main, "generate_music", lambda prompt, duration: {
        "music_id": "9" * 32, "url": "/api/music/" + "9" * 32,
        "format": "MP3", "size_bytes": 2048, "duration_seconds": duration,
        "provider": "Stability AI", "model": "stable-audio-3"
    })
    response = client.post("/api/music/generate", json={
        "prompt": "Mysterious cinematic score", "duration_seconds": 45
    }, headers={"X-Media-Token": "media-secret"})
    assert response.status_code == 200
    assert response.json()["model"] == "stable-audio-3"
    assert response.json()["duration_seconds"] == 45
    assert client.get("/api/music/" + "9" * 32).status_code == 404
    assert client.get("/api/music/not-valid").status_code == 400
    invalid = client.post("/api/music/generate", json={
        "prompt": "Ambient", "duration_seconds": 400
    }, headers={"X-Media-Token": "media-secret"})
    assert invalid.status_code == 422


def test_music_generator_validates_configuration_and_prompt(monkeypatch):
    from app import music_generator
    monkeypatch.delenv("ENABLE_PAID_MEDIA_GENERATION", raising=False)
    monkeypatch.delenv("STABILITY_API_KEY", raising=False)
    with pytest.raises(music_generator.MusicUnavailable):
        music_generator.generate_music("Ambient score", 30)
    monkeypatch.setenv("ENABLE_PAID_MEDIA_GENERATION", "true")
    monkeypatch.setenv("STABILITY_API_KEY", "test-key")
    with pytest.raises(ValueError):
        music_generator.generate_music("", 30)
    with pytest.raises(ValueError):
        music_generator.generate_music("Ambient", 361)


def test_ai_video_generation_is_disabled_by_default(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.delenv("ENABLE_PAID_MEDIA_GENERATION", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert client.get("/api/video/capabilities").json()["available"] is False
    monkeypatch.setenv("MEDIA_GENERATION_TOKEN", "media-secret")
    response = client.post("/api/video/generate", json={"prompt": "A cinematic mountain"},
                           headers={"X-Media-Token": "media-secret"})
    assert response.status_code == 503


def test_ai_video_generation_requires_media_token(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setenv("ENABLE_PAID_MEDIA_GENERATION", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.setenv("MEDIA_GENERATION_TOKEN", "media-secret")
    response = client.post("/api/video/generate", json={"prompt": "A cinematic mountain"})
    assert response.status_code == 403


def test_ai_video_generation_endpoint_contract(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setenv("ENABLE_PAID_MEDIA_GENERATION", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.setenv("MEDIA_GENERATION_TOKEN", "media-secret")
    monkeypatch.setattr(main, "generate_video", lambda prompt, aspect, resolution, style, reference, duration: {
        "video_id": "7" * 32, "url": "/api/ai-videos/" + "7" * 32,
        "format": "MP4", "size_bytes": 4096, "provider": "Google Gemini API",
        "model": "gemini-omni-1.1-flash", "aspect_ratio": aspect,
        "resolution": resolution, "style": style, "requested_duration_seconds": duration
    })
    response = client.post("/api/video/generate", json={
        "prompt": "An animated ancient temple", "aspect_ratio": "9:16",
        "resolution": "720p", "style": "3d-animation", "duration_seconds": 10
    }, headers={"X-Media-Token": "media-secret"})
    assert response.status_code == 200
    assert response.json()["model"] == "gemini-omni-1.1-flash"
    assert response.json()["style"] == "3d-animation"
    assert response.json()["requested_duration_seconds"] == 10
    assert client.get("/api/ai-videos/" + "7" * 32).status_code == 404
    assert client.get("/api/ai-videos/not-valid").status_code == 400
    invalid = client.post("/api/video/generate", json={
        "prompt": "Test", "aspect_ratio": "1:1"
    }, headers={"X-Media-Token": "media-secret"})
    assert invalid.status_code == 400


def test_ai_video_file_download(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    video_dir = tmp_path / "generated_ai_videos"
    video_dir.mkdir()
    monkeypatch.setattr(main, "AI_VIDEO_DIR", video_dir)
    video_id = "8" * 32
    path = video_dir / (video_id + ".mp4")
    path.write_bytes(b"fake-mp4")
    response = client.get("/api/ai-videos/" + video_id)
    assert response.status_code == 200
    assert response.headers["content-type"] == "video/mp4"
    assert response.content == b"fake-mp4"


def test_video_generator_validates_config_and_prompt(monkeypatch):
    from app import video_generator
    monkeypatch.delenv("ENABLE_PAID_MEDIA_GENERATION", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(video_generator.VideoUnavailable):
        video_generator.generate_video("A cinematic city")
    monkeypatch.setenv("ENABLE_PAID_MEDIA_GENERATION", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    with pytest.raises(ValueError):
        video_generator.generate_video("")
    with pytest.raises(ValueError):
        video_generator.generate_video("A city", aspect_ratio="1:1")
    with pytest.raises(ValueError):
        video_generator.generate_video("A city", style="unsupported")
    with pytest.raises(ValueError):
        video_generator.generate_video("A city", duration_seconds=11)


def test_video_generator_extracts_mp4_from_rest_steps():
    import base64
    from app.video_generator import _extract_video
    mp4 = b"1234ftypmp42fake-mp4-video-data"
    payload = {"steps": [{"type": "model_output", "content": [
        {"type": "video", "mime_type": "video/mp4", "data": base64.b64encode(mp4).decode()}
    ]}]}
    assert _extract_video(payload) == mp4


def test_video_generator_calls_gemini_and_saves_mp4(tmp_path, monkeypatch):
    import base64
    import json
    from app import video_generator
    mp4 = b"1234ftypmp42valid-video-content"
    response_body = json.dumps({"id": "interaction-test", "status": "completed", "steps": [
        {"type": "model_output", "content": [
            {"type": "video", "mime_type": "video/mp4", "data": base64.b64encode(mp4).decode()}
        ]}
    ]}).encode()
    class FakeResponse:
        headers = {}
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, limit): return response_body
    captured = {}
    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse()
    output_dir = tmp_path / "ai-videos"
    monkeypatch.setattr(video_generator, "AI_VIDEO_DIR", output_dir)
    monkeypatch.setattr(video_generator.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("ENABLE_PAID_MEDIA_GENERATION", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "test-secret")
    result = video_generator.generate_video("A cinematic forest", "9:16", "720p", "cinematic")
    body = json.loads(captured["request"].data)
    assert body["model"] == "gemini-omni-1.1-flash"
    assert body["response_format"]["aspect_ratio"] == "9:16"
    assert body["response_format"]["delivery"] == "uri"
    assert captured["timeout"] == 360
    assert result["interaction_id"] == "interaction-test"
    assert (output_dir / (result["video_id"] + ".mp4")).read_bytes() == mp4


def test_video_generator_extracts_and_downloads_uri_delivery(monkeypatch):
    import json
    from app import video_generator
    mp4 = b"1234ftypmp42uri-video-content"
    uri = "https://generativelanguage.googleapis.com/v1beta/files/abc-123:download?alt=media"
    payload = {"steps": [{"type": "model_output", "content": [
        {"type": "video", "mime_type": "video/mp4", "uri": uri}
    ]}]}
    assert video_generator._extract_video_file_id(payload) == "abc-123"
    class FakeResponse:
        def __init__(self, body): self.body = body
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, limit): return self.body
    calls = []
    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        if request.full_url.endswith("/files/abc-123"):
            return FakeResponse(json.dumps({"state": "ACTIVE"}).encode())
        return FakeResponse(mp4)
    monkeypatch.setattr(video_generator.urllib.request, "urlopen", fake_urlopen)
    assert video_generator._download_video_file("abc-123", "test-key") == mp4
    assert len(calls) == 2
    assert calls[1].endswith("/files/abc-123:download?alt=media")


def test_video_generator_uses_uri_delivery_for_large_clips(tmp_path, monkeypatch):
    import json
    from app import video_generator
    mp4 = b"1234ftypmp42large-uri-mp4-content"
    uri = "https://generativelanguage.googleapis.com/v1beta/files/large-123:download?alt=media"
    creation = json.dumps({"id": "uri-interaction", "status": "completed", "steps": [
        {"type": "model_output", "content": [{"type": "video", "uri": uri}]}
    ]}).encode()
    class FakeResponse:
        def __init__(self, body): self.body = body
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, limit): return self.body
    def fake_urlopen(request, timeout):
        if request.get_method() == "POST":
            return FakeResponse(creation)
        if request.full_url.endswith("/files/large-123"):
            return FakeResponse(b'{"state":"ACTIVE"}')
        return FakeResponse(mp4)
    output_dir = tmp_path / "ai-videos"
    monkeypatch.setattr(video_generator, "AI_VIDEO_DIR", output_dir)
    monkeypatch.setattr(video_generator.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(video_generator.time, "sleep", lambda seconds: None)
    monkeypatch.setenv("ENABLE_PAID_MEDIA_GENERATION", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    result = video_generator.generate_video("A cinematic sky")
    assert result["interaction_id"] == "uri-interaction"
    assert (output_dir / (result["video_id"] + ".mp4")).read_bytes() == mp4


def test_ai_video_clip_assembly_contract(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    clips_dir = tmp_path / "generated_ai_videos"
    clips_dir.mkdir()
    clip_ids = ["a" * 32, "b" * 32]
    for clip_id in clip_ids:
        (clips_dir / f"{clip_id}.mp4").write_bytes(b"test")
    monkeypatch.setattr(main, "AI_VIDEO_DIR", clips_dir)
    called = {}
    def fake_assembly(paths, audio_path=None, music_path=None, music_volume=0.18, subtitles=None, transition="cut", resolution="720x1280", fps=30, quality="high"):
        called["paths"] = paths
        called["subtitles"] = subtitles
        called["transition"] = transition
        return {
            "video_id": "c" * 32, "url": "/api/videos/" + "c" * 32,
            "scenes": len(paths), "duration_seconds": None,
            "resolution": "720x1280", "format": "MP4 / H.264",
            "audio": "clip-audio-not-preserved", "note": "assembled"
        }
    monkeypatch.setattr(main, "render_ai_clips", fake_assembly)
    result = client.post("/api/render", json={
        "title": "AI Short", "scenes": ["Opening clip", "Ending clip"],
        "video_ids": clip_ids, "subtitles": ["Caption one", "Caption two"], "transition": "fade"
    })
    assert result.status_code == 200
    assert result.json()["scenes"] == 2
    assert len(called["paths"]) == 2
    assert called["subtitles"] == ["Caption one", "Caption two"]
    assert called["transition"] == "fade"
    invalid = client.post("/api/render", json={
        "title": "AI Short", "scenes": ["Only one scene"],
        "video_ids": clip_ids, "transition": "cut"
    })
    assert invalid.status_code == 400
    missing = client.post("/api/render", json={
        "title": "AI Short", "scenes": ["Missing clip"],
        "video_ids": ["d" * 32]
    })
    assert missing.status_code == 404


def test_ai_clip_assembly_ffmpeg_integration(tmp_path, monkeypatch):
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg/FFprobe not installed on this runner")
    filters = subprocess.run([ffmpeg, "-filters"], capture_output=True, text=True, check=False)
    if "subtitles" not in (filters.stdout + filters.stderr):
        pytest.skip("FFmpeg subtitles filter unavailable")

    first = tmp_path / "clip-one.mp4"
    second = tmp_path / "clip-two.mp4"
    subprocess.run([
        ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i",
        "color=c=red:s=320x240:r=24:d=1", "-f", "lavfi", "-i",
        "sine=frequency=440:duration=1", "-shortest", "-c:v", "libx264",
        "-pix_fmt", "yuv420p", "-c:a", "aac", str(first)
    ], check=True, timeout=30)
    subprocess.run([
        ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i",
        "color=c=blue:s=320x240:r=24:d=1", "-t", "1", "-c:v", "libx264",
        "-pix_fmt", "yuv420p", str(second)
    ], check=True, timeout=30)

    monkeypatch.setattr(video_renderer, "OUTPUT_DIR", tmp_path / "renders")
    result = video_renderer.render_ai_clips(
        [first, second], subtitles=["First caption", "Second caption"], transition="fade"
    )
    output = tmp_path / "renders" / f'{result["video_id"]}.mp4'
    assert output.is_file()
    assert result["subtitles_burned_in"] is True
    assert result["transition"] == "fade"
    probe = subprocess.run([
        ffprobe, "-v", "error", "-show_entries", "stream=codec_type",
        "-of", "json", str(output)
    ], capture_output=True, text=True, check=True, timeout=30)
    import json
    stream_types = [item["codec_type"] for item in json.loads(probe.stdout)["streams"]]
    assert "video" in stream_types
    assert "audio" in stream_types
    assert 1.8 <= result["duration_seconds"] <= 2.2


def test_mixed_image_video_timeline_api_contract(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    images_dir = tmp_path / "generated_images"
    videos_dir = tmp_path / "generated_ai_videos"
    images_dir.mkdir()
    videos_dir.mkdir()
    image_id = "1" * 32
    video_id = "2" * 32
    (images_dir / f"{image_id}.jpg").write_bytes(b"image")
    (videos_dir / f"{video_id}.mp4").write_bytes(b"video")
    monkeypatch.setattr(main, "IMAGE_DIR", images_dir)
    monkeypatch.setattr(main, "AI_VIDEO_DIR", videos_dir)
    captured = {}
    def fake_mixed(items, title, scenes, **kwargs):
        captured["items"] = [(item["kind"], item["path"].name) for item in items]
        captured["scenes"] = scenes
        captured["durations"] = [item.get("duration") for item in items]
        captured["transitions"] = kwargs.get("transitions")
        return {"video_id": "3" * 32, "url": "/api/videos/" + "3" * 32,
                "timeline_items": len(items), "timeline_order": [x["kind"] for x in items],
                "duration_seconds": 8, "format": "MP4 / H.264"}
    monkeypatch.setattr(main, "render_mixed_timeline", fake_mixed)
    response = client.post("/api/render", json={
        "title": "Mixed timeline", "scenes": ["Image intro", "Moving clip"],
        "timeline": [f"image:{image_id}:6:fade", f"video:{video_id}:0:cut"],
        "seconds_per_scene": 4, "subtitles": ["Intro caption", ""]
    })
    assert response.status_code == 200
    assert captured["items"] == [("image", f"{image_id}.jpg"), ("video", f"{video_id}.mp4")]
    assert captured["scenes"] == ["Image intro", "Moving clip"]
    assert captured["durations"] == [6, 0]
    assert captured["transitions"] == ["fade", "cut"]
    invalid_duration = client.post("/api/render", json={
        "title": "Invalid video duration", "scenes": ["Clip"],
        "timeline": [f"video:{video_id}:5:cut"]
    })
    assert invalid_duration.status_code == 400
    bad = client.post("/api/render", json={
        "title": "Bad timeline", "scenes": ["One"],
        "timeline": [f"image:{image_id}", f"video:{video_id}"]
    })
    assert bad.status_code == 400


def test_mixed_timeline_video_trim_api_contract(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    videos_dir = tmp_path / "generated_ai_videos"
    videos_dir.mkdir()
    video_id = "4" * 32
    (videos_dir / f"{video_id}.mp4").write_bytes(b"video")
    monkeypatch.setattr(main, "AI_VIDEO_DIR", videos_dir)
    captured = {}
    def fake_mixed(items, title, scenes, **kwargs):
        captured["item"] = items[0]
        return {"video_id": "5" * 32, "url": "/api/videos/" + "5" * 32,
                "timeline_items": 1, "duration_seconds": 2.5}
    monkeypatch.setattr(main, "render_mixed_timeline", fake_mixed)
    response = client.post("/api/render", json={
        "title": "Trim test", "scenes": ["Trimmed scene"],
        "timeline": [f"video:{video_id}:1.5:4.0:cut"]
    })
    assert response.status_code == 200
    assert captured["item"]["trim_start"] == 1.5
    assert captured["item"]["trim_end"] == 4.0
    invalid = client.post("/api/render", json={
        "title": "Invalid trim", "scenes": ["Bad range"],
        "timeline": [f"video:{video_id}:5:2:cut"]
    })
    assert invalid.status_code == 400
    legacy_invalid = client.post("/api/render", json={
        "title": "Legacy invalid", "scenes": ["Bad old duration"],
        "timeline": [f"video:{video_id}:5:cut"]
    })
    assert legacy_invalid.status_code == 400


def test_mixed_timeline_clip_audio_volume_api_contract(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    videos_dir = tmp_path / "generated_ai_videos"
    videos_dir.mkdir()
    video_id = "6" * 32
    (videos_dir / f"{video_id}.mp4").write_bytes(b"video")
    monkeypatch.setattr(main, "AI_VIDEO_DIR", videos_dir)
    captured = {}
    def fake_mixed(items, title, scenes, **kwargs):
        captured["item"] = items[0]
        return {"video_id": "7" * 32, "url": "/api/videos/" + "7" * 32}
    monkeypatch.setattr(main, "render_mixed_timeline", fake_mixed)
    response = client.post("/api/render", json={
        "title": "Clip audio", "scenes": ["Scene"],
        "timeline": [f"video:{video_id}:0::1.5:cut"]
    })
    assert response.status_code == 200
    assert captured["item"]["audio_volume"] == 1.5
    invalid = client.post("/api/render", json={
        "title": "Clip audio invalid", "scenes": ["Scene"],
        "timeline": [f"video:{video_id}:0::2.5:cut"]
    })
    assert invalid.status_code == 400


def test_mixed_timeline_ffmpeg_integration(tmp_path, monkeypatch):
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg/FFprobe not installed")
    first_video = tmp_path / "moving.mp4"
    subprocess.run([
        ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i",
        "color=c=blue:s=320x240:r=24:d=1", "-f", "lavfi", "-i",
        "sine=frequency=440:duration=1", "-shortest", "-c:v", "libx264",
        "-pix_fmt", "yuv420p", "-c:a", "aac", str(first_video)
    ], check=True, timeout=30)
    from PIL import Image
    still = tmp_path / "still.jpg"
    Image.new("RGB", (320, 240), (220, 30, 30)).save(still, format="JPEG")
    monkeypatch.setattr(video_renderer, "OUTPUT_DIR", tmp_path / "mixed-renders")
    result = video_renderer.render_mixed_timeline(
        [{"kind": "image", "path": still, "duration": 3}, {"kind": "video", "path": first_video, "duration": 0}],
        "Mixed timeline", ["Image intro", "Video scene"], seconds_per_scene=2,
        subtitles=["Still caption", "Video caption"], transition="cut", transitions=["fade", "cut"],
        resolution="1080x1080", fps=24, quality="maximum"
    )
    output = tmp_path / "mixed-renders" / f'{result["video_id"]}.mp4'
    assert output.is_file()
    assert result["timeline_order"] == ["image", "video"]
    assert result["timeline_items"] == 2
    assert result["scene_transitions"] == ["fade", "cut"]
    assert result["scene_durations"] == [3, None]
    assert result["subtitles_burned_in"] is True
    assert 3.8 <= result["duration_seconds"] <= 4.2
    probe = subprocess.run([ffprobe, "-v", "error", "-show_entries", "stream=codec_type,width,height,r_frame_rate",
                            "-of", "json", str(output)], capture_output=True, text=True,
                           check=True, timeout=30)
    import json
    streams = json.loads(probe.stdout)["streams"]
    video = next(x for x in streams if x["codec_type"] == "video")
    types = [x["codec_type"] for x in streams]
    assert "video" in types and "audio" in types
    assert (video["width"], video["height"]) == (1080, 1080)
    assert video["r_frame_rate"] == "24/1"
    assert result["resolution"] == "1080x1080"
    assert result["fps"] == 24
    assert result["quality"] == "maximum"



def test_admin_auth_requires_credentials_and_protects_dashboard(tmp_path, monkeypatch):
    monkeypatch.setenv("SINTU_AUTH_REQUIRED", "true")
    monkeypatch.setenv("SINTU_ADMIN_USERNAME", "owner")
    monkeypatch.setenv("SINTU_ADMIN_PASSWORD", "a-strong-test-password")
    monkeypatch.setenv("SINTU_SESSION_SECRET", "test-session-secret-that-is-at-least-32-bytes")
    monkeypatch.setenv("SINTU_COOKIE_SECURE", "false")
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setenv("SINTU_AUTH_REQUIRED", "true")
    protected = client.get("/", follow_redirects=False)
    assert protected.status_code == 303
    assert protected.headers["location"] == "/login"
    assert client.get("/api/tasks").status_code == 401
    assert client.get("/api/health").status_code == 200
    assert client.post("/api/auth/login", json={"username": "owner", "password": "wrong-password"}).status_code == 401
    login = client.post("/api/auth/login", json={"username": "owner", "password": "a-strong-test-password"})
    assert login.status_code == 200
    assert login.json()["authenticated"] is True
    assert client.get("/api/auth/session").json()["authenticated"] is True
    assert client.get("/").status_code == 200
    assert client.get("/api/tasks").status_code == 200
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/tasks").status_code == 401


def test_admin_auth_fails_closed_without_host_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("SINTU_AUTH_REQUIRED", "true")
    monkeypatch.delenv("SINTU_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("SINTU_SESSION_SECRET", raising=False)
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setenv("SINTU_AUTH_REQUIRED", "true")
    response = client.post("/api/auth/login", json={"username": "admin", "password": "not-configured"})
    assert response.status_code == 503


def test_admin_user_management_roles_and_audit(tmp_path, monkeypatch):
    monkeypatch.setenv("SINTU_AUTH_REQUIRED", "true")
    monkeypatch.setenv("SINTU_ADMIN_USERNAME", "owner")
    monkeypatch.setenv("SINTU_ADMIN_PASSWORD", "a-strong-test-password")
    monkeypatch.setenv("SINTU_SESSION_SECRET", "test-session-secret-that-is-at-least-32-bytes")
    monkeypatch.setenv("SINTU_COOKIE_SECURE", "false")
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setenv("SINTU_AUTH_REQUIRED", "true")
    assert client.post("/api/auth/login", json={"username":"owner","password":"a-strong-test-password"}).status_code == 200
    created = client.post("/api/admin/users", json={"username":"viewer_one","password":"viewer-password-long","role":"viewer"})
    assert created.status_code == 200
    viewer_id = created.json()["id"]
    listed = client.get("/api/admin/users").json()["users"]
    assert "password_hash" not in listed[0]
    assert client.get("/api/admin/audit").status_code == 200
    assert client.patch(f"/api/admin/users/{viewer_id}", json={"role":"editor"}).json()["role"] == "editor"
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"username":"viewer_one","password":"viewer-password-long"}).json()["role"] == "editor"
    assert client.post("/api/tasks", json={"prompt":"editor can create","workflow":"shorts"}).status_code == 200
    assert client.get("/api/admin/users").status_code == 403
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username":"owner","password":"a-strong-test-password"})
    assert client.patch(f"/api/admin/users/{viewer_id}", json={"is_active":False}).json()["is_active"] == 0
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"username":"viewer_one","password":"viewer-password-long"}).status_code == 401
    client.post("/api/auth/login", json={"username":"owner","password":"a-strong-test-password"})
    assert client.patch(f"/api/admin/users/{viewer_id}", json={"is_active":True,"role":"viewer"}).status_code == 200
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"username":"viewer_one","password":"viewer-password-long"}).status_code == 200
    assert client.post("/api/tasks", json={"prompt":"viewer cannot create","workflow":"shorts"}).status_code == 403
    assert client.get("/api/tasks").status_code == 200
    assert client.get("/api/admin/audit").status_code == 403


def test_admin_cannot_disable_last_admin_or_self(tmp_path, monkeypatch):
    monkeypatch.setenv("SINTU_AUTH_REQUIRED", "true")
    monkeypatch.setenv("SINTU_ADMIN_USERNAME", "owner")
    monkeypatch.setenv("SINTU_ADMIN_PASSWORD", "a-strong-test-password")
    monkeypatch.setenv("SINTU_SESSION_SECRET", "test-session-secret-that-is-at-least-32-bytes")
    monkeypatch.setenv("SINTU_COOKIE_SECURE", "false")
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setenv("SINTU_AUTH_REQUIRED", "true")
    client.post("/api/auth/login", json={"username":"owner","password":"a-strong-test-password"})
    admin_id = client.get("/api/admin/users").json()["users"][0]["id"]
    assert client.patch(f"/api/admin/users/{admin_id}", json={"is_active":False}).status_code == 400
    assert client.patch(f"/api/admin/users/{admin_id}", json={"role":"viewer"}).status_code == 400


def test_admin_provider_settings_persist_and_never_expose_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("SINTU_AUTH_REQUIRED", "true")
    monkeypatch.setenv("SINTU_ADMIN_USERNAME", "owner")
    monkeypatch.setenv("SINTU_ADMIN_PASSWORD", "a-strong-test-password")
    monkeypatch.setenv("SINTU_SESSION_SECRET", "test-session-secret-that-is-at-least-32-bytes")
    monkeypatch.setenv("SINTU_COOKIE_SECURE", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-secret")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-secret")
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setenv("SINTU_AUTH_REQUIRED", "true")
    assert client.post("/api/auth/login", json={"username":"owner","password":"a-strong-test-password"}).status_code == 200
    settings = client.get("/api/admin/provider-settings")
    assert settings.status_code == 200
    assert settings.json()["providers"]["openai"]["configured"] is True
    assert "test-openai-secret" not in settings.text
    assert "test-gemini-secret" not in settings.text
    changed = client.patch("/api/admin/provider-settings", json={"selected_provider":"gemini"})
    assert changed.status_code == 200
    assert changed.json()["selected_provider"] == "gemini"
    assert client.get("/api/providers").json()["selected"] == "gemini"
    assert client.patch("/api/admin/provider-settings", json={"selected_provider":"claude"}).status_code == 422
    assert client.get("/api/admin/integrations").status_code == 200
    client.post("/api/auth/logout")
    assert client.get("/api/admin/provider-settings").status_code == 401


def test_admin_cannot_select_unconfigured_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("SINTU_AUTH_REQUIRED", "true")
    monkeypatch.setenv("SINTU_ADMIN_USERNAME", "owner")
    monkeypatch.setenv("SINTU_ADMIN_PASSWORD", "a-strong-test-password")
    monkeypatch.setenv("SINTU_SESSION_SECRET", "test-session-secret-that-is-at-least-32-bytes")
    monkeypatch.setenv("SINTU_COOKIE_SECURE", "false")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setenv("SINTU_AUTH_REQUIRED", "true")
    client.post("/api/auth/login", json={"username":"owner","password":"a-strong-test-password"})
    assert client.patch("/api/admin/provider-settings", json={"selected_provider":"openai"}).status_code == 400



def test_failed_task_can_be_retried(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    with main.db() as conn:
        cur = conn.execute(
            "INSERT INTO tasks(prompt,workflow,status,created_at) VALUES(?,?,?,?)",
            ("Retry this Hindi short", "shorts", "Failed", "2026-11-10T00:00:00+00:00"),
        )
        task_id = cur.lastrowid
    monkeypatch.setattr(main, "generate_text", lambda prompt, workflow: {
        "provider": "test", "model": "test-model", "output": "Recovered production package"
    })
    retried = client.post(f"/api/tasks/{task_id}/retry")
    assert retried.status_code == 200
    assert retried.json()["status"] == "Completed"
    assert retried.json()["output"] == "Recovered production package"
    detail = client.get(f"/api/tasks/{task_id}").json()
    assert detail["status"] == "Completed"
    assert detail["output"] == "Recovered production package"


def test_retry_rejects_missing_or_non_retryable_tasks(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    assert client.post("/api/tasks/999999/retry").status_code == 404
    with main.db() as conn:
        cur = conn.execute(
            "INSERT INTO tasks(prompt,workflow,status,created_at) VALUES(?,?,?,?)",
            ("Already done", "shorts", "Completed", "2026-11-10T00:00:00+00:00"),
        )
        task_id = cur.lastrowid
    assert client.post(f"/api/tasks/{task_id}/retry").status_code == 409



def test_content_calendar_create_approve_cancel_and_timezone(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    client = client_for_test(tmp_path, monkeypatch)
    future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    created = client.post("/api/calendar", json={
        "title": "Hindi science short", "platform": "youtube_shorts",
        "prompt": "Create a 45-second science short", "scheduled_at": future
    })
    assert created.status_code == 200
    item_id = created.json()["id"]
    assert created.json()["status"] == "Needs approval"
    listed = client.get("/api/calendar")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["id"] == item_id
    assert listed.json()["publishing_mode"] == "manual_approval_only"
    approved = client.post(f"/api/calendar/{item_id}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "Approved"
    assert client.post(f"/api/calendar/{item_id}/approve").status_code == 409
    cancelled = client.post(f"/api/calendar/{item_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "Cancelled"


def test_content_calendar_rejects_past_naive_and_invalid_platform(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    client = client_for_test(tmp_path, monkeypatch)
    base = {"title":"Post","platform":"youtube","prompt":"Content"}
    past = (datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
    assert client.post("/api/calendar", json={**base,"scheduled_at":past}).status_code == 400
    future_naive = (datetime.now()+timedelta(days=2)).isoformat(timespec="seconds")
    assert client.post("/api/calendar", json={**base,"scheduled_at":future_naive}).status_code == 422
    future = (datetime.now(timezone.utc)+timedelta(days=2)).isoformat()
    assert client.post("/api/calendar", json={**base,"platform":"unsupported","scheduled_at":future}).status_code == 422


def test_youtube_status_never_exposes_credentials(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setenv("YOUTUBE_CLIENT_ID", "client-id-secret")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET", "client-secret-value")
    monkeypatch.setenv("YOUTUBE_REDIRECT_URI", "https://example.test/api/admin/youtube/oauth/callback")
    monkeypatch.setenv("YOUTUBE_TOKEN_ENCRYPTION_KEY", "not-a-real-secret")
    response = client.get("/api/admin/youtube/status")
    assert response.status_code == 200
    body = response.json()
    assert body["oauth_configured"] is True
    assert body["encryption_configured"] is True
    assert "client-secret-value" not in response.text
    assert "client-id-secret" not in response.text


def test_youtube_oauth_start_requires_all_server_credentials(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    response = client.post("/api/admin/youtube/oauth/start")
    assert response.status_code == 503
    monkeypatch.setenv("YOUTUBE_CLIENT_ID", "client-id")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("YOUTUBE_REDIRECT_URI", "https://example.test/api/admin/youtube/oauth/callback")
    response = client.post("/api/admin/youtube/oauth/start")
    assert response.status_code == 503
    from cryptography.fernet import Fernet
    monkeypatch.setenv("YOUTUBE_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    response = client.post("/api/admin/youtube/oauth/start")
    assert response.status_code == 200
    assert response.json()["authorization_url"].startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "youtube.upload" in response.json()["authorization_url"]


def test_meta_status_hides_app_secrets(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setenv("META_APP_ID", "meta-app-id-private")
    monkeypatch.setenv("META_APP_SECRET", "meta-app-secret-private")
    monkeypatch.setenv("META_REDIRECT_URI", "https://example.test/api/admin/meta/oauth/callback")
    response = client.get("/api/admin/meta/status")
    assert response.status_code == 200
    assert response.json()["oauth_configured"] is True
    assert "meta-app-secret-private" not in response.text
    assert "meta-app-id-private" not in response.text


def test_meta_oauth_start_requires_credentials_and_encryption(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    assert client.post("/api/admin/meta/oauth/start").status_code == 503
    monkeypatch.setenv("META_APP_ID", "app-id")
    monkeypatch.setenv("META_APP_SECRET", "app-secret")
    monkeypatch.setenv("META_REDIRECT_URI", "https://example.test/api/admin/meta/oauth/callback")
    assert client.post("/api/admin/meta/oauth/start").status_code == 503
    from cryptography.fernet import Fernet
    monkeypatch.setenv("YOUTUBE_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    response = client.post("/api/admin/meta/oauth/start")
    assert response.status_code == 200
    assert "pages_manage_posts" in response.json()["authorization_url"]
    assert "instagram_content_publish" in response.json()["authorization_url"]


def test_meta_instagram_rejects_non_https_url(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    response = client.post("/api/admin/meta/instagram/publish/1?video_url=http://example.com/video.mp4")
    assert response.status_code == 400


def test_tiktok_status_hides_app_secrets_and_reports_setup(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setenv("TIKTOK_CLIENT_KEY", "private-client-key")
    monkeypatch.setenv("TIKTOK_CLIENT_SECRET", "private-client-secret")
    monkeypatch.setenv("TIKTOK_REDIRECT_URI", "https://example.test/api/admin/tiktok/oauth/callback")
    response = client.get("/api/admin/tiktok/status")
    assert response.status_code == 200
    assert response.json()["oauth_configured"] is True
    assert "private-client-secret" not in response.text
    assert "private-client-key" not in response.text


def test_tiktok_oauth_start_requires_credentials_and_encryption(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    assert client.post("/api/admin/tiktok/oauth/start").status_code == 503
    monkeypatch.setenv("TIKTOK_CLIENT_KEY", "client-key")
    monkeypatch.setenv("TIKTOK_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("TIKTOK_REDIRECT_URI", "https://example.test/api/admin/tiktok/oauth/callback")
    assert client.post("/api/admin/tiktok/oauth/start").status_code == 503
    from cryptography.fernet import Fernet
    monkeypatch.setenv("YOUTUBE_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    response = client.post("/api/admin/tiktok/oauth/start")
    assert response.status_code == 200
    assert "video.publish" in response.json()["authorization_url"]
    assert "state=" in response.json()["authorization_url"]


def test_tiktok_oauth_rejects_non_https_redirect(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setenv("TIKTOK_CLIENT_KEY", "client-key")
    monkeypatch.setenv("TIKTOK_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("TIKTOK_REDIRECT_URI", "http://example.test/callback")
    from cryptography.fernet import Fernet
    monkeypatch.setenv("YOUTUBE_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    response = client.post("/api/admin/tiktok/oauth/start")
    assert response.status_code == 503


def test_scheduler_queue_reports_approval_and_due_states(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    client=client_for_test(tmp_path,monkeypatch)
    now=datetime.now(timezone.utc)
    def add(title, when):
        return client.post("/api/calendar",json={"title":title,"platform":"youtube","prompt":"test",
            "scheduled_at":when.isoformat()}).json()["id"]
    awaiting=add("Awaiting approval",now+timedelta(hours=2))
    due=add("Due post",now+timedelta(minutes=5))
    later=add("Later post",now+timedelta(days=3))
    assert client.post(f"/api/calendar/{due}/approve").status_code==200
    assert client.post(f"/api/calendar/{later}/approve").status_code==200
    result=client.get("/api/admin/scheduler/queue?hours=24")
    assert result.status_code==200
    states={item["id"]:item["queue_state"] for item in result.json()["items"]}
    assert states[awaiting]=="awaiting_approval"
    assert states[due] in {"approved_upcoming","overdue_awaiting_manual_publish"}
    assert states[later]=="scheduled_later"
    assert result.json()["summary"]["awaiting_approval"]==1
    assert client.get("/api/admin/scheduler/queue?hours=0").status_code==422


def test_unified_publishing_history_filters_and_empty_state(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    response = client.get("/api/admin/publishing/history")
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["totals"]["events"] == 0
    assert client.get("/api/admin/publishing/history?platform=invalid").status_code == 422


def test_publishing_history_records_and_filters_events(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    from datetime import datetime, timedelta, timezone
    payload={"title":"History test","platform":"youtube","prompt":"Test video",
        "scheduled_at":(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()}
    item_id=client.post("/api/calendar",json=payload).json()["id"]
    from app.main import _record_publish_event
    _record_publish_event(item_id,"youtube","Published","video123","Upload succeeded","https://youtube.com/watch?v=video123")
    response=client.get("/api/admin/publishing/history")
    assert response.status_code==200
    assert response.json()["items"][0]["calendar_id"]==item_id
    assert response.json()["items"][0]["external_id"]=="video123"
    assert response.json()["totals"]["published"]==1
    assert len(client.get("/api/admin/publishing/history?platform=youtube&status=Published").json()["items"])==1
    assert client.get("/api/admin/publishing/history?platform=tiktok").json()["items"]==[]


def test_youtube_analytics_returns_official_metrics_and_top_videos(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    from app import main as app_main
    monkeypatch.setattr(app_main, "_youtube_access_token", lambda: "test-access-token")
    monkeypatch.setattr(app_main, "_youtube_connection", lambda: {"channel_title": "Test Channel"})
    calls = []
    def fake_request(url, data=None, headers=None, method=None):
        calls.append(url)
        if "currency=INR" in url:
            body = {"columnHeaders":[{"name":"estimatedRevenue"},{"name":"estimatedAdRevenue"},{"name":"estimatedRedPartnerRevenue"},{"name":"grossRevenue"},{"name":"adImpressions"},{"name":"playbackBasedCpm"}],
                "rows":[[123.45,100.0,23.45,150.0,2000,75.0]]}
        elif "dimensions=day" in url:
            body = {"columnHeaders":[{"name":"day"},{"name":"views"},{"name":"estimatedMinutesWatched"},
                {"name":"averageViewDuration"},{"name":"subscribersGained"},{"name":"subscribersLost"}],
                "rows":[["2026-11-01",100,50,30,4,1],["2026-11-02",200,120,36,5,2]]}
        else:
            body = {"columnHeaders":[{"name":"video"},{"name":"views"},{"name":"estimatedMinutesWatched"},{"name":"averageViewDuration"}],
                "rows":[["video123",250,140,34]]}
        return 200, {}, json.dumps(body).encode()
    monkeypatch.setattr(app_main, "_youtube_request", fake_request)
    response = client.get("/api/admin/youtube/analytics?start_date=2026-11-01&end_date=2026-11-02")
    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "YouTube Analytics API"
    assert data["totals"]["views"] == 300
    assert data["totals"]["subscribersGained"] == 9
    assert data["totals"]["subscribersLost"] == 3
    assert data["top_videos"][0]["video_id"] == "video123"
    assert len(calls) == 3
    assert data["revenue"]["available"] is True
    assert data["revenue"]["estimated_revenue"] == 123.45
    assert data["revenue"]["ad_impressions"] == 2000
    assert all("youtubeanalytics.googleapis.com/v2/reports" in url for url in calls)


def test_youtube_analytics_rejects_invalid_date_range(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    assert client.get("/api/admin/youtube/analytics?start_date=bad").status_code == 422
    assert client.get("/api/admin/youtube/analytics?start_date=2026-11-03&end_date=2026-11-01").status_code == 422



def test_youtube_comments_returns_heuristic_triage_and_reply_drafts(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    from app import main as app_main
    monkeypatch.setattr(app_main, "_youtube_access_token", lambda: "test-token")
    monkeypatch.setattr(app_main, "_youtube_connection", lambda: {"channel_id":"UC123","channel_title":"Test Channel"})
    def fake_request(url, data=None, headers=None, method=None):
        assert "allThreadsRelatedToChannelId=UC123" in url
        body = {"items":[
            {"snippet":{"topLevelComment":{"id":"c1","snippet":{"authorDisplayName":"A","textDisplay":"Great video, thanks!","videoId":"abcdefghijk","likeCount":2}}}},
            {"snippet":{"topLevelComment":{"id":"c2","snippet":{"authorDisplayName":"B","textDisplay":"Join my Telegram for guaranteed profit","videoId":"abcdefghijk","likeCount":0}}}},
            {"snippet":{"topLevelComment":{"id":"c3","snippet":{"authorDisplayName":"C","textDisplay":"How does this work?","videoId":"abcdefghijk","likeCount":1}}}},
        ]}
        return 200, {}, json.dumps(body).encode()
    monkeypatch.setattr(app_main, "_youtube_request", fake_request)
    response = client.get("/api/admin/youtube/comments")
    assert response.status_code == 200
    data = response.json()
    assert data["counts"]["total"] == 3
    assert data["counts"]["possible_spam"] == 1
    assert data["counts"]["positive"] == 1
    assert data["counts"]["questions"] == 1
    assert "draft-only" in data["note"].lower()


def test_youtube_comments_paginates_with_youtube_page_token(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    from app import main as app_main
    monkeypatch.setattr(app_main, "_youtube_access_token", lambda: "test-token")
    monkeypatch.setattr(app_main, "_youtube_connection", lambda: {"channel_id":"UC123","channel_title":"Test Channel"})
    captured = []
    def fake_request(url, data=None, headers=None, method=None):
        captured.append(url)
        return 200, {}, json.dumps({"items": [], "nextPageToken": "NEXT_TOKEN"}).encode()
    monkeypatch.setattr(app_main, "_youtube_request", fake_request)
    response = client.get("/api/admin/youtube/comments?limit=25&page_token=NEXT_TOKEN")
    assert response.status_code == 200
    assert "pageToken=NEXT_TOKEN" in captured[0]
    assert response.json()["next_page_token"] == "NEXT_TOKEN"


def test_youtube_comment_review_is_saved_and_returned(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    from app import main as app_main
    payload = {"comment_id":"comment-123","video_id":"abcdefghijk","review_status":"follow_up","notes":"Check context before replying"}
    saved = client.post("/api/admin/youtube/comments/review", json=payload)
    assert saved.status_code == 200
    assert saved.json()["saved"] is True
    monkeypatch.setattr(app_main, "_youtube_access_token", lambda: "test-token")
    monkeypatch.setattr(app_main, "_youtube_connection", lambda: {"channel_id":"UC123","channel_title":"Test Channel"})
    def fake_request(url, data=None, headers=None, method=None):
        body = {"items":[{"snippet":{"topLevelComment":{"id":"comment-123","snippet":{"authorDisplayName":"A","textDisplay":"Please explain","videoId":"abcdefghijk","likeCount":0}}}}]}
        return 200, {}, json.dumps(body).encode()
    monkeypatch.setattr(app_main, "_youtube_request", fake_request)
    response = client.get("/api/admin/youtube/comments")
    assert response.status_code == 200
    comment = response.json()["comments"][0]
    assert comment["review_status"] == "follow_up"
    assert comment["review_notes"] == "Check context before replying"


def test_youtube_comment_review_updates_existing_record(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    base = {"comment_id":"comment-123","video_id":"abcdefghijk","review_status":"follow_up","notes":"Needs context"}
    first = client.post("/api/admin/youtube/comments/review", json=base)
    assert first.status_code == 200
    updated = {**base, "review_status":"resolved", "notes":"Checked; no action needed"}
    second = client.post("/api/admin/youtube/comments/review", json=updated)
    assert second.status_code == 200
    assert second.json()["review_status"] == "resolved"
    with main.db() as conn:
        rows = conn.execute("SELECT review_status,notes FROM youtube_comment_reviews WHERE comment_id=?", ("comment-123",)).fetchall()
    assert len(rows) == 1
    assert rows[0]["review_status"] == "resolved"
    assert rows[0]["notes"] == "Checked; no action needed"


def test_youtube_comment_review_rejects_invalid_status(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    response = client.post("/api/admin/youtube/comments/review", json={
        "comment_id":"comment-123","video_id":"abcdefghijk","review_status":"delete","notes":"No"
    })
    assert response.status_code == 422


def test_youtube_comments_requires_connected_channel(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    from app import main as app_main
    monkeypatch.setattr(app_main, "_youtube_connection", lambda: None)
    assert client.get("/api/admin/youtube/comments").status_code == 409


def test_youtube_video_retention_returns_curve(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "_youtube_access_token", lambda: "test-token")
    captured = []
    def fake_request(url, data=None, headers=None, method=None):
        captured.append(url)
        body = {"columnHeaders":[
            {"name":"elapsedVideoTimeRatio"},{"name":"audienceWatchRatio"},
            {"name":"relativeRetentionPerformance"},{"name":"startedWatching"},{"name":"stoppedWatching"}],
            "rows":[[0.0,1.0,0.7,100,2],[0.5,0.6,0.4,1,30],[1.0,0.3,0.8,0,12]]}
        return 200, {}, json.dumps(body).encode()
    monkeypatch.setattr(main, "_youtube_request", fake_request)
    response = client.get("/api/admin/youtube/retention?video_id=abcdefghijk")
    assert response.status_code == 200
    data = response.json()
    assert data["available"] is True
    assert len(data["points"]) == 3
    assert data["points"][1]["audience_watch_ratio"] == 0.6
    assert "filters=video%3D%3Dabcdefghijk" in captured[0]


def test_youtube_video_retention_rejects_invalid_video_id(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    assert client.get("/api/admin/youtube/retention?video_id=bad").status_code == 422


def test_youtube_reach_returns_official_report_csv(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "_youtube_access_token", lambda: "test-token")
    calls = []
    def fake_request(url, data=None, headers=None, method=None):
        calls.append((url, method))
        if url.endswith("/jobs?includeSystemManaged=true"):
            body = {"jobs":[{"id":"reach-job","reportTypeId":"channel_reach_basic_a1"}]}
        elif "/reports?pageSize=50" in url:
            body = {"reports":[{"startTime":"2026-11-01T00:00:00Z","downloadUrl":"https://youtubereporting.googleapis.com/v1/media/report.csv"}]}
        elif url.endswith("/media/report.csv"):
            body = "\n".join([
                    "date,channel_id,video_id,video_thumbnail_impressions,video_thumbnail_impressions_ctr",
                    "2026-11-01,UC123,vid1,100,0.05"
                ]).encode()
            return 200, {}, body
        else:
            raise AssertionError(url)
        return 200, {}, json.dumps(body).encode()
    monkeypatch.setattr(main, "_youtube_request", fake_request)
    response = client.get("/api/admin/youtube/reach")
    assert response.status_code == 200
    data = response.json()
    assert data["totals"]["thumbnail_impressions"] == 100
    assert data["totals"]["thumbnail_ctr"] == 0.05
    assert data["top_videos"][0]["video_id"] == "vid1"


def test_youtube_reach_setup_creates_job_once(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "_youtube_access_token", lambda: "test-token")
    calls = []
    def fake_request(url, data=None, headers=None, method=None):
        calls.append((url, method))
        if url.endswith("/jobs?includeSystemManaged=true"):
            return 200, {}, json.dumps({"jobs":[]}).encode()
        if url.endswith("/reportTypes?includeSystemManaged=true"):
            return 200, {}, json.dumps({"reportTypes":[{"id":"channel_reach_basic_a1"}]}).encode()
        if url.endswith("/jobs") and method=="POST":
            return 200, {}, json.dumps({"id":"job-123","reportTypeId":"channel_reach_basic_a1"}).encode()
        raise AssertionError(url)
    monkeypatch.setattr(main, "_youtube_request", fake_request)
    response = client.post("/api/admin/youtube/reach/setup")
    assert response.status_code == 200
    assert response.json()["job_id"] == "job-123"
    assert response.json()["created"] is True


