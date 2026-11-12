import json

from app.agents import AGENTS, list_agents
from app.agent_orchestrator import catalog_team
import app.production_runtime as runtime


def test_catalog_contains_all_61_roles_with_distinct_checkers():
    team = catalog_team()
    workers = [item for item in team if item["role_type"] == "specialist"]
    checkers = [item for item in team if item["role_type"] == "independent_checker"]
    assert len(AGENTS) == 61
    assert len(workers) == len(checkers) == 61
    assert [item["name"] for item in workers] == AGENTS
    assert all(item["checks"] == worker["name"] for worker, item in zip(workers, checkers))
    assert all(item["name"] != item["checks"] for item in checkers)
    assert all(item["status"] == "Runnable worker/checker role" for item in list_agents())


def test_full_catalog_run_executes_each_worker_checker_and_final_review(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "DB_PATH", tmp_path / "catalog.sqlite3")
    calls = []

    def fake_generate(prompt, workflow, provider):
        calls.append(prompt)
        is_gate = "independent quality checker" in prompt.lower() or "final video production reviewer" in prompt.lower()
        output = (
            json.dumps({"decision": "PASS", "evidence": ["role output checked against its mission"],
                        "issues": [], "revision_instructions": []})
            if is_gate else "Role-specific test deliverable."
        )
        return {"output": output, "provider": "test", "model": "fixture"}

    monkeypatch.setattr(runtime, "generate_text", fake_generate)
    run = runtime.create_run("__agent_catalog__", "End-to-end catalog validation", "test-owner")
    runtime.execute_run(run["id"], "test-owner")
    result = runtime.get_run(run["id"], "test-owner")

    assert result["status"] == "completed"
    assert len([step for step in result["steps"] if step["step_type"] == "builder"]) == 61
    assert len([step for step in result["steps"] if step["step_type"] == "checker"]) == 61
    assert len([step for step in result["steps"] if step["step_type"] == "reviewer"]) == 5
    assert len(result["result"]["deliverables"]) == 61
    assert result["result"]["video_rendered"] is False
    assert result["result"]["published"] is False
    assert len(calls) == 127


def test_full_catalog_run_pauses_on_first_failed_independent_checker(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "DB_PATH", tmp_path / "catalog-fail.sqlite3")
    calls = []

    def fake_generate(prompt, workflow, provider):
        calls.append(prompt)
        if "independent quality checker" in prompt.lower():
            return {"output": json.dumps({
                "decision": "FAIL", "evidence": [], "issues": ["missing evidence"],
                "revision_instructions": ["supply concrete evidence"],
            }), "provider": "test", "model": "fixture"}
        return {"output": "Draft output.", "provider": "test", "model": "fixture"}

    monkeypatch.setattr(runtime, "generate_text", fake_generate)
    run = runtime.create_run("__agent_catalog__", "Failure gate test")
    runtime.execute_run(run["id"])
    result = runtime.get_run(run["id"])

    assert result["status"] == "paused"
    assert result["current_role"] == AGENTS[0] + " Checker"
    assert len([step for step in result["steps"] if step["step_type"] == "builder"]) == 2
    assert len([step for step in result["steps"] if step["step_type"] == "checker"]) == 2
    assert not any(step["step_type"] == "reviewer" for step in result["steps"])
