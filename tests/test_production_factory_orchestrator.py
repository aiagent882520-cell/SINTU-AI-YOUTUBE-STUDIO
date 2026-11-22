from __future__ import annotations

import pytest

from app.production_factory_orchestrator import build_pipeline_plan, validate_execution_policy


def test_pipeline_plan_is_complete_and_does_not_start_execution():
    plan = build_pipeline_plan("Hindi science explainer", "educational")
    stage_ids = [stage["id"] for stage in plan["stages"]]
    assert stage_ids == [
        "intake", "planning", "research", "fact_check", "strategy", "script",
        "storyboard", "character_bible", "visual_development", "generation",
        "audio", "editing", "localization", "branding", "quality",
        "owner_review", "render", "package", "publishing",
        "analytics_earnings", "learning",
    ]
    assert plan["pipeline_stage_count"] == 21
    assert plan["pipeline_version"] == "2.0"
    assert plan["execution_started"] is False
    assert plan["execution_allowed"] is False
    assert plan["stage_execution_implemented"] is False
    assert "planning-only" in plan["stage_execution_note"]
    assert plan["publishing_enabled"] is False
    assert plan["free_first"] is True
    assert next(stage for stage in plan["stages"] if stage["id"] == "owner_review")["approval"] == "owner_required"
    assert next(stage for stage in plan["stages"] if stage["id"] == "publishing")["auto_execute"] is False
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

def test_existing_specialist_roles_route_to_pipeline_stages_without_false_completion():
    from app.production_factory_orchestrator import route_specialist_roles

    routed = route_specialist_roles([
        "Master AI", "Web Research", "Fact Checker", "Script Writer",
        "Filmmaking Director", "AI Video Generator", "Voice Generator",
        "Video Editor", "Subtitle Creator", "Thumbnail Designer",
        "Unmapped Experimental Agent",
    ])
    stages = {row["stage_id"]: row for row in routed["stages"]}
    assert stages["intake"]["roles"] == ["Master AI"]
    assert stages["research"]["roles"] == ["Web Research"]
    assert stages["fact_check"]["roles"] == ["Fact Checker"]
    assert stages["script"]["roles"] == ["Script Writer"]
    assert stages["storyboard"]["roles"] == ["Filmmaking Director"]
    assert stages["generation"]["roles"] == ["AI Video Generator"]
    assert stages["audio"]["roles"] == ["Voice Generator"]
    assert stages["editing"]["roles"] == ["Video Editor"]
    assert stages["localization"]["roles"] == ["Subtitle Creator"]
    assert stages["branding"]["roles"] == ["Thumbnail Designer"]
    assert stages["render"]["status"] == "not_applicable"
    assert routed["unmapped_roles"] == ["Unmapped Experimental Agent"]

