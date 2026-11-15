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


def test_every_format_preset_routes_every_selected_role_to_a_stage():
    from app.studio_scope import video_formats
    for item in video_formats():
        plan = production_plan(item["id"])
        routed = {pair["worker"] for stage in plan["pipeline"] for pair in stage["worker_checker_pairs"]}
        assert set(item["roles"]).issubset(routed), item["id"]


def test_management_hierarchy_has_five_senior_agents_and_external_chatgpt_supervisor():
    registry = agent_registry()
    hierarchy = registry["management_hierarchy"]
    assert registry["senior_manager_total"] == 5
    assert hierarchy["top_supervisor"]["name"] == "ChatGPT Supervisor"
    assert hierarchy["top_supervisor"]["local_execution"] is False
    assert [item["name"] for item in hierarchy["senior_managers"]] == [
        "HR Agent", "Manager Agent", "GM Agent", "HO Agent", "Owner Agent"
    ]


def test_every_named_video_feature_has_its_own_checker_pair():
    from app.management_hierarchy import FEATURE_CHECKER_PAIRS
    registry = agent_registry()
    available = {pair["specialist"]: pair["checker"] for pair in registry["checker_pairs"]}
    for item in FEATURE_CHECKER_PAIRS:
        assert item["agent"] in available
        assert item["checker"] == available[item["agent"]]
    assert registry["feature_checker_count"] == len(FEATURE_CHECKER_PAIRS)



def test_requested_video_categories_and_every_named_format_are_preserved():
    from app.studio_scope import video_formats
    formats = {item["id"]: item for item in video_formats()}
    required = {
        "Films": ["cinematic-movie", "short-film", "fantasy-film", "sci-fi-film",
                  "action-film", "romantic-film", "horror-film", "historical-film"],
        "Stop Motion": ["stop-motion", "clay-animation", "puppet-animation"],
        "Music": ["lyric-video", "music-video"],
        "Visual Effects": ["visual-effects-video", "green-screen"],
        "Business": ["product-demonstration", "advertisement", "training-corporate"],
        "Live": ["live-action", "event-video", "sports-highlights", "news-reportage"],
        "Special": ["360-video", "vr-video", "ar-video", "virtual-production",
                    "ai-avatar", "talking-photo"],
        "Hybrid": ["hybrid-2d-3d", "timelapse-hyperlapse"],
    }
    assert len(formats) == 60
    for group, ids in required.items():
        for format_id in ids:
            assert format_id in formats, format_id
            assert formats[format_id]["group"] == group
            assert formats[format_id]["category"] == group


def test_exactly_twenty_one_feature_worker_checker_lanes_are_registered():
    from app.management_hierarchy import FEATURE_CHECKER_PAIRS
    registry = agent_registry()
    assert len(FEATURE_CHECKER_PAIRS) == 21
    assert registry["feature_checker_count"] == 21
    assert registry["core_agent_total"] == 61
    assert registry["feature_worker_checker_total"] == 21


def test_new_format_specific_specialists_have_worker_checker_stage_routes():
    from app.studio_scope import production_plan
    for format_id, role in [
        ("3d-animation", "3D Animator"),
        ("stop-motion", "Stop Motion Animator"),
        ("green-screen", "Green Screen Compositor"),
        ("music-video", "Music Video Director"),
        ("product-demonstration", "Product Demo Agent"),
    ]:
        plan = production_plan(format_id)
        pairs = [pair for stage in plan["pipeline"] for pair in stage["worker_checker_pairs"]]
        assert any(pair["worker"] == role and pair["checker"] == role + " Checker" for pair in pairs)
