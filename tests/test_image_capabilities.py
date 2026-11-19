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
