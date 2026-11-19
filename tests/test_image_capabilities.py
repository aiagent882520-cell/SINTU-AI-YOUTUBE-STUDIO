import os

from fastapi.testclient import TestClient

from app import main


def test_image_capabilities_reports_production_safety_gate(monkeypatch):
    monkeypatch.setenv("SINTU_AUTH_REQUIRED", "false")
    monkeypatch.setenv("SINTU_PRODUCTION_ENABLED", "false")
    response = TestClient(main.app).get("/api/images/capabilities")
    assert response.status_code == 200
    assert response.json()["production_enabled"] is False
