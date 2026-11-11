from app.studio_scope import video_formats, agent_registry, production_plan, scope_summary

def test_all_sixty_approved_video_formats_are_present():
    formats = video_formats()
    assert len(formats) == 60
    assert len({item["id"] for item in formats}) == 60
    assert formats[0]["id"] == "youtube-shorts"
    assert any(item["id"] == "documentary" for item in formats)
    assert any(item["id"] == "3d-animation" for item in formats)

def test_every_specialist_has_a_distinct_independent_checker():
    registry = agent_registry()
    pairs = registry["checker_pairs"]
    assert registry["specialist_total"] == registry["checker_total"]
    assert all(pair["independent"] for pair in pairs)
    assert all(pair["specialist"] != pair["checker"] for pair in pairs)
    assert len({pair["checker"] for pair in pairs}) == len(pairs)
    assert any(pair["specialist"] == "Texturing Agent" for pair in pairs)
    assert any(pair["specialist"] == "Text Training Agent" for pair in pairs)

def test_format_plan_only_uses_relevant_roles_and_checker_gates():
    plan = production_plan("3d-animation")
    roles = {pair["worker"] for stage in plan["pipeline"] for pair in stage["worker_checker_pairs"]}
    assert "Modeling Agent" in roles
    assert "Rigging Setup Agent" in roles
    assert "Texturing Agent" in roles
    assert all(pair["checker"] != pair["worker"] for stage in plan["pipeline"] for pair in stage["worker_checker_pairs"])
    assert plan["approval_required_before_publish"] is True
    assert plan["paid_services_enabled"] is False

def test_free_first_upgrade_policy():
    policy = scope_summary()["free_first_policy"]
    assert policy["budget_target_inr"] == 0
    assert policy["required_paid_services"] is False
    assert policy["paid_upgrades_allowed_before_revenue"] is False
    assert policy["paid_upgrades_require_user_approval"] is True
