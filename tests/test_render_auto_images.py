from app import main


def _client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("SINTU_AUTH_REQUIRED", "false")
    monkeypatch.setenv("SINTU_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "sintu-test.sqlite3")
    main._LOGIN_LIMITER.reset()
    main._FIREWALL_LIMITER.reset()
    main.init_db()
    return TestClient(main.app)


def test_render_api_can_generate_scene_images_automatically(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    image_dir = tmp_path / "generated_images"
    image_dir.mkdir()
    monkeypatch.setattr(main, "IMAGE_DIR", image_dir)
    generated = []

    def fake_generate_image(prompt, kind, aspect):
        image_id = f"{len(generated) + 1:032x}"
        (image_dir / f"{image_id}.jpg").write_bytes(b"test-image")
        item = {"image_id": image_id, "provider": "SINTU Procedural Art (offline)",
                "url": f"/api/images/{image_id}", "aspect": aspect}
        generated.append((prompt, kind, aspect, item))
        return item

    captured = {}
    def fake_render(title, scenes, seconds_per_scene, **kwargs):
        captured.update(kwargs)
        return {"video_id": "a" * 32, "scenes": len(scenes), "scene_images": len(kwargs["image_paths"])}

    monkeypatch.setattr(main, "generate_image", fake_generate_image)
    monkeypatch.setattr(main, "render_storyboard", fake_render)

    response = client.post("/api/render", json={
        "title": "Automatic visual test",
        "scenes": ["Ancient fort at night", "Moonlit forest"],
        "seconds_per_scene": 2,
        "auto_generate_images": True,
        "resolution": "720x1280",
        "fps": 24,
        "quality": "standard",
        "transition": "cut",
    })

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(generated) == 2
    assert all(item[1] == "scene" and item[2] == "portrait" for item in generated)
    assert len(captured["image_paths"]) == 2
    assert body["scene_images_generated"] == 2
    assert [item["provider"] for item in body["scene_images"]] == [
        "SINTU Procedural Art (offline)", "SINTU Procedural Art (offline)"
    ]


def test_render_api_keeps_manual_image_mode_as_default(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    captured = {}
    monkeypatch.setattr(main, "render_storyboard", lambda title, scenes, seconds_per_scene, **kwargs: (
        captured.update(kwargs) or {"video_id": "b" * 32, "scenes": len(scenes)}
    ))
    monkeypatch.setattr(main, "generate_image", lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("Image generation must stay opt-in for backwards compatibility.")
    ))
    response = client.post("/api/render", json={
        "title": "Legacy render test",
        "scenes": ["Plain scene"],
        "seconds_per_scene": 2,
        "resolution": "720x1280",
        "fps": 24,
        "quality": "standard",
        "transition": "cut",
    })
    assert response.status_code == 200, response.text
    assert captured["image_paths"] == []
    assert "scene_images_generated" not in response.json()
