from app.production_runtime import _checker_payload
from app.studio_scope import video_formats


def test_all_sixty_video_formats_have_independent_worker_checker_pairs():
    formats = video_formats()
    assert len(formats) == 60
    for item in formats:
        assert item["roles"]
        assert len(item["checker_roles"]) == len(item["roles"])
        assert all(name.endswith(" Checker") for name in item["checker_roles"])


def test_checker_rejects_invalid_json_instead_of_auto_approving():
    result = _checker_payload("Looks good, approved.")
    assert result["decision"] == "FAIL"
    assert result["issues"]


def test_checker_accepts_explicit_pass_with_evidence():
    result = _checker_payload('{"decision":"PASS","evidence":["scene plan complete"],"issues":[]}')
    assert result["decision"] == "PASS"
    assert result["evidence"] == ["scene plan complete"]
