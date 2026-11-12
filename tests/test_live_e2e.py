import json

import pytest

from scripts import live_e2e


def test_preflight_never_returns_oauth_secret_values(monkeypatch):
    monkeypatch.setenv("YOUTUBE_CLIENT_ID", "private-client-id")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET", "private-client-secret")
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
    assert '"credentials_configured": true' in report


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
