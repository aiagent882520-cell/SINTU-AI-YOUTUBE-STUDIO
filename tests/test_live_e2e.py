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


def test_scene_prompt_parser_requires_six_to_twelve_numbered_prompts():
    from scripts.live_e2e import _extract_scene_prompts

    prompt_text = "Approved visual plan\nSCENE PROMPTS:\n" + "\n".join(
        f"{index}. Text-free cinematic scene {index}" for index in range(1, 7)
    )
    prompts = _extract_scene_prompts(prompt_text)
    assert len(prompts) == 6
    assert prompts[0] == "Text-free cinematic scene 1"
    with pytest.raises(RuntimeError, match="6 to 12"):
        _extract_scene_prompts("SCENE PROMPTS:\n1. Only one scene")
    with pytest.raises(RuntimeError, match="no SCENE PROMPTS"):
        _extract_scene_prompts("No approved scene section")


def test_full_studio_e2e_uses_approved_scene_and_attaches_branded_render(monkeypatch):
    scene_section = "SCENE PROMPTS:\n" + "\n".join(
        f"{index}. Approved cinematic scene {index}" for index in range(1, 7)
    )
    package = {
        "id": "full-e2e-run",
        "result": {"deliverables": {"AI Video Generator": scene_section}},
    }
    monkeypatch.setattr(live_e2e, "_live_agent_catalog", lambda topic, include_result=False: (
        {"status": "completed", "registered_agent_roles": 61}, package
    ))
    generated = []
    monkeypatch.setattr(live_e2e, "_live_video", lambda prompt: (
        generated.append(prompt) or {
            "final_render_id": "render-id",
            "render_result": {"video_id": "render-id", "brand_watermark": "SINTU AI YOUTUBE STUDIO"},
            "final_render_path": "/tmp/render.mp4",
        }
    ))
    monkeypatch.setattr(live_e2e, "attach_render_result", lambda *args: {
        "result": {"video_rendered": True, "published": False}
    })

    result = live_e2e._full_studio_e2e("Test topic")
    assert generated == [[f"Approved cinematic scene {index}" for index in range(1, 7)]]
    assert result["approved_scene_prompts"] == 6
    assert result["render_attached_to_production_run"] is True
    assert result["published"] is False


def test_full_studio_e2e_does_not_attach_if_render_is_not_approved(monkeypatch):
    package = {"id": "blocked-run", "result": {"deliverables": {
        "AI Video Generator": "SCENE PROMPTS:\n" + "\n".join(
            f"{index}. Scene {index}" for index in range(1, 7)
        )
    }}}
    monkeypatch.setattr(live_e2e, "_live_agent_catalog", lambda *args, **kwargs: ({}, package))
    monkeypatch.setattr(live_e2e, "_live_video", lambda prompt: {"render_result": {}})
    monkeypatch.setattr(live_e2e, "attach_render_result", lambda *args: {
        "result": {"video_rendered": False, "published": False}
    })
    with pytest.raises(RuntimeError, match="could not be attached"):
        live_e2e._full_studio_e2e("Test topic")
