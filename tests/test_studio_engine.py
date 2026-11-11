import pytest
from app import studio_engine

def test_run_creates_ordered_worker_checker_gates(tmp_path, monkeypatch):
    monkeypatch.setenv("SINTU_DATA_DIR", str(tmp_path))
    run = studio_engine.create_run("tester", "project-1", "3d-animation")
    assert run["status"] == "queued"
    assert run["tasks"]
    assert run["tasks"][0]["status"] == "pending"
    assert all(task["checker"] != task["specialist"] for task in run["tasks"])
    assert all(task["status"] == "blocked" for task in run["tasks"][1:])
    assert any(task["specialist"] == "Rigging Setup Agent" for task in run["tasks"])
    assert any(task["specialist"] == "Text Training Agent" for task in run["tasks"])

def test_checker_pass_advances_and_fail_requires_revision(tmp_path, monkeypatch):
    monkeypatch.setenv("SINTU_DATA_DIR", str(tmp_path))
    run = studio_engine.create_run("tester", "project-1", "youtube-shorts")
    first = run["tasks"][0]
    submitted = studio_engine.submit_worker_output("tester", run["id"], first["id"], "worker output")
    assert submitted["tasks"][0]["status"] == "waiting_checker"
    with pytest.raises(ValueError):
        studio_engine.submit_checker_result("tester", run["id"], first["id"], "PASS", "")
    failed = studio_engine.submit_checker_result("tester", run["id"], first["id"], "FAIL", "evidence", "Fix accuracy")
    assert failed["tasks"][0]["status"] == "needs_revision"
    revised = studio_engine.revise_worker_output("tester", run["id"], first["id"], "revised output")
    assert revised["tasks"][0]["status"] == "waiting_checker"
    passed = studio_engine.submit_checker_result("tester", run["id"], first["id"], "PASS", "All criteria verified")
    assert passed["tasks"][0]["status"] == "approved"
    assert passed["tasks"][1]["status"] == "pending"

def test_owner_isolation_and_human_publish_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("SINTU_DATA_DIR", str(tmp_path))
    run = studio_engine.create_run("owner", "project-1", "youtube-shorts")
    assert studio_engine.get_run("other", run["id"]) is None
    with pytest.raises(ValueError):
        studio_engine.approve_run("owner", run["id"], True)
