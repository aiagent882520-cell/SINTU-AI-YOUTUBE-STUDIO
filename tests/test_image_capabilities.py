import os

from fastapi.testclient import TestClient

from app import main


def test_image_capabilities_reports_production_safety_gate(monkeypatch):
    monkeypatch.setenv("SINTU_AUTH_REQUIRED", "false")
    monkeypatch.setenv("SINTU_PRODUCTION_ENABLED", "false")
    response = TestClient(main.app).get("/api/images/capabilities")
    assert response.status_code == 200
    assert response.json()["production_enabled"] is False


def test_image_generation_post_is_blocked_when_production_is_paused(monkeypatch):
    monkeypatch.setenv("SINTU_AUTH_REQUIRED", "false")
    monkeypatch.setenv("SINTU_PRODUCTION_ENABLED", "false")
    monkeypatch.setattr(
        main,
        "generate_image",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("generation must not run")),
    )
    response = TestClient(main.app).post(
        "/api/images",
        json={"prompt": "A fort at sunrise", "kind": "scene", "aspect": "portrait"},
    )
    assert response.status_code == 503
    assert "production is paused" in response.json()["detail"].lower()


def test_android_image_api_returns_validated_procedural_jpeg(tmp_path, monkeypatch):
    from io import BytesIO
    from PIL import Image
    from app import image_generator

    monkeypatch.setenv("SINTU_AUTH_REQUIRED", "false")
    monkeypatch.setenv("SINTU_PRODUCTION_ENABLED", "true")
    monkeypatch.setattr(image_generator, "IMAGE_DIR", tmp_path)
    monkeypatch.setattr(
        image_generator,
        "image_workflow_status",
        lambda: {
            "available": False, "workflow_configured": False,
            "server_reachable": False, "workflow_valid": False,
            "nodes_verified": False, "missing_nodes": [],
            "missing_models": [], "reason": "ComfyUI not configured",
        },
    )

    def procedural_jpeg(prompt, width, height):
        buffer = BytesIO()
        Image.new("RGB", (width, height), (32, 64, 96)).save(buffer, format="JPEG")
        return buffer.getvalue()

    monkeypatch.setattr(image_generator, "generate_procedural_scene_bytes", procedural_jpeg)
    client = TestClient(main.app)
    response = client.post(
        "/api/images",
        json={"prompt": "A sunrise over an Indian fort", "kind": "scene", "aspect": "portrait"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "SINTU Procedural Art (offline)"
    assert data["format"] == "JPEG"
    assert data["width"] == 768 and data["height"] == 1360
    assert "not a generative-AI image" in data["notice"]
    image_response = client.get(data["url"])
    assert image_response.status_code == 200
    assert image_response.headers["content-type"] == "image/jpeg"
    assert image_response.content[:3] == b"\\xff\\xd8\\xff"
