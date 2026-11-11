from app.production_runtime import _checker_payload, _review_payload
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



def test_final_reviewer_rejects_ambiguous_free_text():
    result = _review_payload("Everything looks excellent, ship it!")
    assert result["decision"] == "FAIL"
    assert "Reviewer did not return valid PASS/FAIL JSON." in result["issues"]


def test_final_reviewer_requires_explicit_pass_evidence():
    result = _review_payload('{"decision":"PASS","evidence":["audio peak checked"],"issues":[]}')
    assert result["decision"] == "PASS"
    assert result["evidence"] == ["audio peak checked"]


def test_final_reviewer_preserves_fail_issues():
    result = _review_payload('{"decision":"FAIL","evidence":[],"issues":["copyright source missing"]}')
    assert result["decision"] == "FAIL"
    assert result["issues"] == ["copyright source missing"]



def test_checker_rejects_pass_without_evidence():
    result = _checker_payload('{"decision":"PASS","evidence":[],"issues":[]}')
    assert result["decision"] == "FAIL"
    assert "non-empty evidence" in result["issues"][0]


def test_checker_rejects_pass_with_unresolved_issues():
    result = _checker_payload('{"decision":"PASS","evidence":["script reviewed"],"issues":["copyright unclear"]}')
    assert result["decision"] == "FAIL"
    assert "non-empty evidence" in result["issues"][0]


def test_checker_rejects_non_string_evidence():
    result = _checker_payload('{"decision":"PASS","evidence":[true],"issues":[]}')
    assert result["decision"] == "FAIL"


def test_final_reviewer_rejects_pass_without_evidence():
    result = _review_payload('{"decision":"PASS","evidence":[],"issues":[]}')
    assert result["decision"] == "FAIL"
