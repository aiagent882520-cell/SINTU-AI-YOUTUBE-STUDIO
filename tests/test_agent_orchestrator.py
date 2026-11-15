from app.agent_orchestrator import format_team
from app.management_hierarchy import SENIOR_MANAGER_NAMES


def test_every_format_team_includes_five_senior_managers_with_separate_checkers():
    team = format_team("youtube-shorts")
    workers = {item["name"] for item in team if item["role_type"] == "specialist"}
    checkers = {item["name"] for item in team if item["role_type"] == "independent_checker"}
    for manager in SENIOR_MANAGER_NAMES:
        assert manager in workers
        assert manager + " Checker" in checkers


def test_selected_video_team_includes_feature_and_senior_roles():
    team = format_team("youtube-shorts")
    workers = {item["name"] for item in team if item["role_type"] == "specialist"}
    checkers = {item["name"] for item in team if item["role_type"] == "independent_checker"}
    assert "Hindi Narration Agent" in workers
    assert "Sound Effects Agent" in workers
    assert "Branding Agent" in workers
    for manager in SENIOR_MANAGER_NAMES:
        assert manager in workers
        assert manager + " Checker" in checkers
