from fastapi.testclient import TestClient

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
