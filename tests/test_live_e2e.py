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
    from app.agents import AGENTS
    from app.production_runtime import REVIEWERS

    steps = []
    for role in AGENTS:
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
    assert result["registered_agent_roles"] == 61
    assert result["completed_workers"] == 61
    assert result["passed_checkers"] == 61
    assert result["final_reviewers"] == 5
    assert result["worker_role_coverage"] == 61
    assert result["checker_role_coverage"] == 61
    assert result["reviewer_role_coverage"] == 5


def test_live_agent_catalog_rejects_incomplete_role_coverage(monkeypatch):
    from app.agents import AGENTS

    steps = []
    for role in AGENTS[:-1]:
        steps.append({"step_type": "builder", "role": role, "status": "completed"})
        steps.append({"step_type": "checker", "role": role + " Checker", "status": "pass"})
    monkeypatch.setattr(live_e2e, "create_run", lambda *args: {"id": "incomplete-run"})
    monkeypatch.setattr(live_e2e, "execute_run", lambda *args: None)
    monkeypatch.setattr(live_e2e, "get_run", lambda *args: {
        "status": "completed", "steps": steps, "error": None
    })

    with pytest.raises(RuntimeError, match="exact catalog coverage"):
        live_e2e._live_agent_catalog("Incomplete role coverage test")

