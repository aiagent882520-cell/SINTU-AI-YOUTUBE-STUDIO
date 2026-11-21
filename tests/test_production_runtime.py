import pytest

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
    assert "Reviewer did not return valid PASS/FAIL JSON with evidence." in result["issues"]


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
        if is_gate:
            output = ('{"decision":"PASS","evidence":["reviewed against acceptance criteria"],'
                      '"issues":[],"revision_instructions":[]}')
        elif "you are the sintu owner agent" in prompt.lower():
            output = "READY: all feature and final reviewer gates passed; waiting for human owner approval."
        else:
            output = "Hindi production deliverable"
        return {"output": output, "provider": "test", "model": "fixture"}
    monkeypatch.setattr(runtime, "generate_text", fake_generate)

    run = runtime.create_run("youtube-shorts", "भारत की रहस्यमयी जगहें")
    runtime.execute_run(run["id"])
    result = runtime.get_run(run["id"])

    assert result["status"] == "completed"
    assert result["result"]["video_rendered"] is False
    assert result["result"]["published"] is False
    assert len(result["result"]["reviewer_reports"]) == 5
    assert set(result["result"]["management_reports"]) == {"HR Agent", "Manager Agent", "GM Agent", "HO Agent", "Owner Agent"}
    assert len(result["result"]["management_hierarchy"]["senior_managers"]) == 5
    assert result["result"]["management_hierarchy"]["top_supervisor"]["local_execution"] is False
    assert result["steps"][-2]["role"] == "Owner Agent"
    assert result["steps"][-1]["role"] == "Owner Agent Checker"
    final_review_positions = [i for i, step in enumerate(result["steps"]) if step["step_type"] == "reviewer"]
    assert final_review_positions and final_review_positions[-1] < len(result["steps"]) - 2
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
    assert len(calls) == 6
    assert [step["step_type"] for step in result["steps"]] == ["builder", "checker"] * 3
    assert result["steps"][-1]["status"] == "fail"
    assert result["steps"][-1]["attempts"] == 3


def test_render_result_attaches_only_to_completed_run(tmp_path, monkeypatch):
    import app.production_runtime as runtime

    monkeypatch.setattr(runtime, "DB_PATH", tmp_path / "runtime.sqlite3")
    run = runtime.create_run("youtube-shorts", "Hindi topic")
    runtime._set_run(run["id"], "completed", result={
        "deliverables": {"Script Writer": "Narration"},
        "video_rendered": False, "published": False
    })
    attached = runtime.attach_render_result(run["id"], {
        "video_id": "a" * 32, "url": "/api/videos/" + "a" * 32,
        "format": "MP4 / H.264"
    })
    assert attached["status"] == "completed"
    assert attached["result"]["video_rendered"] is True
    assert attached["result"]["render"]["video_id"] == "a" * 32
    assert attached["result"]["published"] is False


def test_render_result_cannot_attach_to_unapproved_run(tmp_path, monkeypatch):
    import app.production_runtime as runtime

    monkeypatch.setattr(runtime, "DB_PATH", tmp_path / "runtime.sqlite3")
    run = runtime.create_run("youtube-shorts", "Hindi topic")
    with pytest.raises(ValueError, match="completed"):
        runtime.attach_render_result(run["id"], {"video_id": "a" * 32})


def test_runtime_revises_once_then_continues_after_checker_pass(tmp_path, monkeypatch):
    import app.production_runtime as runtime

    monkeypatch.setattr(runtime, "DB_PATH", tmp_path / "runtime.sqlite3")
    monkeypatch.setattr(runtime, "format_team", lambda _format: [
        {"role_type": "specialist", "name": "Script Writer", "mission": "write the Hindi narration"}
    ])
    calls = []

    def fake_generate(prompt, workflow, provider):
        calls.append(prompt)
        if "independent quality checker" in prompt.lower():
            if "Revision attempt: 1" in prompt:
                output = '{"decision":"FAIL","evidence":[],"issues":["hook is weak"],"revision_instructions":["write a stronger opening hook"]}'
            else:
                output = '{"decision":"PASS","evidence":["stronger hook verified"],"issues":[],"revision_instructions":[]}'
        elif "final video production reviewer" in prompt.lower():
            output = '{"decision":"PASS","evidence":["review criteria checked"],"issues":[],"revision_instructions":[]}'
        else:
            output = "Revised Hindi narration with a stronger opening hook" if "REVISION REQUIRED" in prompt else "Initial Hindi narration"
        return {"output": output, "provider": "test", "model": "fixture"}

    monkeypatch.setattr(runtime, "generate_text", fake_generate)
    run = runtime.create_run("youtube-shorts", "भारत की रहस्यमयी जगहें")
    runtime.execute_run(run["id"])
    result = runtime.get_run(run["id"])

    assert result["status"] == "completed"
    assert result["result"]["deliverables"]["Script Writer"].startswith("Revised")
    assert [step["step_type"] for step in result["steps"][:4]] == ["builder", "checker", "builder", "checker"]
    assert result["steps"][0]["attempts"] == 1
    assert result["steps"][2]["attempts"] == 2
    assert len([step for step in result["steps"] if step["step_type"] == "reviewer"]) == 5



def test_production_runs_are_isolated_by_owner(tmp_path, monkeypatch):
    import app.production_runtime as runtime

    monkeypatch.setattr(runtime, "DB_PATH", tmp_path / "runtime.sqlite3")
    alice = runtime.create_run("youtube-shorts", "Alice topic", "alice")
    bob = runtime.create_run("youtube-shorts", "Bob topic", "bob")

    assert runtime.get_run(alice["id"], "alice")["topic"] == "Alice topic"
    assert runtime.get_run(alice["id"], "bob") is None
    assert runtime.get_run(bob["id"], "alice") is None
    assert runtime.get_run(bob["id"], "bob")["topic"] == "Bob topic"

    with pytest.raises(ValueError, match="not found"):
        runtime.attach_render_result(alice["id"], {"video_id": "a" * 32}, "bob")


def test_runtime_database_migrates_legacy_runs_to_local_owner(tmp_path, monkeypatch):
    import sqlite3
    import app.production_runtime as runtime

    database = tmp_path / "legacy.sqlite3"
    monkeypatch.setattr(runtime, "DB_PATH", database)
    with sqlite3.connect(database) as conn:
        conn.execute("""CREATE TABLE production_runs (
            id TEXT PRIMARY KEY, format_id TEXT NOT NULL, topic TEXT NOT NULL,
            status TEXT NOT NULL, current_role TEXT, result_json TEXT,
            error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")
        conn.execute("""INSERT INTO production_runs
            (id,format_id,topic,status,created_at,updated_at)
            VALUES(?,?,?,?,?,?)""",
            ("f" * 32, "youtube-shorts", "Legacy topic", "paused", "now", "now"))

    legacy = runtime.get_run("f" * 32, "local")
    assert legacy is not None
    assert legacy["owner_username"] == "local"
    assert runtime.get_run("f" * 32, "another-user") is None



def test_list_runs_is_owner_scoped_and_newest_first(tmp_path, monkeypatch):
    import app.production_runtime as runtime

    monkeypatch.setattr(runtime, "DB_PATH", tmp_path / "runtime.sqlite3")
    first = runtime.create_run("youtube-shorts", "first topic", "alice")
    second = runtime.create_run("youtube-shorts", "second topic", "alice")
    runtime.create_run("youtube-shorts", "private topic", "bob")

    runs = runtime.list_runs("alice", limit=1)
    assert len(runs) == 1
    assert runs[0]["id"] == second["id"]
    assert runtime.list_runs("bob")[0]["topic"] == "private topic"
    assert all(run["owner_username"] == "alice" for run in runtime.list_runs("alice"))



def test_revision_attempt_limit_is_bounded_by_configuration(monkeypatch):
    import importlib
    import app.production_runtime as runtime

    monkeypatch.setenv("SINTU_MAX_REVISION_ATTEMPTS", "999")
    importlib.reload(runtime)
    assert runtime.MAX_REVISION_ATTEMPTS == 2
    monkeypatch.setenv("SINTU_MAX_REVISION_ATTEMPTS", "0")
    importlib.reload(runtime)
    assert runtime.MAX_REVISION_ATTEMPTS == 0
    monkeypatch.setenv("SINTU_MAX_REVISION_ATTEMPTS", "not-a-number")
    importlib.reload(runtime)
    assert runtime.MAX_REVISION_ATTEMPTS == 2



def test_owner_agent_not_ready_pauses_even_when_its_checker_passes(tmp_path, monkeypatch):
    import app.production_runtime as runtime
    from app.management_hierarchy import SENIOR_MANAGER_NAMES

    monkeypatch.setattr(runtime, "DB_PATH", tmp_path / "runtime.sqlite3")
    roles = ["Script Writer", *SENIOR_MANAGER_NAMES]
    monkeypatch.setattr(runtime, "format_team", lambda _format: [
        item
        for role in roles
        for item in (
            {"role_type": "specialist", "name": role, "mission": "Review assigned evidence."},
            {"role_type": "independent_checker", "name": role + " Checker", "checks": role},
        )
    ])

    def fake_generate(prompt, workflow, provider):
        lower = prompt.lower()
        if "you are the sintu owner agent" in lower:
            output = "NOT READY: copyright permission for one visual is not verified."
        elif "independent quality checker" in lower or "final video production reviewer" in lower:
            output = '{"decision":"PASS","evidence":["report accurately identifies the blocker"],"issues":[],"revision_instructions":[]}'
        else:
            output = "Reviewed production report."
        return {"output": output, "provider": "test", "model": "fixture"}

    monkeypatch.setattr(runtime, "generate_text", fake_generate)
    run = runtime.create_run("youtube-shorts", "भारत का इतिहास")
    runtime.execute_run(run["id"])
    result = runtime.get_run(run["id"])

    assert result["status"] == "paused"
    assert result["current_role"] == "Owner Agent"
    assert "release blockers" in result["error"]
    assert result["steps"][-2]["role"] == "Owner Agent"
    assert result["steps"][-1]["role"] == "Owner Agent Checker"


def test_interrupted_production_runs_recover_to_paused(tmp_path, monkeypatch):
    import app.production_runtime as runtime

    monkeypatch.setattr(runtime, "DB_PATH", tmp_path / "runtime.sqlite3")
    running = runtime.create_run("youtube-shorts", "Interrupted topic", "alice")
    runtime._set_run(running["id"], "running", current_role="Script Writer")
    reviewing = runtime.create_run("youtube-shorts", "Review interrupted", "bob")
    runtime._set_run(reviewing["id"], "reviewing", current_role="Audio Quality Reviewer")
    queued = runtime.create_run("youtube-shorts", "Still queued", "carol")

    assert runtime.recover_interrupted_runs() == 2
    assert runtime.get_run(running["id"], "alice")["status"] == "paused"
    assert runtime.get_run(reviewing["id"], "bob")["status"] == "paused"
    assert runtime.get_run(queued["id"], "carol")["status"] == "queued"
    assert "last independently approved checkpoint" in runtime.get_run(running["id"], "alice")["error"]


def test_resumed_run_skips_already_approved_specialist_checkpoints(tmp_path, monkeypatch):
    import app.production_runtime as runtime

    monkeypatch.setattr(runtime, "DB_PATH", tmp_path / "runtime.sqlite3")
    monkeypatch.setattr(runtime, "format_team", lambda _format: [
        {"role_type": "specialist", "name": "Script Writer", "mission": "write narration"},
        {"role_type": "specialist", "name": "Voice Artist", "mission": "prepare voice direction"},
    ])
    run = runtime.create_run("youtube-shorts", "भारत के किले")
    runtime._set_run(run["id"], "paused", current_role="Voice Artist",
                     error="Simulated process interruption")
    runtime._save_step(run["id"], 1, "Script Writer", "builder", "completed",
                       "script brief", "Previously approved Hindi narration")
    runtime._save_step(run["id"], 2, "Script Writer Checker", "checker", "pass",
                       "check script", '{"decision":"PASS"}',
                       ["Hindi narration is complete"], [])
    calls = []

    def fake_generate(prompt, workflow, provider):
        calls.append(prompt)
        if "independent quality checker" in prompt.lower() or "final video production reviewer" in prompt.lower():
            output = '{"decision":"PASS","evidence":["acceptance criteria checked"],"issues":[],"revision_instructions":[]}'
        elif "Role: Voice Artist" in prompt:
            output = "Voice direction for the approved narration"
        else:
            output = "Unexpected duplicate specialist execution"
        return {"output": output, "provider": "test", "model": "fixture"}

    monkeypatch.setattr(runtime, "generate_text", fake_generate)
    runtime.execute_run(run["id"])
    result = runtime.get_run(run["id"])

    assert result["status"] == "completed"
    assert result["result"]["deliverables"]["Script Writer"] == "Previously approved Hindi narration"
    assert result["result"]["deliverables"]["Voice Artist"] == "Voice direction for the approved narration"
    assert not any("Role: Script Writer" in prompt for prompt in calls)
    assert len([step for step in result["steps"] if step["role"] == "Script Writer" and step["step_type"] == "builder"]) == 1


def test_resumed_run_reuses_passed_final_reviewer_checkpoint(tmp_path, monkeypatch):
    import app.production_runtime as runtime

    monkeypatch.setattr(runtime, "DB_PATH", tmp_path / "runtime.sqlite3")
    monkeypatch.setattr(runtime, "format_team", lambda _format: [
        {"role_type": "specialist", "name": "Script Writer", "mission": "write narration"},
    ])
    run = runtime.create_run("youtube-shorts", "भारत का इतिहास")
    runtime._set_run(run["id"], "paused", current_role="Audio Quality Reviewer")
    runtime._save_step(run["id"], 1, "Script Writer", "builder", "completed",
                       "script brief", "Approved Hindi narration")
    runtime._save_step(run["id"], 2, "Script Writer Checker", "checker", "pass",
                       "check script", "PASS", ["Script checked"], [])
    saved_review = '{"decision":"PASS","evidence":["audio review completed"],"issues":[],"revision_instructions":[]}'
    runtime._save_step(run["id"], 3, "Audio Quality Reviewer", "reviewer", "pass",
                       "review prompt", saved_review, ["audio reviewed"], [])
    calls = []

    def fake_generate(prompt, workflow, provider):
        calls.append(prompt)
        return {"output": '{"decision":"PASS","evidence":["review complete"],"issues":[],"revision_instructions":[]}',
                "provider": "test", "model": "fixture"}

    monkeypatch.setattr(runtime, "generate_text", fake_generate)
    runtime.execute_run(run["id"])

    assert not any("Reviewer: Audio Quality Reviewer" in prompt for prompt in calls)
    assert len([step for step in runtime.get_run(run["id"])["steps"]
                if step["role"] == "Audio Quality Reviewer" and step["step_type"] == "reviewer"]) == 1



def test_documentary_runtime_passes_persisted_research_ledger_to_workers_and_reviewers(tmp_path, monkeypatch):
    import app.production_runtime as runtime
    from app.documentary_research import validate_documentary_evidence_for_production
    from app.research_evidence_store import save_research_evidence

    monkeypatch.setattr(runtime, "DB_PATH", tmp_path / "runtime.sqlite3")
    monkeypatch.setattr(runtime, "RESEARCH_EVIDENCE_DB_PATH", tmp_path / "studio.sqlite3")
    monkeypatch.setattr(runtime, "format_team", lambda _format: [
        {"role_type": "specialist", "name": "Fact Checker", "mission": "verify each claim against supplied evidence"},
        {"role_type": "specialist", "name": "Script Writer", "mission": "write a researched Hindi script"}
    ])
    package = {
        "schema_version": 1,
        "topic": "भारत का इतिहास",
        "researched_at": "2026-11-21T10:00:00+05:30",
        "sources": [
            {"id": "a", "title": "Archive", "publisher": "Archive A",
             "url": "https://archive-a.example/record", "accessed_at": "2026-11-21",
             "published_at": None, "source_type": "primary"},
            {"id": "b", "title": "Paper", "publisher": "University B",
             "url": "https://university-b.example/paper", "accessed_at": "2026-11-21",
             "published_at": "2020-01-01", "source_type": "academic"},
        ],
        "claims": [
            {"id": "claim-1", "text": "एक ऐतिहासिक घटना दर्ज है।",
             "claim_type": "factual", "status": "corroborated",
             "source_ids": ["a", "b"], "evidence_notes": "दोनों स्रोतों को स्वतंत्र रूप से पढ़ना आवश्यक है।"}
        ],
    }
    validation = validate_documentary_evidence_for_production(package)
    run = runtime.create_run("documentary", package["topic"], "owner")
    save_research_evidence(runtime.RESEARCH_EVIDENCE_DB_PATH, run["id"], "owner", package, validation)
    prompts = []

    def fake_generate(prompt, workflow, provider):
        prompts.append(prompt)
        if "independent quality checker" in prompt.lower() or "final video production reviewer" in prompt.lower():
            output = '{"decision":"PASS","evidence":["reviewed against supplied evidence ledger"],"issues":[],"revision_instructions":[]}'
        else:
            output = "भारत के इतिहास पर स्रोत-संदर्भित हिंदी स्क्रिप्ट।"
        return {"output": output, "provider": "test", "model": "fixture"}

    monkeypatch.setattr(runtime, "generate_text", fake_generate)
    runtime.execute_run(run["id"], "owner")
    result = runtime.get_run(run["id"], "owner")

    assert result["status"] == "completed"
    assert result["result"]["research_evidence"]["sha256"] == validation["sha256"]
    assert result["result"]["research_evidence"]["human_fact_check_required"] is True
    ledger_prompts = [prompt for prompt in prompts if "DOCUMENTARY RESEARCH EVIDENCE LEDGER" in prompt]
    assert len(ledger_prompts) >= 2
    assert any("Fact Checker" in prompt and "claim-1" in prompt for prompt in ledger_prompts)
    assert any("Script Writer" in prompt and "archive-a.example" in prompt for prompt in ledger_prompts)


def test_documentary_runtime_pauses_when_research_evidence_is_missing(tmp_path, monkeypatch):
    import app.production_runtime as runtime

    monkeypatch.setattr(runtime, "DB_PATH", tmp_path / "runtime.sqlite3")
    monkeypatch.setattr(runtime, "RESEARCH_EVIDENCE_DB_PATH", tmp_path / "studio.sqlite3")
    monkeypatch.setattr(runtime, "format_team", lambda _format: [
        {"role_type": "specialist", "name": "Script Writer", "mission": "write a researched Hindi script"}
    ])
    calls = []
    monkeypatch.setattr(runtime, "generate_text", lambda *args: calls.append(args))
    run = runtime.create_run("documentary", "भारत का इतिहास", "owner")
    runtime.execute_run(run["id"], "owner")
    result = runtime.get_run(run["id"], "owner")
    assert result["status"] == "paused"
    assert result["current_role"] == "Documentary Research Evidence"
    assert calls == []
