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


def test_each_run_persists_the_ordered_21_stage_ledger(tmp_path, monkeypatch):
    import app.production_runtime as runtime

    monkeypatch.setattr(runtime, "DB_PATH", tmp_path / "runtime.sqlite3")
    run = runtime.create_run("youtube-shorts", "Hindi science explainer", "owner-a")

    assert len(run["pipeline_stages"]) == 21
    assert [stage["sequence"] for stage in run["pipeline_stages"]] == list(range(1, 22))
    assert run["pipeline_stages"][0]["stage_id"] == "intake"
    assert run["pipeline_stages"][-1]["stage_id"] == "learning"
    assert run["pipeline_stage_execution_implemented"] is False
    assert all(stage["status"] == "pending" for stage in run["pipeline_stages"])


def test_pipeline_stage_transitions_require_evidence_lease_and_owner_approval(tmp_path, monkeypatch):
    import app.production_runtime as runtime

    monkeypatch.setattr(runtime, "DB_PATH", tmp_path / "runtime.sqlite3")
    run = runtime.create_run("youtube-shorts", "Hindi science explainer", "owner-a")

    with pytest.raises(ValueError, match="requires evidence"):
        runtime.transition_pipeline_stage(
            run["id"], "planning", "completed", owner_username="owner-a",
        )
    assert runtime._claim_run(run["id"], "owner-a") is True
    token = runtime._worker_token(run["id"], "owner-a")
    with pytest.raises(ValueError, match="Earlier pipeline stages are incomplete"):
        runtime.transition_pipeline_stage(
            run["id"], "planning", "running", owner_username="owner-a", worker_token=token,
        )
    runtime.transition_pipeline_stage(
        run["id"], "intake", "running", owner_username="owner-a", worker_token=token,
    )
    runtime.transition_pipeline_stage(
        run["id"], "intake", "completed", owner_username="owner-a",
        worker_token=token, evidence="Format and topic validated",
    )
    runtime.transition_pipeline_stage(
        run["id"], "planning", "running", owner_username="owner-a", worker_token=token,
    )
    with pytest.raises(runtime.ProductionRunCancelled, match="live fenced worker lease"):
        runtime.transition_pipeline_stage(
            run["id"], "planning", "completed", owner_username="owner-a",
            evidence="Acceptance criteria checked",
        )
    updated = runtime.transition_pipeline_stage(
        run["id"], "planning", "completed", owner_username="owner-a",
        worker_token=token, evidence="Acceptance criteria checked",
    )
    planning = next(stage for stage in updated["pipeline_stages"] if stage["stage_id"] == "planning")
    assert planning["status"] == "completed"
    assert planning["evidence"] == "Acceptance criteria checked"

    with runtime._connect() as conn:
        conn.execute("UPDATE production_pipeline_stages SET status='completed' WHERE run_id=? AND sequence<16",
                     (run["id"],))
    with pytest.raises(PermissionError, match="not worker-executable"):
        runtime.transition_pipeline_stage(
            run["id"], "owner_review", "running", owner_username="owner-a",
        )
    with pytest.raises(PermissionError, match="cannot be skipped"):
        runtime.transition_pipeline_stage(
            run["id"], "owner_review", "skipped", owner_username="owner-a",
        )
    runtime.transition_pipeline_stage(
        run["id"], "owner_review", "awaiting_owner", owner_username="owner-a",
    )
    with pytest.raises(PermissionError, match="Owner approval"):
        runtime.transition_pipeline_stage(
            run["id"], "owner_review", "completed", owner_username="owner-a",
            evidence="Review completed",
        )
    updated = runtime.transition_pipeline_stage(
        run["id"], "owner_review", "completed", owner_username="owner-a",
        evidence="Owner explicitly approved the creative package",
        owner_approved=True,
    )
    review = next(stage for stage in updated["pipeline_stages"] if stage["stage_id"] == "owner_review")
    assert review["status"] == "completed"


def test_pipeline_claiming_is_ordered_and_owner_gates_are_not_auto_approved(tmp_path, monkeypatch):
    import app.production_runtime as runtime

    monkeypatch.setattr(runtime, "DB_PATH", tmp_path / "runtime.sqlite3")
    run = runtime.create_run("youtube-shorts", "Hindi science explainer", "owner-a")
    assert runtime._claim_run(run["id"], "owner-a") is True
    token = runtime._worker_token(run["id"], "owner-a")

    first = runtime.claim_next_pipeline_stage(run["id"], owner_username="owner-a", worker_token=token)
    assert first["stage_id"] == "intake"
    assert first["status"] == "running"
    same = runtime.claim_next_pipeline_stage(run["id"], owner_username="owner-a", worker_token=token)
    assert same["stage_id"] == "intake"
    runtime.transition_pipeline_stage(
        run["id"], "intake", "completed", owner_username="owner-a",
        worker_token=token, evidence="Input contract validated",
    )
    second = runtime.claim_next_pipeline_stage(run["id"], owner_username="owner-a", worker_token=token)
    assert second["stage_id"] == "planning"
    assert second["status"] == "running"

    with runtime._connect() as conn:
        conn.execute(
            "UPDATE production_pipeline_stages SET status='completed' WHERE run_id=? AND sequence<16",
            (run["id"],),
        )
    with runtime._connect() as conn:
        conn.execute(
            "UPDATE production_pipeline_stages SET status='pending' WHERE run_id=? AND stage_id='owner_review'",
            (run["id"],),
        )
    owner_gate = runtime.claim_next_pipeline_stage(
        run["id"], owner_username="owner-a", worker_token=token,
    )
    assert owner_gate["stage_id"] == "owner_review"
    assert owner_gate["status"] == "awaiting_owner"
    with pytest.raises(PermissionError, match="explicitly awaiting Owner gate"):
        runtime.transition_pipeline_stage(
            run["id"], "owner_review", "completed", owner_username="owner-a",
            evidence="not approved",
        )


def test_pipeline_stage_ledger_is_owner_scoped(tmp_path, monkeypatch):
    import app.production_runtime as runtime

    monkeypatch.setattr(runtime, "DB_PATH", tmp_path / "runtime.sqlite3")
    run = runtime.create_run("youtube-shorts", "Hindi science explainer", "owner-a")
    assert runtime.transition_pipeline_stage(
        run["id"], "intake", "running", owner_username="owner-b",
    ) is None


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
    stages = {stage["stage_id"]: stage for stage in result["pipeline_stages"]}
    assert stages["script"]["status"] == "completed"
    assert stages["intake"]["status"] == "skipped"
    assert stages["quality"]["status"] == "completed"
    assert stages["owner_review"]["status"] == "awaiting_owner"
    assert result["pipeline_stage_execution_implemented"] is False
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
    stages = {stage["stage_id"]: stage for stage in result["pipeline_stages"]}
    assert stages["script"]["status"] == "completed"
    assert stages["owner_review"]["status"] == "blocked"
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
        elif "Role: Fact Checker" in prompt:
            output = "FACT CHECK RESULT: claim-1 is traceable to source IDs a and b; source contents still require human review."
        else:
            output = "भारत के इतिहास पर स्रोत-संदर्भित हिंदी स्क्रिप्ट।"
        return {"output": output, "provider": "test", "model": "fixture"}

    monkeypatch.setattr(runtime, "generate_text", fake_generate)
    runtime.execute_run(run["id"], "owner")
    result = runtime.get_run(run["id"], "owner")

    assert result["status"] == "completed"
    assert result["result"]["research_evidence"]["sha256"] == validation["sha256"]
    assert result["result"]["research_evidence"]["human_fact_check_required"] is True
    stages = {stage["stage_id"]: stage for stage in result["pipeline_stages"]}
    assert stages["research"]["status"] == "completed"
    assert stages["fact_check"]["status"] == "completed"
    ledger_prompts = [prompt for prompt in prompts if "DOCUMENTARY RESEARCH EVIDENCE LEDGER" in prompt]
    assert len(ledger_prompts) >= 2
    assert any("Fact Checker" in prompt and "claim-1" in prompt for prompt in ledger_prompts)
    script_prompt = next(prompt for prompt in ledger_prompts if "Role: Script Writer" in prompt)
    assert "archive-a.example" in script_prompt
    assert "FACT CHECK RESULT" in script_prompt


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


def test_owner_can_cancel_queued_run_idempotently_and_audit_transition(tmp_path, monkeypatch):
    import app.production_runtime as runtime

    monkeypatch.setattr(runtime, "DB_PATH", tmp_path / "runtime.sqlite3")
    run = runtime.create_run("youtube-shorts", "cancel me", "alice")
    first = runtime.request_cancel(run["id"], "alice")
    second = runtime.request_cancel(run["id"], "alice")

    assert first["status"] == "cancelled"
    assert second["status"] == "cancelled"
    assert runtime.request_cancel(run["id"], "bob") is None
    events = runtime.list_run_events(run["id"], "alice")
    assert [event["event_type"] for event in events].count("cancel_requested") == 1
    assert events[-1]["to_status"] == "cancelled"


def test_cancellation_during_model_call_wins_and_preserves_partial_outputs(tmp_path, monkeypatch):
    import app.production_runtime as runtime

    monkeypatch.setattr(runtime, "DB_PATH", tmp_path / "runtime.sqlite3")
    monkeypatch.setattr(runtime, "format_team", lambda _format: [
        {"role_type": "specialist", "name": "Script Writer", "mission": "write narration"}
    ])
    run = runtime.create_run("youtube-shorts", "cancel during call", "alice")
    calls = []

    def fake_generate(prompt, workflow, provider):
        calls.append(prompt)
        runtime.request_cancel(run["id"], "alice")
        return {"output": "Must not be persisted after cancellation", "provider": "test", "model": "fixture"}

    monkeypatch.setattr(runtime, "generate_text", fake_generate)
    runtime.execute_run(run["id"], "alice")
    result = runtime.get_run(run["id"], "alice")

    assert result["status"] == "cancelled"
    assert len(calls) == 1
    assert result["steps"] == []
    assert result["result"] is None
    stages = {stage["stage_id"]: stage for stage in result["pipeline_stages"]}
    assert stages["script"]["status"] == "paused"
    events = runtime.list_run_events(run["id"], "alice")
    assert any(event["to_status"] == "cancelling" for event in events)
    assert events[-1]["to_status"] == "cancelled"


def test_stale_worker_lease_is_recovered_and_old_worker_is_fenced(tmp_path, monkeypatch):
    import sqlite3
    from datetime import datetime, timedelta, timezone
    import app.production_runtime as runtime

    database = tmp_path / "runtime.sqlite3"
    monkeypatch.setattr(runtime, "DB_PATH", database)
    run = runtime.create_run("youtube-shorts", "recover stale worker", "alice")
    assert runtime._claim_run(run["id"], "alice") is True
    old_token = runtime._worker_token(run["id"], "alice")
    runtime.transition_pipeline_stage(
        run["id"], "intake", "running", owner_username="alice", worker_token=old_token,
    )
    expired = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE production_runs SET lease_expires_at=? WHERE id=?", (expired, run["id"]))

    assert runtime.recover_stale_runs() == 1
    recovered = runtime.get_run(run["id"], "alice")
    assert recovered["status"] == "paused"
    assert recovered["worker_token"] is None
    assert recovered["pipeline_stages"][0]["status"] == "paused"
    with pytest.raises(runtime.ProductionRunCancelled):
        runtime._save_step(run["id"], 1, "Script Writer", "builder", "completed",
                           "prompt", "stale output", worker_token=old_token)

    assert runtime._claim_run(run["id"], "alice") is True
    assert runtime._worker_token(run["id"], "alice") != old_token


def test_restart_recovery_finishes_pending_cancellation_without_deleting_steps(tmp_path, monkeypatch):
    import sqlite3
    from datetime import datetime, timedelta, timezone
    import app.production_runtime as runtime

    database = tmp_path / "runtime.sqlite3"
    monkeypatch.setattr(runtime, "DB_PATH", database)
    run = runtime.create_run("youtube-shorts", "restart during cancellation", "alice")
    assert runtime._claim_run(run["id"], "alice") is True
    token = runtime._worker_token(run["id"], "alice")
    runtime._save_step(run["id"], 1, "Script Writer", "builder", "completed",
                       "prompt", "preserved checkpoint", worker_token=token)
    assert runtime.request_cancel(run["id"], "alice")["status"] == "cancelling"
    expired = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE production_runs SET lease_expires_at=? WHERE id=?", (expired, run["id"]))

    assert runtime.recover_interrupted_runs() == 1
    result = runtime.get_run(run["id"], "alice")
    assert result["status"] == "cancelled"
    assert result["steps"][0]["output_text"] == "preserved checkpoint"
    assert runtime.list_run_events(run["id"], "alice")[-1]["event_type"] == "restart_recovery"


def test_completed_run_is_not_cancelled_or_modified(tmp_path, monkeypatch):
    import app.production_runtime as runtime

    monkeypatch.setattr(runtime, "DB_PATH", tmp_path / "runtime.sqlite3")
    run = runtime.create_run("youtube-shorts", "already completed", "alice")
    original = {"deliverables": {"Script Writer": "approved output"}, "video_rendered": False}
    runtime._set_run(run["id"], "completed", result=original)

    result = runtime.request_cancel(run["id"], "alice")
    assert result["status"] == "completed"
    assert result["result"] == original
    assert runtime.list_run_events(run["id"], "alice")[-1]["to_status"] == "completed"


def test_model_call_timeout_pauses_without_claiming_success(tmp_path, monkeypatch):
    import time
    import app.production_runtime as runtime

    monkeypatch.setattr(runtime, "DB_PATH", tmp_path / "runtime.sqlite3")
    monkeypatch.setattr(runtime, "format_team", lambda _format: [
        {"role_type": "specialist", "name": "Script Writer", "mission": "write narration"}
    ])
    monkeypatch.setattr(runtime, "MODEL_CALL_TIMEOUT_SECONDS", 0.001)

    def slow_generate(prompt, workflow, provider):
        time.sleep(0.01)
        return {"output": "late response", "provider": "test", "model": "fixture"}

    monkeypatch.setattr(runtime, "generate_text", slow_generate)
    run = runtime.create_run("youtube-shorts", "slow provider", "alice")
    runtime.execute_run(run["id"], "alice")

    result = runtime.get_run(run["id"], "alice")
    assert result["status"] == "paused"
    assert "exceeded" in result["error"]
    assert result["steps"] == []


def test_concurrent_cancel_requests_are_idempotent(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import app.production_runtime as runtime

    monkeypatch.setattr(runtime, "DB_PATH", tmp_path / "runtime.sqlite3")
    run = runtime.create_run("youtube-shorts", "concurrent cancel", "alice")
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _index: runtime.request_cancel(run["id"], "alice"), range(6)))

    assert all(item and item["status"] == "cancelled" for item in results)
    events = runtime.list_run_events(run["id"], "alice")
    assert [event["event_type"] for event in events].count("cancel_requested") == 1


def test_stale_cancelling_worker_is_recovered_by_run_poll(tmp_path, monkeypatch):
    import sqlite3
    from datetime import datetime, timedelta, timezone
    import app.production_runtime as runtime

    database = tmp_path / "runtime.sqlite3"
    monkeypatch.setattr(runtime, "DB_PATH", database)
    run = runtime.create_run("youtube-shorts", "cancel then worker crash", "alice")
    assert runtime._claim_run(run["id"], "alice") is True
    token = runtime._worker_token(run["id"], "alice")
    runtime._save_step(run["id"], 1, "Script Writer", "builder", "completed",
                       "prompt", "safe checkpoint", worker_token=token)
    assert runtime.request_cancel(run["id"], "alice")["status"] == "cancelling"

    expired = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE production_runs SET lease_expires_at=? WHERE id=?", (expired, run["id"]))

    recovered = runtime.get_run(run["id"], "alice")
    assert recovered["status"] == "cancelled"
    assert recovered["steps"][0]["output_text"] == "safe checkpoint"
    assert runtime.list_run_events(run["id"], "alice")[-1]["event_type"] == "stale_worker_recovered"


def test_startup_recovery_does_not_steal_a_live_worker_lease(tmp_path, monkeypatch):
    import app.production_runtime as runtime

    monkeypatch.setattr(runtime, "DB_PATH", tmp_path / "runtime.sqlite3")
    run = runtime.create_run("youtube-shorts", "live worker survives sibling startup", "alice")
    assert runtime._claim_run(run["id"], "alice") is True
    token = runtime._worker_token(run["id"], "alice")

    assert runtime.recover_interrupted_runs() == 0
    current = runtime.get_run(run["id"], "alice")
    assert current["status"] == "running"
    assert current["worker_token"] == token


def test_worker_cannot_transition_a_cancelling_run_to_success(tmp_path, monkeypatch):
    import app.production_runtime as runtime

    monkeypatch.setattr(runtime, "DB_PATH", tmp_path / "runtime.sqlite3")
    run = runtime.create_run("youtube-shorts", "cancel wins over success", "alice")
    assert runtime._claim_run(run["id"], "alice") is True
    token = runtime._worker_token(run["id"], "alice")
    assert runtime.request_cancel(run["id"], "alice")["status"] == "cancelling"

    assert runtime._set_run(run["id"], "completed", result={"fake": "success"},
                            worker_token=token) is False
    current = runtime.get_run(run["id"], "alice")
    assert current["status"] == "cancelling"
    assert current["result"] is None


def test_transient_provider_errors_retry_with_audited_backoff(tmp_path, monkeypatch):
    import app.production_runtime as runtime

    monkeypatch.setattr(runtime, "DB_PATH", tmp_path / "runtime.sqlite3")
    monkeypatch.setattr(runtime, "format_team", lambda _format: [
        {"role_type": "specialist", "name": "Script Writer", "mission": "write narration"}
    ])
    monkeypatch.setattr(runtime, "REVIEWERS", ())
    monkeypatch.setenv("SINTU_MODEL_RETRY_ATTEMPTS", "2")
    monkeypatch.setattr(runtime.time, "sleep", lambda _seconds: None)
    calls = []

    def flaky_generate(prompt, workflow, provider):
        calls.append(prompt)
        if len(calls) == 1:
            raise runtime.ProviderRequestError("Local server returned HTTP 503.")
        if len(calls) == 2:
            return {"output": "   ", "provider": "test", "model": "fixture"}
        return {"output": '{"decision":"PASS","evidence":["checked"],"issues":[],"revision_instructions":[]}',
                "provider": "test", "model": "fixture"}

    monkeypatch.setattr(runtime, "generate_text", flaky_generate)
    run = runtime.create_run("youtube-shorts", "retry transient model error", "alice")
    runtime.execute_run(run["id"], "alice")

    result = runtime.get_run(run["id"], "alice")
    assert result["status"] == "completed"
    assert len(calls) == 4
    retry_events = [event for event in runtime.list_run_events(run["id"], "alice")
                    if event["event_type"] == "model_call_retry"]
    assert len(retry_events) == 2


def test_durable_queue_exposes_only_queued_runs_not_human_paused_work(tmp_path, monkeypatch):
    import app.production_runtime as runtime

    monkeypatch.setattr(runtime, "DB_PATH", tmp_path / "queued-runtime.sqlite3")
    queued = runtime.create_run("youtube-shorts", "Queued work")
    paused = runtime.create_run("youtube-shorts", "Human review required")
    assert runtime._set_run(paused["id"], "paused", error="Independent checker requires human review.")

    rows = runtime.list_queued_runs(limit=10)
    assert rows == [{"id": queued["id"], "owner_username": "local"}]
    assert runtime.get_run(paused["id"])["status"] == "paused"

def test_runtime_dispatches_existing_roles_in_stage_order_and_persists_checkpoints(tmp_path, monkeypatch):
    import app.production_runtime as runtime

    monkeypatch.setattr(runtime, "DB_PATH", tmp_path / "runtime.sqlite3")
    monkeypatch.setattr(runtime, "format_team", lambda _format: [
        {"role_type": "specialist", "name": "Script Writer", "mission": "write the script"},
        {"role_type": "specialist", "name": "Fact Checker", "mission": "check claims"},
        {"role_type": "specialist", "name": "Web Research", "mission": "research sources"},
    ])

    def fake_generate(prompt, workflow, provider):
        lower = prompt.lower()
        if "independent quality checker" in lower or "final video production reviewer" in lower:
            output = '{"decision":"PASS","evidence":["acceptance criteria checked"],"issues":[],"revision_instructions":[]}'
        else:
            output = "Approved specialist deliverable."
        return {"output": output, "provider": "test", "model": "fixture"}

    monkeypatch.setattr(runtime, "generate_text", fake_generate)
    run = runtime.create_run("youtube-shorts", "भारत के जल स्रोत", "owner")
    runtime.execute_run(run["id"])
    result = runtime.get_run(run["id"], "owner")

    builders = [step["role"] for step in result["steps"] if step["step_type"] == "builder"]
    assert builders == ["Web Research", "Fact Checker", "Script Writer"]
    stages = {stage["stage_id"]: stage for stage in result["pipeline_stages"]}
    assert stages["research"]["status"] == "completed"
    assert stages["fact_check"]["status"] == "completed"
    assert stages["script"]["status"] == "completed"
    assert stages["intake"]["status"] == "skipped"
    assert stages["quality"]["status"] == "completed"
    assert stages["owner_review"]["status"] == "awaiting_owner"
    assert result["pipeline_stage_role_dispatch_integrated"] is True
    assert result["pipeline_stage_execution_implemented"] is False
    assert result["result"]["pipeline_dispatch"]["mode"] == "existing_specialist_checker_roles"
    assert result["result"]["pipeline_dispatch"]["full_21_stage_execution"] is False
    assert {"research", "fact_check", "script", "quality"}.issubset(
        set(result["result"]["pipeline_dispatch"]["completed_stage_ids"])
    )
    assert "intake" in result["result"]["pipeline_dispatch"]["skipped_stage_ids"]
    assert result["result"]["pipeline_dispatch"]["awaiting_owner_stage_ids"] == ["owner_review"]
    assert "render" in result["result"]["pipeline_dispatch"]["deferred_stage_ids"]

def test_legacy_completed_runs_are_backfilled_without_false_stage_completion(tmp_path, monkeypatch):
    import app.production_runtime as runtime

    monkeypatch.setattr(runtime, "DB_PATH", tmp_path / "runtime.sqlite3")
    runtime.init_runtime_db()
    now = runtime._now()
    with runtime._connect() as conn:
        conn.execute(
            """INSERT INTO production_runs
               (id,format_id,topic,status,owner_username,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?)""",
            ("c" * 32, "youtube-shorts", "legacy completed run", "completed", "owner", now, now),
        )

    run = runtime.get_run("c" * 32, "owner")
    assert len(run["pipeline_stages"]) == 21
    stages = {stage["stage_id"]: stage for stage in run["pipeline_stages"]}
    assert stages["intake"]["status"] == "skipped"
    assert stages["quality"]["status"] == "skipped"
    assert stages["owner_review"]["status"] == "awaiting_owner"
    assert stages["render"]["status"] == "pending"
    assert "no per-stage evidence" in stages["intake"]["issues"][0]
    events = runtime.list_run_events("c" * 32, "owner")
    assert any(event["event_type"] == "pipeline_ledger_backfilled" for event in events)

def test_owner_media_executor_advances_render_and_package_after_owner_review(tmp_path, monkeypatch):
    import app.production_runtime as runtime

    monkeypatch.setattr(runtime, "DB_PATH", tmp_path / "runtime.sqlite3")
    run = runtime.create_run("youtube-shorts", "स्थानीय मीडिया परीक्षण", "owner")
    runtime._set_run(
        run["id"], "completed",
        result={"pipeline_dispatch": {
            "mode": "existing_specialist_checker_roles",
            "completed_stage_ids": [],
            "skipped_stage_ids": [],
            "awaiting_owner_stage_ids": ["owner_review"],
            "deferred_stage_ids": ["render", "package", "publishing", "analytics_earnings", "learning"],
            "full_21_stage_execution": False,
        }},
    )
    with pytest.raises(PermissionError, match="Human Owner Review"):
        runtime.transition_owner_media_stage(
            run["id"], "render", "running", owner_username="owner",
        )
    with runtime._connect() as conn:
        conn.execute(
            "UPDATE production_pipeline_stages SET status='completed' WHERE run_id=? AND sequence<16",
            (run["id"],),
        )
    runtime.transition_pipeline_stage(
        run["id"], "owner_review", "awaiting_owner", owner_username="owner",
    )
    runtime.transition_pipeline_stage(
        run["id"], "owner_review", "completed", owner_username="owner",
        evidence="Owner explicitly approved the package", owner_approved=True,
    )

    runtime.transition_owner_media_stage(
        run["id"], "render", "running", owner_username="owner",
    )
    with pytest.raises(ValueError, match="Earlier pipeline stages are incomplete"):
        runtime.transition_owner_media_stage(
            run["id"], "package", "running", owner_username="owner",
        )
    runtime.transition_owner_media_stage(
        run["id"], "render", "completed", owner_username="owner",
        evidence="Verified MP4 and provenance manifest passed.",
    )
    runtime.transition_owner_media_stage(
        run["id"], "package", "running", owner_username="owner",
    )
    updated = runtime.transition_owner_media_stage(
        run["id"], "package", "completed", owner_username="owner",
        evidence="Owner-scoped media package attached.",
    )

    stages = {stage["stage_id"]: stage for stage in updated["pipeline_stages"]}
    assert stages["render"]["status"] == "completed"
    assert stages["package"]["status"] == "completed"
    assert stages["publishing"]["status"] == "pending"
    dispatch = updated["result"]["pipeline_dispatch"]
    assert dispatch["completed_stage_ids"] == ["owner_review", "render", "package"]
    assert dispatch["awaiting_owner_stage_ids"] == []
    assert dispatch["deferred_stage_ids"] == ["publishing", "analytics_earnings", "learning"]
    assert runtime.transition_owner_media_stage(
        run["id"], "render", "running", owner_username="other",
    ) is None

