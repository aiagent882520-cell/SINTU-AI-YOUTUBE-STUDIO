import sqlite3
from fastapi.testclient import TestClient
import csv
import io
import json
import shutil
import subprocess
import pytest

from app import main, video_renderer

def client_for_test(tmp_path, monkeypatch):
    monkeypatch.setenv("SINTU_AUTH_REQUIRED", "false")
    monkeypatch.setenv("SINTU_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "test.sqlite3")
    main._LOGIN_LIMITER.reset()
    main._FIREWALL_LIMITER.reset()
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
    assert 'id="adminBackupCreate"' in page.text
    assert 'id="adminBackups"' in page.text
    assert 'navigator.serviceWorker.register("/sw.js")' in page.text
    manifest = client.get("/static/manifest.json")
    assert manifest.status_code == 200
    assert manifest.json()["display"] == "standalone"
    worker = client.get("/sw.js")
    assert worker.status_code == 200
    assert worker.headers["Service-Worker-Allowed"] == "/"
    assert client.get("/static/icon.svg").status_code == 200
    assert client.get("/static/offline.html").status_code == 200
    assert "/static/production_studio.js" in worker.text
    assert "/static/production_studio.css" in worker.text
    assert "/static/app.js" in worker.text
    app_script = client.get("/static/app.js")
    assert app_script.status_code == 200
    assert "/api/admin/backups" in app_script.text
    assert "SHA-256" in app_script.text
    assert "backup-verify" in app_script.text
    assert "adminBackupHealth" in page.text
    assert "sintu-studio-shell-v12" in worker.text
    assert "/static/offline.html" in worker.text

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

def test_admin_backup_contains_consistent_database_and_generated_media_but_no_secrets(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main, "BACKUP_DIR", tmp_path / "backups")
    with main.db() as conn:
        conn.execute(
            "INSERT INTO tasks(prompt,workflow,status,created_at,output) VALUES(?,?,?,?,?)",
            ("backup regression", "shorts", "Completed", "2026-11-12T00:00:00+00:00", "saved content"),
        )
    media = tmp_path / "generated_videos"
    media.mkdir()
    (media / "sample.mp4").write_bytes(b"test-video-bytes")
    (tmp_path / ".env").write_text("OPENAI_API_KEY=must-not-be-backed-up", encoding="utf-8")
    earnings_db = tmp_path / "sintu_earnings.sqlite3"
    with sqlite3.connect(earnings_db) as conn:
        conn.execute("CREATE TABLE earning_records(id INTEGER PRIMARY KEY, title TEXT)")
        conn.execute("CREATE TABLE earning_targets(id INTEGER PRIMARY KEY, month TEXT)")
        conn.execute("INSERT INTO earning_records(title) VALUES('backup income')")


    created = client.post("/api/admin/backups")
    assert created.status_code == 200, created.text
    result = created.json()
    assert result["database_integrity"] == "ok"
    assert result["secrets_and_environment_files_included"] is False
    assert result["file_count"] == 3
    assert "sintu_earnings.sqlite3" in result["database_members"]
    archive_response = client.get(result["download_url"])
    assert archive_response.status_code == 200
    import zipfile
    archive_path = tmp_path / "downloaded-backup.zip"
    archive_path.write_bytes(archive_response.content)
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        assert "database/sintu_studio.db" in names
        assert "database/sintu_earnings.sqlite3" in names
        assert "media/generated_videos/sample.mp4" in names
        assert ".env" not in names
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["database_integrity"] == "ok"
        assert manifest["file_count"] == 3
        assert manifest["database_members"] == ["sintu_studio.db", "sintu_earnings.sqlite3"]
        database_file = tmp_path / "restored-snapshot.sqlite"
        database_file.write_bytes(archive.read("database/sintu_studio.db"))
    with sqlite3.connect(database_file) as snapshot:
        row = snapshot.execute("SELECT output FROM tasks WHERE prompt='backup regression'").fetchone()
        assert row == ("saved content",)
        assert snapshot.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    verify = client.post(result["download_url"] + "/verify")
    assert verify.status_code == 200, verify.text
    assert verify.json()["verified"] is True
    assert verify.json()["database_integrity"] == "ok"
    assert len(verify.json()["archive_sha256"]) == 64
    assert set(verify.json()["databases"]) == {"database/sintu_studio.db", "database/sintu_earnings.sqlite3"}
    health = client.get("/api/admin/backups/health")
    assert health.status_code == 200
    assert health.json()["archive_count"] == 1
    assert health.json()["freshness"] == "recent"
    assert health.json()["latest_backup"]["integrity"] == "not_checked"
    listing = client.get("/api/admin/backups")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["retention_limit"] == 5
    assert not list((tmp_path / "backups").glob(".*.sqlite"))
    assert not list((tmp_path / "backups").glob(".*.zip.tmp"))


def test_admin_backup_rejects_invalid_identifiers_and_requires_admin(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main, "BACKUP_DIR", tmp_path / "backups")
    assert client.get("/api/admin/backups/../../.env").status_code in {400, 404}
    monkeypatch.setenv("SINTU_AUTH_REQUIRED", "true")
    assert client.get("/api/admin/backups").status_code == 401


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
    monkeypatch.setenv("SINTU_REVENUE_CONFIRMED", "true")
    monkeypatch.setenv("ALLOW_PAID_UPGRADES", "true")
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
    monkeypatch.setenv("SINTU_REVENUE_CONFIRMED", "true")
    monkeypatch.setenv("ALLOW_PAID_UPGRADES", "true")
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
        "audio_id": audio_id
    })
    assert result.status_code == 200
    assert captured["image_paths"] == [image_dir / (image_id + ".jpg")]
    assert captured["audio_path"] == audio_dir / (audio_id + ".mp3")
    assert captured["subtitles"] == []


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
    monkeypatch.setattr(video_renderer, "_verify_rendered_output", lambda *args, **kwargs: {"duration_seconds": 6.0})
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
    monkeypatch.setattr(video_renderer, "_verify_rendered_output", lambda *args, **kwargs: {"duration_seconds": 3.0})
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
    assert client.get("/api/music/capabilities").json()["available"] is True
    response = client.post("/api/music/generate", json={
        "prompt": "Cinematic orchestral mystery score", "duration_seconds": 20
    })
    assert response.status_code == 200
    assert response.json()["local"] is True
    assert response.json()["format"] == "WAV"


def test_ai_music_generation_requires_media_token(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setenv("SINTU_REVENUE_CONFIRMED", "true")
    monkeypatch.setenv("ALLOW_PAID_UPGRADES", "true")
    monkeypatch.setenv("ENABLE_PAID_MEDIA_GENERATION", "true")
    monkeypatch.setenv("STABILITY_API_KEY", "stability-test-key")
    monkeypatch.setenv("MEDIA_GENERATION_TOKEN", "media-secret")
    monkeypatch.setenv("MUSIC_PROVIDER", "stability")
    response = client.post("/api/music/generate", json={"prompt": "Ambient score"})
    assert response.status_code == 403


def test_ai_music_generation_endpoint_contract(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setenv("SINTU_REVENUE_CONFIRMED", "true")
    monkeypatch.setenv("ALLOW_PAID_UPGRADES", "true")
    monkeypatch.setenv("ENABLE_PAID_MEDIA_GENERATION", "true")
    monkeypatch.setenv("STABILITY_API_KEY", "stability-test-key")
    monkeypatch.setenv("MEDIA_GENERATION_TOKEN", "media-secret")
    monkeypatch.setenv("MUSIC_PROVIDER", "stability")
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


def test_music_generator_validates_configuration_and_prompt(tmp_path, monkeypatch):
    from app import music_generator
    monkeypatch.setattr(music_generator, "MUSIC_DIR", tmp_path / "generated_music")
    monkeypatch.delenv("ENABLE_PAID_MEDIA_GENERATION", raising=False)
    monkeypatch.delenv("STABILITY_API_KEY", raising=False)
    free_track = music_generator.generate_music("Ambient score", 8)
    assert free_track["local"] is True
    assert free_track["format"] == "WAV"
    import wave
    with wave.open(str(music_generator.MUSIC_DIR / (free_track["music_id"] + ".wav")), "rb") as track:
        assert track.getnframes() == 8 * track.getframerate()
    monkeypatch.setenv("SINTU_REVENUE_CONFIRMED", "true")
    monkeypatch.setenv("ALLOW_PAID_UPGRADES", "true")
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


def test_local_ai_video_generation_does_not_require_paid_media_token(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.delenv("MEDIA_GENERATION_TOKEN", raising=False)
    monkeypatch.setattr(main, "video_status", lambda: {
        "local_available": True, "paid_available": False, "available": True
    })
    monkeypatch.setattr(main, "generate_video", lambda prompt, aspect, resolution, style, reference, duration: {
        "video_id": "6" * 32, "url": "/api/ai-videos/" + "6" * 32,
        "provider": "ComfyUI (local)", "local": True, "requested_duration_seconds": duration
    })
    response = client.post("/api/video/generate", json={"prompt": "A cinematic mountain"})
    assert response.status_code == 200, response.text
    assert response.json()["provider"] == "ComfyUI (local)"
    assert response.json()["local"] is True


def test_unavailable_video_provider_returns_service_unavailable_without_token(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.delenv("MEDIA_GENERATION_TOKEN", raising=False)
    monkeypatch.setattr(main, "video_status", lambda: {
        "local_available": False, "paid_available": False, "available": False
    })
    monkeypatch.setattr(main, "generate_video", lambda *args: (_ for _ in ()).throw(main.VideoUnavailable("Local video workflow is not ready.")))
    response = client.post("/api/video/generate", json={"prompt": "A cinematic mountain"})
    assert response.status_code == 503
    assert "not ready" in response.json()["detail"]


def test_unconfigured_local_image_and_voice_return_503_without_media_token(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.delenv("MEDIA_GENERATION_TOKEN", raising=False)
    monkeypatch.setattr(main, "image_status", lambda: {
        "local_available": False, "enabled_by_admin": False, "provider_configured": False
    })
    monkeypatch.setattr(main, "voice_status", lambda: {
        "local_available": False, "enabled_by_admin": False, "provider_configured": False
    })
    monkeypatch.setattr(main, "generate_image", lambda *args: (_ for _ in ()).throw(main.ImageUnavailable("ComfyUI image workflow is not ready.")))
    monkeypatch.setattr(main, "generate_voiceover", lambda *args: (_ for _ in ()).throw(main.VoiceUnavailable("Piper Hindi voice model is not ready.")))
    image = client.post("/api/images", json={"prompt": "A cinematic fort"})
    voice = client.post("/api/voice", json={"text": "यह एक हिंदी कहानी है"})
    assert image.status_code == 503
    assert voice.status_code == 503


def test_ai_video_generation_requires_media_token(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setenv("ENABLE_PAID_MEDIA_GENERATION", "true")
    monkeypatch.setenv("SINTU_REVENUE_CONFIRMED", "true")
    monkeypatch.setenv("ALLOW_PAID_UPGRADES", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.setenv("MEDIA_GENERATION_TOKEN", "media-secret")
    response = client.post("/api/video/generate", json={"prompt": "A cinematic mountain"})
    assert response.status_code == 403


def test_ai_video_generation_endpoint_contract(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setenv("ENABLE_PAID_MEDIA_GENERATION", "true")
    monkeypatch.setenv("SINTU_REVENUE_CONFIRMED", "true")
    monkeypatch.setenv("ALLOW_PAID_UPGRADES", "true")
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
    monkeypatch.setenv("SINTU_REVENUE_CONFIRMED", "true")
    monkeypatch.setenv("ALLOW_PAID_UPGRADES", "true")
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


def test_video_generator_extracts_mp4_from_rest_steps(monkeypatch):
    import base64
    from app import video_generator
    monkeypatch.setattr(video_generator, "_validate_video", lambda raw: raw)
    _extract_video = video_generator._extract_video
    mp4 = b"1234ftypmp42fake-mp4-video-data"
    payload = {"steps": [{"type": "model_output", "content": [
        {"type": "video", "mime_type": "video/mp4", "data": base64.b64encode(mp4).decode()}
    ]}]}
    assert _extract_video(payload) == mp4


def test_video_generator_calls_gemini_and_saves_mp4(tmp_path, monkeypatch):
    import base64
    import json
    from app import video_generator
    monkeypatch.setattr(video_generator, "_validate_video", lambda raw: raw)
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
    monkeypatch.setenv("SINTU_REVENUE_CONFIRMED", "true")
    monkeypatch.setenv("ALLOW_PAID_UPGRADES", "true")
    monkeypatch.setenv("ENABLE_PAID_MEDIA_GENERATION", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "test-secret")
    result = video_generator.generate_video("A cinematic forest", "9:16", "720p", "cinematic")
    body = json.loads(captured["request"].data)
    assert body["model"] == "gemini-omni-1.1-flash"
    assert body["response_format"]["aspect_ratio"] == "9:16"
    assert body["response_format"]["delivery"] == "uri"
    assert "no text" in body["input"].lower()
    assert "no subtitles" in body["input"].lower()
    assert "SINTU AI YOUTUBE STUDIO logo" in body["input"]
    assert captured["timeout"] == 360
    assert result["interaction_id"] == "interaction-test"
    assert (output_dir / (result["video_id"] + ".mp4")).read_bytes() == mp4


def test_video_generator_extracts_and_downloads_uri_delivery(monkeypatch):
    import json
    from app import video_generator
    monkeypatch.setattr(video_generator, "_validate_video", lambda raw: raw)
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
    monkeypatch.setattr(video_generator, "_validate_video", lambda raw: raw)
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
    monkeypatch.setenv("SINTU_REVENUE_CONFIRMED", "true")
    monkeypatch.setenv("ALLOW_PAID_UPGRADES", "true")
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
            "audio": "clip-audio-not-preserved", "note": "assembled",
            "subtitles_burned_in": False, "brand_watermark": "SINTU AI YOUTUBE STUDIO"
        }

    monkeypatch.setattr(main, "render_ai_clips", fake_assembly)
    rejected = client.post("/api/render", json={
        "title": "AI Short", "scenes": ["Opening clip", "Ending clip"],
        "video_ids": clip_ids, "subtitles": ["Caption one", "Caption two"], "transition": "fade"
    })
    assert rejected.status_code == 400
    assert "text" in rejected.json()["detail"].lower()
    assert "paths" not in called

    result = client.post("/api/render", json={
        "title": "AI Short", "scenes": ["Opening clip", "Ending clip"],
        "video_ids": clip_ids, "transition": "fade"
    })
    assert result.status_code == 200
    assert result.json()["scenes"] == 2
    assert len(called["paths"]) == 2
    assert called["subtitles"] == []
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
        [first, second], transition="fade"
    )
    output = tmp_path / "renders" / f'{result["video_id"]}.mp4'
    assert output.is_file()
    assert result["subtitles_burned_in"] is False
    assert result["brand_watermark"] == "SINTU AI YOUTUBE STUDIO"
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
    rejected = client.post("/api/render", json={
        "title": "Mixed timeline", "scenes": ["Image intro", "Moving clip"],
        "timeline": [f"image:{image_id}:6:fade", f"video:{video_id}:0:cut"],
        "seconds_per_scene": 4, "subtitles": ["Intro caption", ""]
    })
    assert rejected.status_code == 400
    response = client.post("/api/render", json={
        "title": "Mixed timeline", "scenes": ["Image intro", "Moving clip"],
        "timeline": [f"image:{image_id}:6:fade", f"video:{video_id}:0:cut"],
        "seconds_per_scene": 4
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
        transition="cut", transitions=["fade", "cut"],
        resolution="1080x1080", fps=24, quality="maximum"
    )
    output = tmp_path / "mixed-renders" / f'{result["video_id"]}.mp4'
    assert output.is_file()
    assert result["timeline_order"] == ["image", "video"]
    assert result["timeline_items"] == 2
    assert result["scene_transitions"] == ["fade", "cut"]
    assert result["scene_durations"] == [3, None]
    assert result["subtitles_burned_in"] is False
    assert result["brand_watermark"] == "SINTU AI YOUTUBE STUDIO"
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
    monkeypatch.setenv("SINTU_REVENUE_CONFIRMED", "true")
    monkeypatch.setenv("ALLOW_PAID_UPGRADES", "true")
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
    integrations = client.get("/api/admin/integrations")
    assert integrations.status_code == 200
    assert integrations.json()["analytics"]["status"] == "needs_youtube_connection"
    assert integrations.json()["analytics"]["endpoint"] == "/api/admin/youtube/analytics"
    assert "integration is implemented" in integrations.json()["analytics"]["note"].lower()
    client.post("/api/auth/logout")
    assert client.get("/api/admin/provider-settings").status_code == 401



def test_admin_integrations_reports_truthful_engine_readiness(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "admin_provider_settings", lambda: {
        "selected_provider": "local",
        "providers": {
            "local": {"configured": False, "model": "qwen2.5:3b"},
            "openai": {"configured": True, "model": "test"},
            "gemini": {"configured": False, "model": "test"},
        },
    })
    monkeypatch.setattr(main, "paid_upgrades_allowed", lambda: False)
    monkeypatch.setattr(main, "image_status", lambda: {"available": False, "local_available": False, "local_diagnostics": {"reason": "workflow missing"}, "provider": "ComfyUI local"})
    monkeypatch.setattr(main, "video_status", lambda: {"available": False, "local_available": False, "local_diagnostics": {"reason": "workflow missing"}, "provider": "ComfyUI local"})
    monkeypatch.setattr(main, "voice_status", lambda: {"available": False, "local_available": False, "provider": "Piper local", "local_engine": "Piper TTS"})
    monkeypatch.setattr(main, "music_status", lambda: {"available": True, "local_available": True, "provider": "SINTU Procedural Composer", "max_duration_seconds": 360})
    monkeypatch.setattr(main, "blender_status", lambda: {"available": False, "engine": "Blender (free/open-source)"})
    monkeypatch.setattr(main.shutil, "which", lambda name: None if name == "ffmpeg" else shutil.which(name))
    integrations = client.get("/api/admin/integrations")
    assert integrations.status_code == 200
    body = integrations.json()
    assert body["text_ai"]["status"] == "needs_local_model"
    assert body["text_ai"]["paid_upgrades_allowed"] is False
    assert body["image_generation"]["status"] == "needs_local_workflow"
    assert body["video_generation"]["status"] == "needs_local_workflow"
    assert body["voiceover"]["status"] == "needs_piper_model"
    assert body["music_generation"]["status"] == "ready_local"
    assert body["three_d_rendering"]["status"] == "needs_blender"
    assert body["video_rendering"]["status"] == "needs_ffmpeg"
    assert body["tiktok_publishing"]["status"] in {"needs_credentials", "not_connected"}
    assert body["runtime_truth"]["independent_autonomous_agents_running"] == 0
    assert "not 61 continuously running autonomous agents" in body["runtime_truth"]["note"]

def test_admin_cannot_select_unconfigured_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("SINTU_AUTH_REQUIRED", "true")
    monkeypatch.setenv("SINTU_ADMIN_USERNAME", "owner")
    monkeypatch.setenv("SINTU_ADMIN_PASSWORD", "a-strong-test-password")
    monkeypatch.setenv("SINTU_SESSION_SECRET", "test-session-secret-that-is-at-least-32-bytes")
    monkeypatch.setenv("SINTU_COOKIE_SECURE", "false")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("SINTU_REVENUE_CONFIRMED", "true")
    monkeypatch.setenv("ALLOW_PAID_UPGRADES", "true")
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



def test_agent_catalog_validation_route_starts_scoped_full_run(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    captured = {}
    run = {"id": "a" * 32, "format_id": "__agent_catalog__", "status": "queued"}

    def fake_create(format_id, topic, owner):
        captured.update(format_id=format_id, topic=topic, owner=owner)
        return run

    monkeypatch.setattr(main, "create_production_run", fake_create)
    monkeypatch.setattr(main, "execute_production_run", lambda run_id, owner: captured.update(executed=(run_id, owner)))
    monkeypatch.setattr(main, "get_production_run", lambda run_id, owner=None: {**run, "owner_username": owner})

    response = client.post("/api/admin/agent-catalog/validate", json={"topic": "पूर्ण स्टूडियो परीक्षण"})
    assert response.status_code == 202
    assert response.json()["registered_agent_roles"] == 61
    assert response.json()["expected_worker_checker_pairs"] == 61
    assert captured["format_id"] == "__agent_catalog__"
    assert captured["owner"] == "local"
    assert captured["executed"] == (run["id"], "local")
    status = client.get(f"/api/admin/agent-catalog/runs/{run['id']}")
    assert status.status_code == 200
    assert status.json()["run"]["owner_username"] == "local"


def test_agent_catalog_validation_rejects_empty_topic(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    response = client.post("/api/admin/agent-catalog/validate", json={"topic": "   "})
    assert response.status_code == 422


def test_youtube_oauth_callback_rejects_invalid_state_before_network(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "_youtube_request", lambda *args, **kwargs: pytest.fail("invalid OAuth state must not contact Google"))
    response = client.get("/api/admin/youtube/oauth/callback?code=untrusted-code&state=invalid-state")
    assert response.status_code == 400


def test_youtube_publish_requires_approved_calendar_item_and_rendered_file(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone

    client = client_for_test(tmp_path, monkeypatch)
    scheduled = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    created = client.post("/api/calendar", json={
        "title": "Approval gate", "platform": "youtube", "prompt": "Test upload",
        "scheduled_at": scheduled,
    })
    assert created.status_code == 200
    calendar_id = created.json()["id"]
    video_id = "b" * 32
    query = f"?video_id={video_id}&title=Approved%20test"
    blocked = client.post(f"/api/admin/youtube/publish/{calendar_id}" + query)
    assert blocked.status_code == 409

    with main.db() as conn:
        conn.execute("UPDATE content_calendar SET status='Approved' WHERE id=?", (calendar_id,))
    monkeypatch.setattr(main, "OUTPUT_DIR", tmp_path / "renders")
    missing = client.post(f"/api/admin/youtube/publish/{calendar_id}" + query)
    assert missing.status_code == 404

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


def test_youtube_comment_reviews_queue_persists_comment_snapshot_and_filters(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    payload = {"comment_id":"comment-queue-1","video_id":"abcdefghijk","review_status":"follow_up",
               "notes":"Need context","author":"Creator Fan","text":"Please make a part two",
               "published_at":"2026-11-10T10:00:00Z","likes":7,"classification":"positive"}
    saved = client.post("/api/admin/youtube/comments/review", json=payload)
    assert saved.status_code == 200
    all_reviews = client.get("/api/admin/youtube/comments/reviews")
    assert all_reviews.status_code == 200
    assert all_reviews.json()["total"] == 1
    record = all_reviews.json()["items"][0]
    assert record["author"] == "Creator Fan"
    assert record["text"] == "Please make a part two"
    assert record["likes"] == 7
    filtered = client.get("/api/admin/youtube/comments/reviews?review_status=resolved")
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 0
    follow_up = client.get("/api/admin/youtube/comments/reviews?review_status=follow_up")
    assert follow_up.json()["items"][0]["comment_id"] == "comment-queue-1"


def test_youtube_comment_reviews_queue_search_category_and_sort(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    base = {"video_id":"abcdefghijk","review_status":"reviewed","published_at":"2026-11-10T10:00:00Z"}
    records = [
        {**base,"comment_id":"queue-search-1","author":"Asha","text":"Great tutorial","notes":"Follow up soon","likes":3,"classification":"positive"},
        {**base,"comment_id":"queue-search-2","author":"Ravi","text":"Join my Telegram","notes":"Spam check","likes":20,"classification":"possible_spam"},
        {**base,"comment_id":"queue-search-3","author":"Meera","text":"How to install?","notes":"Answer this","likes":8,"classification":"question"},
    ]
    for item in records:
        response = client.post("/api/admin/youtube/comments/review", json=item)
        assert response.status_code == 200
    search = client.get("/api/admin/youtube/comments/reviews?search=Telegram")
    assert search.status_code == 200
    assert search.json()["total"] == 1
    assert search.json()["items"][0]["comment_id"] == "queue-search-2"
    category = client.get("/api/admin/youtube/comments/reviews?classification=question")
    assert category.json()["total"] == 1
    assert category.json()["items"][0]["author"] == "Meera"
    liked = client.get("/api/admin/youtube/comments/reviews?sort=likes")
    assert [item["likes"] for item in liked.json()["items"]] == [20, 8, 3]
    spam_first = client.get("/api/admin/youtube/comments/reviews?sort=spam")
    assert spam_first.json()["items"][0]["classification"] == "possible_spam"


def test_youtube_comment_reviews_export_respects_filters_and_csv_encoding(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    payloads = [
        {"comment_id":"csv-review-1","video_id":"abcdefghijk","review_status":"reviewed",
         "author":"Asha","text":"Great, thanks!","notes":"Keep in touch","likes":4,"classification":"positive"},
        {"comment_id":"csv-review-2","video_id":"abcdefghijk","review_status":"follow_up",
         "author":"Ravi","text":"Join Telegram","notes":"Spam","likes":12,"classification":"possible_spam"},
    ]
    for payload in payloads:
        assert client.post("/api/admin/youtube/comments/review", json=payload).status_code == 200
    response = client.get("/api/admin/youtube/comments/reviews/export?classification=possible_spam")
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "sintu-community-review-queue.csv" in response.headers["content-disposition"]
    assert response.content.startswith(bytes([0xEF, 0xBB, 0xBF]))
    assert b"csv-review-2" in response.content
    assert b"csv-review-1" not in response.content


def test_youtube_comment_review_history_records_status_and_note_changes(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    payload = {"comment_id":"history-comment-1","video_id":"abcdefghijk","review_status":"pending",
               "notes":"First note","author":"Asha","text":"Hello","classification":"positive"}
    first = client.post("/api/admin/youtube/comments/review", json=payload)
    assert first.status_code == 200
    updated = {**payload,"review_status":"follow_up","notes":"Updated note"}
    second = client.post("/api/admin/youtube/comments/review", json=updated)
    assert second.status_code == 200
    history = client.get("/api/admin/youtube/comments/reviews/history-comment-1/history")
    assert history.status_code == 200
    assert len(history.json()["items"]) == 2
    latest = history.json()["items"][0]
    assert latest["event_type"] == "updated"
    assert latest["previous_status"] == "pending"
    assert latest["new_status"] == "follow_up"
    assert latest["note_changed"] == 1
    created = history.json()["items"][1]
    assert created["event_type"] == "created"
    assert created["previous_status"] == ""


def test_youtube_comment_review_history_returns_404_for_unknown_comment(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    response = client.get("/api/admin/youtube/comments/not-saved/history")
    assert response.status_code == 404


def test_youtube_comment_reviews_bulk_status_update_and_history(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    for comment_id,status in [("bulk-review-1","pending"),("bulk-review-2","follow_up")]:
        payload = {"comment_id":comment_id,"video_id":"abcdefghijk","review_status":status,
                   "author":"Tester","text":"Saved comment","classification":"other"}
        assert client.post("/api/admin/youtube/comments/review",json=payload).status_code == 200
    response = client.post("/api/admin/youtube/comments/reviews/bulk",json={
        "comment_ids":["bulk-review-1","bulk-review-2"],"review_status":"reviewed"
    })
    assert response.status_code == 200
    assert response.json()["updated"] == 2
    queue = client.get("/api/admin/youtube/comments/reviews?review_status=reviewed")
    assert queue.json()["total"] == 2
    history = client.get("/api/admin/youtube/comments/reviews/bulk-review-1/history")
    assert history.status_code == 200
    assert history.json()["items"][0]["event_type"] == "bulk_updated"
    assert history.json()["items"][0]["previous_status"] == "pending"
    assert history.json()["items"][0]["new_status"] == "reviewed"


def test_youtube_comment_reviews_bulk_rejects_missing_ids_without_partial_updates(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    payload = {"comment_id":"bulk-existing-1","video_id":"abcdefghijk","review_status":"pending"}
    assert client.post("/api/admin/youtube/comments/review",json=payload).status_code == 200
    response = client.post("/api/admin/youtube/comments/reviews/bulk",json={
        "comment_ids":["bulk-existing-1","bulk-missing-2"],"review_status":"resolved"
    })
    assert response.status_code == 404
    existing = client.get("/api/admin/youtube/comments/reviews?review_status=pending")
    assert existing.json()["total"] == 1
    assert client.get("/api/admin/youtube/comments/reviews?review_status=resolved").json()["total"] == 0


def test_youtube_comment_review_assignment_and_follow_up_history(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    payload = {"comment_id":"assign-review-1","video_id":"abcdefghijk","review_status":"pending"}
    assert client.post("/api/admin/youtube/comments/review",json=payload).status_code == 200
    response = client.post("/api/admin/youtube/comments/reviews/assign",json={
        "comment_ids":["assign-review-1"],"assigned_to":"Community Team","follow_up_at":"2026-11-15"
    })
    assert response.status_code == 200
    saved = client.get("/api/admin/youtube/comments/reviews?review_status=pending").json()["items"][0]
    assert saved["assigned_to"] == "Community Team"
    assert saved["follow_up_at"] == "2026-11-15"
    history = client.get("/api/admin/youtube/comments/reviews/assign-review-1/history").json()["items"][0]
    assert history["event_type"] == "assignment_updated"
    assert history["new_assigned_to"] == "Community Team"
    assert history["new_follow_up_at"] == "2026-11-15"


def test_youtube_comment_review_assignment_missing_id_is_atomic(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    payload = {"comment_id":"assign-existing-1","video_id":"abcdefghijk","review_status":"pending"}
    assert client.post("/api/admin/youtube/comments/review",json=payload).status_code == 200
    response = client.post("/api/admin/youtube/comments/reviews/assign",json={
        "comment_ids":["assign-existing-1","assign-missing-2"],"assigned_to":"Team","follow_up_at":""
    })
    assert response.status_code == 404
    saved = client.get("/api/admin/youtube/comments/reviews?review_status=pending").json()["items"][0]
    assert saved["assigned_to"] == ""




def test_youtube_comment_follow_up_workload_csv_export(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    for cid,owner,due,status in [
        ("csv-overdue","Team A","2026-11-10","follow_up"),
        ("csv-today","Team A","2026-11-11","pending"),
        ("csv-resolved","Team B","2026-11-15","resolved"),
    ]:
        payload={"comment_id":cid,"video_id":"abcdefghijk","review_status":status,
                 "assigned_to":owner,"follow_up_at":due}
        assert client.post("/api/admin/youtube/comments/review",json=payload).status_code==200
    response=client.get("/api/admin/youtube/comments/reviews/follow-ups/export?as_of=2026-11-11")
    assert response.status_code==200
    assert "text/csv" in response.headers["content-type"]
    assert "sintu-community-follow-up-workload.csv" in response.headers["content-disposition"]
    rows=list(csv.reader(io.StringIO(response.text.lstrip("\\ufeff"))))
    assert rows[1][0:3]==["overall","2026-11-11","All owners"]
    team_a=next(row for row in rows[2:] if row[2]=="Team A")
    assert team_a[3:10]==["2","2","0","1","1","0","0"]
    team_b=next(row for row in rows[2:] if row[2]=="Team B")
    assert team_b[3:6]==["1","0","1"]
    invalid=client.get("/api/admin/youtube/comments/reviews/follow-ups/export?as_of=bad")
    assert invalid.status_code==422

def test_youtube_comment_follow_up_due_inbox_excludes_resolved_and_future(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    for cid,due,status in [
        ("inbox-overdue","2026-11-09","pending"),
        ("inbox-today","2026-11-11","follow_up"),
        ("inbox-resolved","2026-11-10","resolved"),
        ("inbox-future","2026-11-12","pending"),
    ]:
        payload={"comment_id":cid,"video_id":"abcdefghijk","review_status":status,
                 "follow_up_at":due,"assigned_to":"Community Team","text":"Please review"}
        assert client.post("/api/admin/youtube/comments/review",json=payload).status_code==200
    result=client.get("/api/admin/youtube/comments/reviews/follow-ups/due?as_of=2026-11-11").json()
    assert result["total"]==2
    assert {item["comment_id"]:item["due_state"] for item in result["items"]}=={
        "inbox-overdue":"overdue","inbox-today":"due_today"
    }
    assert client.get("/api/admin/youtube/comments/reviews/follow-ups/due?as_of=bad").status_code==422


def test_youtube_comment_follow_up_summary_and_owner_workload(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    for cid,owner,due,status in [
        ("due-overdue","Team A","2026-11-10","follow_up"),
        ("due-today","Team A","2026-11-11","pending"),
        ("due-future","Team B","2026-11-15","resolved"),
        ("due-none","","","pending"),
    ]:
        payload={"comment_id":cid,"video_id":"abcdefghijk","review_status":status,
                 "assigned_to":owner,"follow_up_at":due}
        assert client.post("/api/admin/youtube/comments/review",json=payload).status_code==200
    summary=client.get("/api/admin/youtube/comments/reviews/follow-ups/summary?as_of=2026-11-11").json()
    assert summary["totals"]["overdue"]==1
    assert summary["totals"]["due_today"]==1
    assert summary["totals"]["upcoming"]==1
    assert summary["totals"]["unscheduled"]==1
    assert summary["totals"]["resolved"]==1
    team_a=next(row for row in summary["owners"] if row["owner"]=="Team A")
    assert team_a["total"]==2 and team_a["overdue"]==1
    assert team_a["open"]==2 and team_a["resolved"]==0
    assert team_a["resolution_rate"]==0
    assert team_a["follow_up_coverage"]==100
    assert summary["totals"]["open"]==3 and summary["totals"]["resolution_rate"]==25



def test_youtube_comment_follow_up_queue_filters_and_invalid_date(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    for cid,due in [("filter-overdue","2026-11-10"),("filter-today","2026-11-11"),("filter-none","")]:
        payload={"comment_id":cid,"video_id":"abcdefghijk","review_status":"pending",
                 "assigned_to":"Community Team","follow_up_at":due}
        assert client.post("/api/admin/youtube/comments/review",json=payload).status_code==200
    overdue=client.get("/api/admin/youtube/comments/reviews?follow_up_filter=overdue&as_of=2026-11-11")
    assert overdue.json()["total"]==1
    owner=client.get("/api/admin/youtube/comments/reviews?assigned_to=Community%20Team")
    assert owner.json()["total"]==3
    invalid=client.get("/api/admin/youtube/comments/reviews/follow-ups/summary?as_of=11-11-2026")
    assert invalid.status_code==422


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




def test_complete_production_catalog_and_project_studio(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    response = client.get("/api/production-catalog")
    assert response.status_code == 200
    data = response.json()
    formats = {item["id"]: item for item in data["formats"]}
    assert len(formats) >= 20
    assert formats["youtube-shorts"]["aspect_ratio"] == "9:16"
    assert formats["documentary"]["aspect_ratio"] == "16:9"
    assert formats["3d-animation"]["stage"] == "prompt_and_storyboard"
    assert len(data["pipeline"]) == 8
    assert {item["id"] for item in data["presets"]} >= {"mystery-short", "documentary", "faceless"}
    page = client.get("/")
    assert 'id="productionStudio"' in page.text
    assert "/static/production_studio.js" in page.text
    assert "/static/production_studio.css" in page.text
    assert client.get("/static/production_studio.js").status_code == 200
    assert client.get("/static/production_studio.css").status_code == 200


def test_production_projects_server_crud_export_and_validation(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    payload = {
        "name": "Hindi Mystery Short",
        "brief": "भारत की रहस्यमयी जगह पर तथ्य-जाँचा हुआ वीडियो बनाओ।",
        "format_id": "youtube-shorts",
        "language": "Hindi",
        "duration_seconds": 60,
    }
    created = client.post("/api/projects", json=payload)
    assert created.status_code == 201
    project = created.json()["project"]
    assert project["name"] == payload["name"]
    assert project["owner_username"] == "local"
    project_id = project["id"]

    listing = client.get("/api/projects")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["projects"][0]["id"] == project_id

    detail = client.get(f"/api/projects/{project_id}")
    assert detail.status_code == 200
    assert detail.json()["project"]["brief"] == payload["brief"]

    changed = {**payload, "name": "Updated Mystery Short", "duration_seconds": 90}
    updated = client.put(f"/api/projects/{project_id}", json=changed)
    assert updated.status_code == 200
    assert updated.json()["project"]["version"] == 2
    assert updated.json()["project"]["duration_seconds"] == 90

    exported = client.get(f"/api/projects/{project_id}/export")
    assert exported.status_code == 200
    assert exported.json()["project"]["format"]["id"] == "youtube-shorts"
    assert len(exported.json()["project"]["pipeline"]) == 8

    invalid = client.post("/api/projects", json={**payload, "format_id": "unknown"})
    assert invalid.status_code == 400
    assert client.delete(f"/api/projects/{project_id}").json()["deleted"] is True
    assert client.get(f"/api/projects/{project_id}").status_code == 404


def test_production_project_input_limits_and_bad_ids(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    payload = {"name": "Bad", "brief": "Brief", "format_id": "youtube-shorts",
               "language": "Hindi", "duration_seconds": 2}
    assert client.post("/api/projects", json=payload).status_code == 422
    assert client.get("/api/projects/not-an-id").status_code == 400
    assert client.delete("/api/projects/not-an-id").status_code == 400


def test_production_studio_has_direct_generation_action(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    page = client.get("/")
    assert page.status_code == 200
    assert 'id="generateProductionPackage"' in page.text
    script = client.get("/static/production_studio.js")
    assert script.status_code == 200
    assert 'workflowMap' in script.text
    assert 'data-view-project-output' in script.text
    assert '/task-output' in script.text
    assert 'fetch("/api/projects/"' in script.text
    assert '"/generate"' in script.text


def test_docker_compose_forwards_optional_integration_secrets():
    from pathlib import Path
    compose = (Path(__file__).resolve().parents[1] / "docker-compose.yml").read_text(encoding="utf-8")
    for key in [
        "OPENAI_API_KEY", "GEMINI_API_KEY", "STABILITY_API_KEY",
        "YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REDIRECT_URI",
        "YOUTUBE_TOKEN_ENCRYPTION_KEY", "META_APP_ID", "META_APP_SECRET",
        "META_REDIRECT_URI", "TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET",
        "TIKTOK_REDIRECT_URI", "MEDIA_GENERATION_TOKEN"
    ]:
        assert key + ":" in compose
    assert "OPENAI_MODEL:-gpt-5.5" in compose
    assert "GEMINI_MODEL:-gemini-2.5-flash" in compose


def test_production_studio_prompt_uses_real_line_break_escapes(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    script = client.get("/static/production_studio.js").text
    assert '\\\\nLanguage:' not in script
    assert '"\\\\nLanguage:' not in script


def test_saved_production_project_generates_and_links_ai_task(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    captured = {}
    monkeypatch.setattr(main, "generate_text", lambda prompt, workflow: (
        captured.update({"prompt": prompt, "workflow": workflow}) or {
            "provider": "test", "model": "test-model", "output": "Complete scene-by-scene production package"
        }
    ))
    created = client.post("/api/projects", json={
        "name": "Linked project", "brief": "Make a Hindi mystery short.",
        "format_id": "youtube-shorts", "language": "Hindi", "duration_seconds": 60
    })
    assert created.status_code == 201
    project_id = created.json()["project"]["id"]
    generated = client.post(f"/api/projects/{project_id}/generate", json={"workflow": "shorts"})
    assert generated.status_code == 200
    data = generated.json()
    assert data["task"]["status"] == "Completed"
    assert data["task"]["output"] == "Complete scene-by-scene production package"
    assert data["project"]["last_task_id"] == data["task"]["id"]
    assert data["project"]["last_task_status"] == "Completed"
    assert captured["workflow"] == "shorts"
    assert "scene-by-scene Hindi narration" in captured["prompt"]
    assert "on-screen text" not in captured["prompt"].lower()
    assert "do not include any visible text" in captured["prompt"].lower()
    assert "only the SINTU AI YOUTUBE STUDIO brand watermark" in captured["prompt"]


def test_saved_production_project_generation_rejects_unknown_workflow(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    created = client.post("/api/projects", json={
        "name": "Bad workflow", "brief": "Make a video.",
        "format_id": "youtube-shorts", "language": "Hindi", "duration_seconds": 60
    })
    project_id = created.json()["project"]["id"]
    response = client.post(f"/api/projects/{project_id}/generate", json={"workflow": "unknown"})
    assert response.status_code == 400


def test_production_projects_are_scoped_to_signed_in_owner(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "_production_project_owner",
                        lambda request: request.headers.get("x-test-owner", "local"))
    created = client.post("/api/projects", json={
        "name": "Private project", "brief": "Private brief.",
        "format_id": "youtube-shorts", "language": "Hindi", "duration_seconds": 60
    })
    project_id = created.json()["project"]["id"]
    assert client.get("/api/projects").json()["total"] == 1
    other_headers = {"x-test-owner": "another-user"}
    assert client.get("/api/projects", headers=other_headers).json()["total"] == 0
    assert client.get(f"/api/projects/{project_id}", headers=other_headers).status_code == 404
    assert client.delete(f"/api/projects/{project_id}", headers=other_headers).status_code == 404


def test_production_project_schema_upgrades_existing_installation(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    with main.db() as conn:
        conn.execute("DROP TABLE IF EXISTS production_projects")
        conn.execute("""
            CREATE TABLE production_projects (
                id TEXT PRIMARY KEY, owner_username TEXT NOT NULL, name TEXT NOT NULL,
                brief TEXT NOT NULL, format_id TEXT NOT NULL, language TEXT NOT NULL,
                duration_seconds INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'Draft',
                version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )
        """)
    assert client.get("/api/projects").status_code == 200
    with main.db() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(production_projects)").fetchall()}
    assert {"last_task_id", "last_task_status", "last_task_updated_at"} <= columns


def test_project_generation_marks_provider_missing_without_fake_output(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    created = client.post("/api/projects", json={
        "name": "Provider pending", "brief": "Make a Hindi video.",
        "format_id": "youtube-shorts", "language": "Hindi", "duration_seconds": 60
    })
    project_id = created.json()["project"]["id"]
    def no_provider(prompt, workflow):
        raise main.ProviderNotConfigured("No AI provider key configured.")
    monkeypatch.setattr(main, "generate_text", no_provider)
    response = client.post(f"/api/projects/{project_id}/generate", json={"workflow": "shorts"})
    assert response.status_code == 503
    saved = client.get(f"/api/projects/{project_id}").json()["project"]
    assert saved["last_task_status"] == "Blocked"
    assert saved["last_task_id"] is None


def test_windows_bootstrap_generates_secure_local_login_without_api_keys(tmp_path, monkeypatch, capsys):
    import importlib.util
    from pathlib import Path
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap_local.py"
    spec = importlib.util.spec_from_file_location("sintu_bootstrap_local", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ENV_FILE = tmp_path / ".env"
    module.EXAMPLE_FILE = Path(__file__).resolve().parents[1] / ".env.example"
    module.main()
    content = module.ENV_FILE.read_text(encoding="utf-8")
    assert "SINTU_AUTH_REQUIRED=true" in content
    assert "SINTU_ADMIN_PASSWORD=CHANGE-THIS" not in content
    assert "SINTU_SESSION_SECRET=CHANGE-THIS" not in content
    assert "OPENAI_API_KEY=\n" in content
    assert "GEMINI_API_KEY=\n" in content
    password = next(line.split("=", 1)[1] for line in content.splitlines()
                    if line.startswith("SINTU_ADMIN_PASSWORD="))
    assert len(password) >= 24
    capsys.readouterr()
    module.main()
    assert module.ENV_FILE.read_text(encoding="utf-8") == content
    weak_env = tmp_path / "weak.env"
    weak_env.write_text("SINTU_ADMIN_USERNAME=admin\nSINTU_ADMIN_PASSWORD=short\nSINTU_SESSION_SECRET=" + "a" * 64 + "\n", encoding="utf-8")
    module.ENV_FILE = weak_env
    module.main()
    capsys.readouterr()
    upgraded = weak_env.read_text(encoding="utf-8")
    assert "SINTU_ADMIN_PASSWORD=short" not in upgraded
    assert len(next(line.split("=", 1)[1] for line in upgraded.splitlines() if line.startswith("SINTU_ADMIN_PASSWORD="))) >= 24


def test_windows_launcher_is_in_repo_and_uses_bootstrap():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "START_SINTU_WINDOWS.bat").read_text(encoding="utf-8")
    assert "scripts\\bootstrap_local.py" in launcher
    assert "requirements.txt" in launcher
    assert "uvicorn app.main:app" in launcher
    assert "sys.version_info >= (3,11)" in launcher
    gitignore = (root / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gitignore and ".venv/" in gitignore


def test_project_task_output_is_available_only_to_project_owner(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "_production_project_owner",
                        lambda request: request.headers.get("x-test-owner", "local"))
    monkeypatch.setattr(main, "generate_text", lambda prompt, workflow: {
        "provider": "test", "model": "test-model", "output": "Owner-only generated package"
    })
    created = client.post("/api/projects", json={
        "name": "Private output", "brief": "Private project brief.",
        "format_id": "youtube-shorts", "language": "Hindi", "duration_seconds": 60
    })
    project_id = created.json()["project"]["id"]
    generated = client.post(f"/api/projects/{project_id}/generate", json={"workflow": "shorts"})
    assert generated.status_code == 200
    output = client.get(f"/api/projects/{project_id}/task-output")
    assert output.status_code == 200
    assert output.json()["task"]["output"] == "Owner-only generated package"
    assert client.get(f"/api/projects/{project_id}/task-output",
                      headers={"x-test-owner": "different-user"}).status_code == 404


def test_production_projects_reject_whitespace_only_fields(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    payload = {"name": "   ", "brief": "   ", "format_id": "youtube-shorts", "language": "Hindi", "duration_seconds": 60}
    assert client.post("/api/projects", json=payload).status_code == 400
    valid = {**payload, "name": "Project", "brief": "Brief"}
    project_id = client.post("/api/projects", json=valid).json()["project"]["id"]
    assert client.put(f"/api/projects/{project_id}", json={**valid, "language": "   "}).status_code == 400


def test_complete_studio_api_worker_checker_memory_assets_versions_and_queue(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    project_response = client.post("/api/projects", json={
        "name": "Studio integration test", "brief": "Create a concise Hindi 3D character animation.",
        "format_id": "3d-animation", "language": "Hindi", "duration_seconds": 60
    })
    assert project_response.status_code == 201
    project_id = project_response.json()["project"]["id"]
    run_response = client.post("/api/studio/runs", json={"project_id": project_id, "format_id": "3d-animation"})
    assert run_response.status_code == 201
    run = run_response.json()["run"]
    assert run["tasks"][0]["status"] == "pending"
    assert any(t["specialist"] == "Rigging Setup Agent" for t in run["tasks"])
    assert any(t["checker"] == "Texturing Agent Checker" for t in run["tasks"])
    first = run["tasks"][0]
    submitted = client.post(f"/api/studio/runs/{run['id']}/tasks/{first['id']}/submit", json={"output":"Initial specialist output"})
    assert submitted.status_code == 200
    rejected = client.post(f"/api/studio/runs/{run['id']}/tasks/{first['id']}/check",
                           json={"decision":"FAIL","evidence":"Missing required details","issues":"Add scene continuity and timing."})
    assert rejected.status_code == 200
    assert rejected.json()["run"]["tasks"][0]["status"] == "needs_revision"
    revised = client.post(f"/api/studio/runs/{run['id']}/tasks/{first['id']}/revise", json={"output":"Revised specialist output"})
    assert revised.status_code == 200
    passed = client.post(f"/api/studio/runs/{run['id']}/tasks/{first['id']}/check",
                          json={"decision":"PASS","evidence":"All role criteria checked."})
    assert passed.status_code == 200
    assert passed.json()["run"]["tasks"][1]["status"] == "pending"
    memory = client.put("/api/studio/memory", json={"project_id":project_id,"key":"character_style","value":"Consistent blue jacket"})
    assert memory.status_code == 200
    assert client.get(f"/api/studio/memory/{project_id}").json()["memory"][0]["value"] == "Consistent blue jacket"
    asset = client.post("/api/studio/assets", json={"project_id":project_id,"kind":"reference","name":"Character sheet","uri":"local://character-sheet","metadata":{"version":1}})
    assert asset.status_code == 201
    assert len(client.get("/api/studio/assets", params={"project_id":project_id}).json()["assets"]) == 1
    version = client.post("/api/studio/versions", json={"project_id":project_id})
    assert version.status_code == 201
    assert version.json()["version"]["version"] == 1
    queue = client.post("/api/studio/render-queue", json={"project_id":project_id,"payload":{"profile":"portrait_full_hd"}})
    assert queue.status_code == 201
    item_id = queue.json()["item"]["id"]
    assert client.patch(f"/api/studio/render-queue/{item_id}", json={"status":"running"}).status_code == 200
    assert client.patch(f"/api/studio/render-queue/{item_id}", json={"status":"completed","result":{"video_id":"a"*32}}).status_code == 200


def test_render_queue_executes_existing_ffmpeg_renderer(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    project_response = client.post("/api/projects", json={
        "name":"Queued render test","brief":"A short test video","format_id":"youtube-shorts",
        "language":"Hindi","duration_seconds":15
    })
    project_id = project_response.json()["project"]["id"]
    monkeypatch.setattr(main, "render_video", lambda payload: {
        "video_id":"f"*32,"url":"/api/videos/"+"f"*32,"format":"MP4","duration_seconds":8
    })
    queued = client.post("/api/studio/render-queue", json={
        "project_id":project_id,"payload":{"title":"Queued render","scenes":["Scene one"]}
    })
    item_id = queued.json()["item"]["id"]
    executed = client.post(f"/api/studio/render-queue/{item_id}/execute")
    assert executed.status_code == 200
    assert executed.json()["item"]["status"] == "completed"
    assert executed.json()["render"]["video_id"] == "f"*32


def test_piper_voice_is_free_and_does_not_need_media_token(tmp_path, monkeypatch):
    import wave
    from pathlib import Path
    from app import voice_generator
    model = tmp_path / "hi_IN-model.onnx"
    model.write_bytes(b"test-model")
    output_dir = tmp_path / "audio"
    monkeypatch.setattr(voice_generator, "AUDIO_DIR", output_dir)
    monkeypatch.setenv("PIPER_EXECUTABLE", "fake-piper")
    monkeypatch.setenv("PIPER_MODEL_PATH", str(model))
    monkeypatch.setattr(voice_generator.shutil, "which", lambda name: "fake-piper")
    def fake_run(command, **kwargs):
        output = Path(command[command.index("--output_file") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output), "wb") as audio:
            audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(22050)
            audio.writeframes(b"\x00\x00" * 2205)
        return type("Result", (), {"returncode":0,"stderr":""})()
    monkeypatch.setattr(voice_generator.subprocess, "run", fake_run)
    result = voice_generator.generate_voiceover("नमस्ते सीन्टू, आज हम एक नई कहानी सुनेंगे।", "alloy")
    assert result["local"] is True
    assert result["format"] == "WAV"
    assert (output_dir / result["filename"]).is_file()


def test_blender_3d_render_api_adds_result_to_project_assets(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    project_response = client.post("/api/projects", json={
        "name":"3D scene test","brief":"Make a simple animated 3D scene",
        "format_id":"3d-animation","language":"Hindi","duration_seconds":8
    })
    project_id = project_response.json()["project"]["id"]
    monkeypatch.setattr(main, "render_scene", lambda title, objects, duration_seconds, resolution, fps: {
        "render_id":"e"*32,"video_id":"e"*32,"url":"/api/blender-renders/"+"e"*32,
        "format":"MP4 / H.264","size_bytes":1000,"duration_seconds":duration_seconds,
        "resolution":resolution,"fps":fps,"provider":"Blender (local, free)","local":True
    })
    response = client.post("/api/studio/blender/render", json={
        "project_id":project_id,"title":"Hero turntable",
        "objects":[{"shape":"sphere","name":"Hero","color":[0.2,0.5,0.8,1]}],
        "duration_seconds":5,"resolution":"1280x720","fps":24
    })
    assert response.status_code == 201
    assert response.json()["render"]["local"] is True
    assets = client.get("/api/studio/assets", params={"project_id":project_id}).json()["assets"]
    assert assets[0]["kind"] == "render"


def test_storyboard_renderer_accepts_local_piper_wav_voiceover(tmp_path, monkeypatch):
    import wave
    client = client_for_test(tmp_path, monkeypatch)
    audio_id = "a" * 32
    audio_dir = tmp_path / "generated_audio"
    audio_dir.mkdir()
    with wave.open(str(audio_dir / (audio_id + ".wav")), "wb") as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(22050)
        audio.writeframes(b"\x00\x00" * 2205)
    monkeypatch.setattr(main, "AUDIO_DIR", audio_dir)
    called = {}
    def fake_render(title, scenes, seconds_per_scene, image_paths=None, audio_path=None, **kwargs):
        called["audio_path"] = audio_path
        return {"video_id":"b"*32,"url":"/api/videos/"+"b"*32,"resolution":"720x1280","duration_seconds":4}
    monkeypatch.setattr(main, "render_storyboard", fake_render)
    response = client.post("/api/render", json={"title":"Piper WAV test","scenes":["One scene"],"audio_id":audio_id})
    assert response.status_code == 200
    assert called["audio_path"].suffix == ".wav"


def test_background_run_can_be_started_and_resumed_after_pause(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    project_response = client.post("/api/projects", json={
        "name":"Background workflow test","brief":"Test the one-click agent pipeline",
        "format_id":"youtube-shorts","language":"Hindi","duration_seconds":30
    })
    project_id = project_response.json()["project"]["id"]
    run_response = client.post("/api/studio/runs", json={"project_id":project_id,"format_id":"youtube-shorts"})
    run_id = run_response.json()["run"]["id"]
    monkeypatch.setattr(main, "_run_studio_background", lambda owner, identifier: None)
    started = client.post(f"/api/studio/runs/{run_id}/execute-all")
    assert started.status_code == 200
    assert started.json()["started"] is True
    assert started.json()["run"]["status"] == "in_progress"
    studio_engine = __import__("app.studio_engine", fromlist=["set_run_status"])
    studio_engine.set_run_status("local", run_id, "paused", "Test pause")
    resumed = client.post(f"/api/studio/runs/{run_id}/execute-all")
    assert resumed.status_code == 200
    assert resumed.json()["run"]["status"] == "in_progress"




def test_storyboard_frames_are_clean_and_include_sintu_branding(tmp_path):
    from PIL import Image
    from app import video_renderer

    frame = tmp_path / "clean-frame.png"
    video_renderer._make_frame(
        frame, "DO NOT SHOW TITLE", "DO NOT SHOW SCENE TEXT", 1, 1,
        width=360, height=640
    )
    with Image.open(frame) as image:
        assert image.size == (360, 640)
        assert image.getpixel((180, 300))[:3] == (16, 24, 39)
        assert image.getpixel((200, 590))[:3] != (16, 24, 39)

    clean_frame = tmp_path / "clean-frame-without-mark.png"
    video_renderer._make_frame(
        clean_frame, "Hidden title", "Hidden scene", 1, 1,
        width=360, height=640, include_watermark=False
    )
    with Image.open(clean_frame) as image:
        assert image.getpixel((200, 590))[:3] == (16, 24, 39)


def test_storyboard_frame_rejects_subtitle_overlay(tmp_path):
    from app import video_renderer

    with pytest.raises(ValueError, match="subtitles are disabled"):
        video_renderer._make_frame(
            tmp_path / "should-not-exist.png", "Title", "Scene", 1, 1,
            subtitle="spoken words"
        )


def test_video_voiceover_requires_at_least_95_percent_hindi(monkeypatch):
    from app import voice_generator

    assert voice_generator.hindi_letter_ratio("नमस्ते, आज हम कहानी सुनेंगे।") == 1.0
    monkeypatch.setattr(voice_generator, "voice_status", lambda: {"local_available": True})
    with pytest.raises(ValueError, match="95% Hindi"):
        voice_generator.generate_voiceover("Hello world, this is an English narration.")


def test_scene_image_prompts_are_text_free(tmp_path, monkeypatch):
    import io
    from PIL import Image
    from app import image_generator

    output = io.BytesIO()
    Image.new("RGB", (16, 16), (20, 30, 40)).save(output, format="PNG")
    captured = {}
    monkeypatch.setattr(image_generator, "IMAGE_DIR", tmp_path / "images")
    monkeypatch.setattr(image_generator, "image_workflow_status", lambda: {"available": True, "workflow_configured": True})
    def fake_generate(prompt, width, height):
        captured["prompt"] = prompt
        return output.getvalue()
    monkeypatch.setattr(image_generator, "generate_image_bytes", fake_generate)
    image_generator.generate_image("A mysterious ancient stepwell", kind="scene", aspect="portrait")
    assert "no text" in captured["prompt"].lower()
    assert "no subtitles" in captured["prompt"].lower()
    assert "SINTU AI YOUTUBE STUDIO watermark" in captured["prompt"]



def test_format_rendering_capability_api_lists_all_formats(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    response = client.get("/api/rendering/formats")
    assert response.status_code == 200
    body = response.json()
    assert body["format_count"] == 60
    assert body["generic_export_ready_count"] == 56
    assert body["specialized_pipeline_blocked_count"] == 4
    assert len(body["profiles"]) == 60


def test_format_rendering_profile_api_reports_vertical_shorts(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    response = client.get("/api/rendering/formats/youtube-shorts")
    assert response.status_code == 200
    body = response.json()
    assert body["default_resolution"] == "1080x1920"
    assert body["brand_watermark"] == "SINTU AI YOUTUBE STUDIO"
    assert body["burned_in_text"] is False


def test_format_rendering_profile_api_rejects_unknown_format(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    assert client.get("/api/rendering/formats/not-real").status_code == 404



def test_render_api_uses_selected_format_default_resolution(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    captured = {}
    def fake_render(title, scenes, seconds, **kwargs):
        captured.update(kwargs)
        return {"video_id": "b" * 32, "format": "MP4 / H.264"}
    monkeypatch.setattr(main, "render_storyboard", fake_render)
    response = client.post("/api/render", json={
        "title": "Short", "scenes": ["A visual scene"], "format_id": "youtube-shorts"
    })
    assert response.status_code == 200
    assert captured["resolution"] == "1080x1920"


def test_render_api_blocks_unimplemented_specialized_formats(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    response = client.post("/api/render", json={
        "title": "VR test", "scenes": ["A scene"], "format_id": "vr-video"
    })
    assert response.status_code == 501
    assert "VR-specific" in response.json()["detail"]


def test_production_run_render_requires_approved_matching_format(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    run_id = "a" * 32
    state = {"status": "paused", "format_id": "youtube-shorts"}
    monkeypatch.setattr(main, "get_production_run", lambda value, owner=None: state if value == run_id and owner == "local" else None)
    monkeypatch.setattr(main, "render_video", lambda payload: {
        "video_id": "b" * 32, "url": "/api/videos/" + "b" * 32,
        "format": "MP4 / H.264"
    })
    monkeypatch.setattr(main, "attach_render_result", lambda value, result, owner=None: {
        "status": "completed", "result": {"video_rendered": True}
    })
    payload = {"title": "Hindi short", "scenes": ["Opening"], "format_id": "youtube-shorts", "image_ids": ["d" * 32]}
    assert client.post(f"/api/production/runs/{run_id}/render", json=payload).status_code == 409
    state["status"] = "completed"
    no_visuals = dict(payload)
    no_visuals.pop("image_ids")
    assert client.post(f"/api/production/runs/{run_id}/render", json=no_visuals).status_code == 400
    mismatch = dict(payload, format_id="documentary")
    assert client.post(f"/api/production/runs/{run_id}/render", json=mismatch).status_code == 400
    response = client.post(f"/api/production/runs/{run_id}/render", json=payload)
    assert response.status_code == 200
    assert response.json()["render"]["video_id"] == "b" * 32
    assert response.json()["published"] is False


def test_production_run_render_rejects_unknown_run(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    response = client.post(f"/api/production/runs/{'c' * 32}/render", json={
        "title": "Hindi short", "scenes": ["Opening"], "format_id": "youtube-shorts"
    })
    assert response.status_code == 404



def test_structured_mixed_timeline_api_contract(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    images_dir = tmp_path / "generated_images"
    videos_dir = tmp_path / "generated_ai_videos"
    images_dir.mkdir()
    videos_dir.mkdir()
    image_id = "a" * 32
    video_id = "b" * 32
    (images_dir / f"{image_id}.jpg").write_bytes(b"image")
    (videos_dir / f"{video_id}.mp4").write_bytes(b"video")
    monkeypatch.setattr(main, "IMAGE_DIR", images_dir)
    monkeypatch.setattr(main, "AI_VIDEO_DIR", videos_dir)
    captured = {}
    def fake_mixed(items, title, scenes, **kwargs):
        captured["items"] = items
        return {"video_id": "c" * 32, "timeline_items": len(items), "timeline_order": [x["kind"] for x in items]}
    monkeypatch.setattr(main, "render_mixed_timeline", fake_mixed)
    response = client.post("/api/render", json={
        "title": "Structured timeline", "scenes": ["Still", "Motion"],
        "timeline_items": [
            {"kind": "image", "asset_id": image_id, "duration": 5, "transition": "fade"},
            {"kind": "video", "asset_id": video_id, "trim_start": 1.25, "trim_end": 4.5,
             "audio_volume": 0.7, "transition": "cut"}
        ]
    })
    assert response.status_code == 200
    assert [item["kind"] for item in captured["items"]] == ["image", "video"]
    assert captured["items"][0]["duration"] == 5
    assert captured["items"][1]["trim_start"] == 1.25
    assert captured["items"][1]["trim_end"] == 4.5
    assert captured["items"][1]["audio_volume"] == 0.7


def test_structured_timeline_rejects_invalid_video_trim(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    response = client.post("/api/render", json={
        "title": "Invalid structured timeline", "scenes": ["Scene"],
        "timeline_items": [{"kind": "video", "asset_id": "d" * 32,
                             "trim_start": 4, "trim_end": 2}]
    })
    assert response.status_code == 400


def test_firewall_ip_allowlist_and_origin_validation():
    from app.security import client_address_allowed, same_origin_request
    assert client_address_allowed("192.0.2.10", "192.0.2.0/24")
    assert not client_address_allowed("192.0.3.10", "192.0.2.0/24")
    assert client_address_allowed("127.0.0.1", "")
    assert not client_address_allowed("127.0.0.1", "not-a-cidr")
    assert same_origin_request("https://studio.example.com", "studio.example.com")
    assert same_origin_request("https://studio.example.com:8443", "studio.example.com:8443")
    assert not same_origin_request("https://evil.example", "studio.example.com")
    assert not same_origin_request("null", "studio.example.com")


def test_application_firewall_blocks_cross_origin_mutations(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    response = client.post(
        "/api/tasks",
        json={"prompt": "cross-site request", "workflow": "shorts"},
        headers={"Origin": "https://attacker.example"},
    )
    assert response.status_code == 403
    assert "Cross-origin" in response.json()["detail"]


def test_application_firewall_rate_limits_api_requests(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    main._FIREWALL_LIMITER.reset()
    monkeypatch.setenv("SINTU_RATE_LIMIT_PER_MINUTE", "1")
    assert client.get("/api/agents").status_code == 200
    limited = client.get("/api/agents")
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) >= 1
    assert client.get("/api/health").status_code == 200
    main._FIREWALL_LIMITER.reset()



def test_admin_login_rate_limit_is_bounded_and_resets_after_success(tmp_path, monkeypatch):
    monkeypatch.setenv("SINTU_AUTH_REQUIRED", "true")
    monkeypatch.setenv("SINTU_ADMIN_USERNAME", "owner")
    monkeypatch.setenv("SINTU_ADMIN_PASSWORD", "a-strong-test-password")
    monkeypatch.setenv("SINTU_SESSION_SECRET", "test-session-secret-that-is-at-least-32-bytes")
    monkeypatch.setenv("SINTU_COOKIE_SECURE", "false")
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setenv("SINTU_AUTH_REQUIRED", "true")

    for _ in range(10):
        response = client.post("/api/auth/login", json={"username": "owner", "password": "wrong-password"})
        assert response.status_code == 401
    locked = client.post("/api/auth/login", json={"username": "owner", "password": "a-strong-test-password"})
    assert locked.status_code == 429

    main._LOGIN_LIMITER.reset("testclient")
    login = client.post("/api/auth/login", json={"username": "owner", "password": "a-strong-test-password"})
    assert login.status_code == 200
    assert len(main._LOGIN_LIMITER._events) == 0



def test_production_run_status_is_scoped_to_authenticated_owner(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    run_id = "d" * 32
    seen = {}

    def fake_get(run_value, owner=None):
        seen["owner"] = owner
        return {"id": run_id, "status": "completed", "owner_username": owner} if owner == "local" else None

    monkeypatch.setattr(main, "get_production_run", fake_get)
    response = client.get(f"/api/production/runs/{run_id}")
    assert response.status_code == 200
    assert response.json()["owner_username"] == "local"
    assert seen["owner"] == "local"


def test_production_run_creation_assigns_request_owner(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    captured = {}

    def fake_create(format_id, topic, owner):
        captured.update(format_id=format_id, topic=topic, owner=owner)
        return {"id": "e" * 32, "status": "queued"}

    monkeypatch.setattr(main, "create_production_run", fake_create)
    monkeypatch.setattr(main, "execute_production_run", lambda run_id, owner: None)
    response = client.post("/api/production/runs", json={
        "format_id": "youtube-shorts", "topic": "भारत की रहस्यमयी जगहें"
    })
    assert response.status_code == 200
    assert captured["owner"] == "local"



def test_production_media_pipeline_uses_local_engines_and_attaches_verified_render(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    run_id = "a" * 32
    state = {"id": run_id, "status": "completed", "format_id": "youtube-shorts",
             "topic": "भारत की रहस्यमयी जगहें",
             "result": {"deliverables": {"Script Writer": "भारत की रहस्यमयी जगहों की कहानी"}}}
    monkeypatch.setattr(main, "get_production_run", lambda value, owner=None: state if value == run_id and owner == "local" else None)
    monkeypatch.setattr(main, "image_status", lambda: {"local_available": True})
    monkeypatch.setattr(main, "voice_status", lambda: {"local_available": True})
    monkeypatch.setattr(main, "generate_image", lambda prompt, kind, aspect: {
        "image_id": str(len(generated) + 1).zfill(32), "url": "/api/images/" + str(len(generated) + 1).zfill(32)
    })
    generated, aspects = [], []
    def fake_image(prompt, kind, aspect):
        generated.append(prompt)
        aspects.append(aspect)
        return {"image_id": str(len(generated)).zfill(32), "url": "/api/images/" + str(len(generated)).zfill(32)}
    monkeypatch.setattr(main, "generate_image", fake_image)
    monkeypatch.setattr(main, "generate_voiceover", lambda text: {
        "audio_id": "b" * 32, "filename": "b" * 32 + ".wav", "url": "/api/audio/" + "b" * 32
    })
    monkeypatch.setattr(main, "generate_music", lambda prompt, duration: {
        "music_id": "c" * 32, "url": "/api/music/" + "c" * 32
    })
    monkeypatch.setattr(main, "render_storyboard", lambda title, scenes, seconds, **kwargs: {
        "video_id": "d" * 32, "filename": "d" * 32 + ".mp4",
        "url": "/api/videos/" + "d" * 32, "resolution": kwargs["resolution"],
        "brand_watermark": "SINTU AI YOUTUBE STUDIO", "subtitles_burned_in": False
    })
    attached = {}
    def fake_attach(value, rendered, owner):
        attached.update(run_id=value, render=rendered, owner=owner)
        return {"status": "completed"}
    monkeypatch.setattr(main, "attach_render_result", fake_attach)
    image_dir, audio_dir, music_dir = tmp_path / "generated_images", tmp_path / "generated_audio", tmp_path / "generated_music"
    image_dir.mkdir(); audio_dir.mkdir(); music_dir.mkdir()
    for i in (1, 2): (image_dir / (str(i).zfill(32) + ".jpg")).write_bytes(b"image")
    (audio_dir / ("b" * 32 + ".wav")).write_bytes(b"audio")
    (music_dir / ("c" * 32 + ".wav")).write_bytes(b"music")
    monkeypatch.setattr(main, "IMAGE_DIR", image_dir)
    monkeypatch.setattr(main, "AUDIO_DIR", audio_dir)
    monkeypatch.setattr(main, "MUSIC_DIR", music_dir)

    response = client.post(f"/api/production/runs/{run_id}/produce-media", json={
        "scene_prompts": ["पुराने किले का सिनेमाई दृश्य", "रहस्यमयी जंगल का दृश्य"],
        "seconds_per_scene": 5, "resolution": "720x1280"
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["video_rendered"] is True and body["published"] is False
    assert len(body["generated_images"]) == 2
    assert body["render"]["brand_watermark"] == "SINTU AI YOUTUBE STUDIO"
    assert body["render"]["subtitles_burned_in"] is False
    assert attached["owner"] == "local"
    assert generated == ["पुराने किले का सिनेमाई दृश्य", "रहस्यमयी जंगल का दृश्य"]
    assert aspects == ["portrait", "portrait"]


def test_production_media_pipeline_uses_approved_storyboard_when_scene_prompts_omitted(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    run_id = "9" * 32
    state = {
        "id": run_id, "status": "completed", "format_id": "youtube-shorts",
        "topic": "भारत की रहस्यमयी जगहें",
        "result": {
            "deliverables": {
                "Script Writer": "भारत की रहस्यमयी जगहों की कहानी",
                "AI Video Generator": (
                    "SCENE PROMPTS:\n"
                    "1. प्राचीन किले का वाइड सिनेमाई दृश्य, सुबह की धुंध, धीमा कैमरा पुश-इन\n"
                    "2. घने जंगल में रहस्यमयी रास्ता, पेड़ों से छनती रोशनी, लो-एंगल कैमरा"
                ),
            }
        },
    }
    monkeypatch.setattr(main, "get_production_run", lambda value, owner=None: state if value == run_id and owner == "local" else None)
    monkeypatch.setattr(main, "image_status", lambda: {"local_available": True})
    monkeypatch.setattr(main, "voice_status", lambda: {"local_available": True})
    generated = []
    def fake_image(prompt, kind, aspect):
        generated.append(prompt)
        return {"image_id": str(len(generated)).zfill(32), "url": "/api/images/" + str(len(generated)).zfill(32)}
    monkeypatch.setattr(main, "generate_image", fake_image)
    monkeypatch.setattr(main, "generate_voiceover", lambda text: {
        "audio_id": "b" * 32, "filename": "b" * 32 + ".wav", "url": "/api/audio/" + "b" * 32
    })
    monkeypatch.setattr(main, "generate_music", lambda prompt, duration: {
        "music_id": "c" * 32, "url": "/api/music/" + "c" * 32
    })
    monkeypatch.setattr(main, "render_storyboard", lambda title, scenes, seconds, **kwargs: {
        "video_id": "d" * 32, "filename": "d" * 32 + ".mp4",
        "url": "/api/videos/" + "d" * 32, "resolution": kwargs["resolution"],
        "brand_watermark": "SINTU AI YOUTUBE STUDIO", "subtitles_burned_in": False
    })
    monkeypatch.setattr(main, "attach_render_result", lambda *args: {"status": "completed"})
    image_dir, audio_dir, music_dir = tmp_path / "images", tmp_path / "audio", tmp_path / "music"
    image_dir.mkdir(); audio_dir.mkdir(); music_dir.mkdir()
    monkeypatch.setattr(main, "IMAGE_DIR", image_dir)
    monkeypatch.setattr(main, "AUDIO_DIR", audio_dir)
    monkeypatch.setattr(main, "MUSIC_DIR", music_dir)
    for i in (1, 2):
        (image_dir / (str(i).zfill(32) + ".jpg")).write_bytes(b"image")
    (audio_dir / ("b" * 32 + ".wav")).write_bytes(b"audio")
    (music_dir / ("c" * 32 + ".wav")).write_bytes(b"music")

    response = client.post(f"/api/production/runs/{run_id}/produce-media", json={})
    assert response.status_code == 200, response.text
    assert generated == [
        "प्राचीन किले का वाइड सिनेमाई दृश्य, सुबह की धुंध, धीमा कैमरा पुश-इन",
        "घने जंगल में रहस्यमयी रास्ता, पेड़ों से छनती रोशनी, लो-एंगल कैमरा",
    ]
    assert response.json()["video_rendered"] is True
    assert response.json()["published"] is False


def test_scene_prompt_extraction_from_numbered_deliverable():
    assert main._scene_prompts_from_deliverables({
        "AI Video Generator": "SCENE PROMPTS:\n1. छोटा दृश्य prompt"
    }) == ["छोटा दृश्य prompt"]


def test_production_media_pipeline_fails_closed_when_local_media_engines_missing(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    run_id = "e" * 32
    state = {"id": run_id, "status": "completed", "format_id": "youtube-shorts",
             "result": {"deliverables": {"Script Writer": "हिंदी कहानी"}}}
    monkeypatch.setattr(main, "get_production_run", lambda value, owner=None: state if value == run_id else None)
    monkeypatch.setattr(main, "image_status", lambda: {"local_available": False})
    monkeypatch.setattr(main, "generate_image", lambda *args: pytest.fail("must not generate without local engine"))
    response = client.post(f"/api/production/runs/{run_id}/produce-media", json={
        "scene_prompts": ["एक दृश्य"]
    })
    assert response.status_code == 503
    assert "ComfyUI" in response.json()["detail"]


def test_production_media_pipeline_rejects_runs_owned_by_other_users(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "get_production_run", lambda value, owner=None: None)
    response = client.post(f"/api/production/runs/{'f' * 32}/produce-media", json={
        "scene_prompts": ["एक दृश्य"], "narration": "यह हिंदी कहानी है"
    })
    assert response.status_code == 404


def test_youtube_analytics_aggregates_official_metrics_and_separates_estimated_revenue(tmp_path, monkeypatch):
    from datetime import date, timedelta
    from fastapi import HTTPException
    from urllib.parse import urlparse, parse_qs

    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "_youtube_access_token", lambda: "test-access-token")
    monkeypatch.setattr(main, "_youtube_connection", lambda: {"channel_title": "Test Channel"})
    calls = []

    def fake_request(url, headers=None):
        query = parse_qs(urlparse(url).query)
        calls.append(query)
        dimension = query.get("dimensions", [""])[0]
        if "estimatedRevenue" in query.get("metrics", [""])[0]:
            payload = {"columnHeaders": [{"name": "estimatedRevenue"}, {"name": "estimatedAdRevenue"}],
                       "rows": [[12.5, 10.0]]}
        elif dimension == "day":
            payload = {
                "columnHeaders": [{"name": "day"}, {"name": "views"},
                                  {"name": "estimatedMinutesWatched"}, {"name": "averageViewDuration"},
                                  {"name": "subscribersGained"}, {"name": "subscribersLost"}],
                "rows": [["2026-11-01", 100, 50.0, 30, 4, 1], ["2026-11-02", 300, 180.0, 36, 8, 2]]
            }
        else:
            payload = {"columnHeaders": [{"name": "video"}, {"name": "views"}],
                       "rows": [["abc123", 250], ["xyz789", 150]]}
        return 200, {}, json.dumps(payload).encode("utf-8")

    monkeypatch.setattr(main, "_youtube_request", fake_request)
    response = client.get("/api/admin/youtube/analytics?start_date=2026-11-01&end_date=2026-11-30")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["channel"] == "Test Channel"
    assert body["totals"]["views"] == 400
    assert body["totals"]["estimatedMinutesWatched"] == 230
    assert body["totals"]["subscribersGained"] == 12
    assert body["totals"]["subscribersLost"] == 3
    assert body["totals"]["averageViewDuration"] == 34.5
    assert body["top_videos"][0]["url"] == "https://www.youtube.com/watch?v=abc123"
    assert body["revenue"]["available"] is True
    assert body["revenue"]["estimated_revenue"] == 12.5
    assert len(calls) == 3
    assert all(call["ids"] == ["channel==MINE"] for call in calls)
    assert response.json()["revenue"]["currency"] == "INR"


def test_youtube_analytics_rejects_invalid_ranges_before_oauth_and_handles_revenue_permission_error(tmp_path, monkeypatch):
    from fastapi import HTTPException

    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "_youtube_access_token", lambda: pytest.fail("invalid dates must be rejected before OAuth"))
    assert client.get("/api/admin/youtube/analytics?start_date=not-a-date").status_code == 422
    assert client.get("/api/admin/youtube/analytics?start_date=2026-11-10&end_date=2026-11-01").status_code == 422
    assert client.get("/api/admin/youtube/analytics?start_date=2025-01-01&end_date=2026-11-01").status_code == 422

    monkeypatch.setattr(main, "_youtube_access_token", lambda: "test-access-token")
    monkeypatch.setattr(main, "_youtube_connection", lambda: {"channel_title": "Test Channel"})
    calls = {"count": 0}

    def fake_request(url, headers=None):
        calls["count"] += 1
        if calls["count"] == 3:
            raise HTTPException(status_code=403, detail="monetary scope unavailable")
        from urllib.parse import urlparse, parse_qs
        dimension = parse_qs(urlparse(url).query).get("dimensions", [""])[0]
        if dimension == "day":
            payload = {"columnHeaders": [{"name": "day"}, {"name": "views"},
                       {"name": "estimatedMinutesWatched"}, {"name": "averageViewDuration"},
                       {"name": "subscribersGained"}, {"name": "subscribersLost"}], "rows": []}
        else:
            payload = {"columnHeaders": [{"name": "video"}, {"name": "views"}], "rows": []}
        return 200, {}, json.dumps(payload).encode("utf-8")

    monkeypatch.setattr(main, "_youtube_request", fake_request)
    response = client.get("/api/admin/youtube/analytics?start_date=2026-11-01&end_date=2026-11-02")
    assert response.status_code == 200, response.text
    assert response.json()["revenue"]["available"] is False
    assert "Revenue abhi available nahi" in response.json()["revenue"]["note"]
    assert response.json()["totals"]["views"] == 0
