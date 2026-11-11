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



def test_runtime_executes_worker_and_checker_as_separate_calls(tmp_path, monkeypatch):
    import app.production_runtime as runtime

    monkeypatch.setattr(runtime, "DB_PATH", tmp_path / "runtime.sqlite3")
    calls = []
    def fake_generate(prompt, workflow, provider):
        calls.append((prompt, workflow, provider))
        is_gate = "independent quality checker" in prompt.lower() or "final video production reviewer" in prompt.lower()
        output = ('{"decision":"PASS","evidence":["reviewed against acceptance criteria"],'
                  '"issues":[],"revision_instructions":[]}') if is_gate else "Hindi production deliverable"
        return {"output": output, "provider": "test", "model": "fixture"}
    monkeypatch.setattr(runtime, "generate_text", fake_generate)

    run = runtime.create_run("youtube-shorts", "भारत की रहस्यमयी जगहें")
    runtime.execute_run(run["id"])
    result = runtime.get_run(run["id"])

    assert result["status"] == "completed"
    assert result["result"]["video_rendered"] is False
    assert result["result"]["published"] is False
    assert len(result["result"]["reviewer_reports"]) == 5
    assert len(calls) == 2 * len([x for x in result["steps"] if x["step_type"] == "builder"]) + 5
    assert all(step["status"] in {"completed", "pass"} for step in result["steps"])


def test_runtime_stops_after_first_checker_failure(tmp_path, monkeypatch):
    import app.production_runtime as runtime

    monkeypatch.setattr(runtime, "DB_PATH", tmp_path / "runtime.sqlite3")
    calls = []
    def fake_generate(prompt, workflow, provider):
        calls.append(prompt)
        if "independent quality checker" in prompt.lower():
            return {"output": '{"decision":"FAIL","evidence":[],"issues":["missing source"],'
                              '"revision_instructions":["add source"]}', "provider": "test", "model": "fixture"}
        return {"output": "Draft output", "provider": "test", "model": "fixture"}
    monkeypatch.setattr(runtime, "generate_text", fake_generate)

    run = runtime.create_run("youtube-shorts", "भारत की रहस्यमयी जगहें")
    runtime.execute_run(run["id"])
    result = runtime.get_run(run["id"])

    assert result["status"] == "paused"
    assert result["current_role"].endswith("Checker")
    assert len(calls) == 2
    assert result["steps"][-1]["status"] == "fail"
