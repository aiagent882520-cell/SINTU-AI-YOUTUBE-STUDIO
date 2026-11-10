from fastapi.testclient import TestClient
import pytest

from app import main

def client_for_test(tmp_path, monkeypatch):
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
    assert invalid.status_code == 503


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
        audio_path=voice, music_path=music, music_volume=0.2, transition="fade"
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
        "resolution": resolution, "style": style, "duration_seconds": duration
    })
    response = client.post("/api/video/generate", json={
        "prompt": "An animated ancient temple", "aspect_ratio": "9:16",
        "resolution": "720p", "style": "3d-animation", "duration_seconds": 10
    }, headers={"X-Media-Token": "media-secret"})
    assert response.status_code == 200
    assert response.json()["model"] == "gemini-omni-1.1-flash"
    assert response.json()["style"] == "3d-animation"
    assert response.json()["duration_seconds"] == 10
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
    def fake_assembly(paths, audio_path=None, music_path=None, music_volume=0.18):
        called["paths"] = paths
        return {
            "video_id": "c" * 32, "url": "/api/videos/" + "c" * 32,
            "scenes": len(paths), "duration_seconds": None,
            "resolution": "720x1280", "format": "MP4 / H.264",
            "audio": "clip-audio-not-preserved", "note": "assembled"
        }
    monkeypatch.setattr(main, "render_ai_clips", fake_assembly)
    result = client.post("/api/render", json={
        "title": "AI Short", "scenes": ["Opening clip", "Ending clip"],
        "video_ids": clip_ids, "transition": "cut"
    })
    assert result.status_code == 200
    assert result.json()["scenes"] == 2
    assert len(called["paths"]) == 2
    invalid = client.post("/api/render", json={
        "title": "AI Short", "scenes": ["Only one scene"],
        "video_ids": clip_ids, "transition": "cut"
    })
    assert invalid.status_code == 400
    missing = client.post("/api/render", json={
        "title": "AI Short", "scenes": ["Missing clip"],
        "video_ids": ["d" * 32], "transition": "cut"
    })
    assert missing.status_code == 404
