from __future__ import annotations

import pytest

from app.production_factory_orchestrator import build_pipeline_plan, validate_execution_policy


def test_pipeline_plan_is_complete_and_does_not_start_execution():
    plan = build_pipeline_plan("Hindi science explainer", "educational")
    stage_ids = [stage["id"] for stage in plan["stages"]]
    assert stage_ids == [
        "intake", "research", "strategy", "writing", "visuals", "audio",
        "assembly", "quality", "owner_review", "publishing", "analytics",
    ]
    assert plan["execution_started"] is False
    assert plan["execution_allowed"] is False
    assert plan["publishing_enabled"] is False
    assert plan["free_first"] is True
    assert plan["paid_auto_activation"] is False


def test_catalogue_presence_never_claims_live_health():
    plan = build_pipeline_plan("topic", "shorts")
    for stage in plan["stages"]:
        assert stage["readiness"] in {
            "owner_approval_required",
            "runtime_health_check_required",
            "installation_or_credentials_required",
            "provider_unavailable",
            "ready_without_external_provider",
        }
    assert "do not prove installation" in plan["notice"]


def test_custom_provider_candidates_are_capability_matched():
    providers = [
        {"id": "local_writer", "name": "Local Writer", "status": "integrated",
         "pricing": "free_local", "capabilities": ["text", "script"]},
        {"id": "paid_video", "name": "Paid Video", "status": "external_optional",
         "pricing": "paid_optional", "capabilities": ["video"]},
    ]
    plan = build_pipeline_plan("topic", "format", providers=providers)
    writing = next(stage for stage in plan["stages"] if stage["id"] == "writing")
    assembly = next(stage for stage in plan["stages"] if stage["id"] == "assembly")
    assert any(item["id"] == "local_writer" for item in writing["provider_candidates"])
    assert any(item["id"] == "paid_video" for item in assembly["provider_candidates"])
    assert next(item for item in assembly["provider_candidates"] if item["id"] == "paid_video")["selection"] == "verify_before_use"


@pytest.mark.parametrize("action", ["publish", "upload", "schedule", "share_externally", "delete_source"])
def test_external_side_effects_require_owner_approval(action):
    with pytest.raises(PermissionError):
        validate_execution_policy(action=action)
    validate_execution_policy(action=action, owner_approved=True)


def test_paid_provider_requires_policy_and_owner_approval(monkeypatch):
    from app import production_factory_orchestrator as factory

    monkeypatch.setattr(factory, "_paid_upgrades_allowed", lambda: False)
    with pytest.raises(PermissionError):
        validate_execution_policy(action="generate", paid_provider=True, owner_approved=True)
    monkeypatch.setattr(factory, "_paid_upgrades_allowed", lambda: True)
    with pytest.raises(PermissionError):
        validate_execution_policy(action="generate", paid_provider=True)
    validate_execution_policy(action="generate", paid_provider=True, owner_approved=True)


def test_input_limits_are_enforced():
    with pytest.raises(ValueError):
        build_pipeline_plan("", "shorts")
    with pytest.raises(ValueError):
        build_pipeline_plan("topic", "")
