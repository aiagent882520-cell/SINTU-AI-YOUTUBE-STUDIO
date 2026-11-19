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
    managers = [task for task in run["tasks"] if task["stage_id"] == "senior_management"]
    assert [task["specialist"] for task in managers] == ["HR Agent", "Manager Agent", "GM Agent", "HO Agent", "Owner Agent"]
    assert all(task["checker"] == task["specialist"] + " Checker" for task in managers)

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


def test_full_run_requires_every_checker_and_final_human_approval(tmp_path, monkeypatch):
    monkeypatch.setenv("SINTU_DATA_DIR", str(tmp_path))
    run = studio_engine.create_run("tester", "project-1", "youtube-shorts")
    while run["current_task_id"]:
        task = next(item for item in run["tasks"] if item["id"] == run["current_task_id"])
        run = studio_engine.submit_worker_output("tester", run["id"], task["id"], "Complete specialist deliverable.")
        run = studio_engine.submit_checker_result("tester", run["id"], task["id"], "PASS", "Independent criteria verified.")
    assert run["status"] == "awaiting_human_approval"
    completed = studio_engine.approve_run("tester", run["id"], True, "Final review passed.")
    assert completed["status"] == "completed"


def test_render_queue_cancel_retry_and_running_safety(tmp_path, monkeypatch):
    monkeypatch.setenv("SINTU_DATA_DIR", str(tmp_path))
    queued = studio_engine.enqueue_render("owner", "project-1", {"title": "keep"})
    assert studio_engine.cancel_queued_render("other", queued["id"]) is None
    assert studio_engine.cancel_queued_render("owner", queued["id"])["status"] == "cancelled"
    assert studio_engine.cancel_queued_render("owner", queued["id"]) is None
    failed = studio_engine.enqueue_render("owner", "project-1", {"title": "retry me"})
    studio_engine.update_render_item("owner", failed["id"], "running")
    studio_engine.update_render_item("owner", failed["id"], "failed", {"error": "temporary"})
    assert studio_engine.retry_failed_render("other", failed["id"]) is None
    retried = studio_engine.retry_failed_render("owner", failed["id"])
    assert retried["status"] == "queued" and retried["payload"] == {"title": "retry me"} and retried["result"] is None
    assert studio_engine.retry_failed_render("owner", failed["id"]) is None
    running = studio_engine.enqueue_render("owner", "project-1", {"title": "running"})
    studio_engine.update_render_item("owner", running["id"], "running")
    assert studio_engine.cancel_queued_render("owner", running["id"]) is None
    assert studio_engine.list_render_queue("owner")[0]["status"] == "running"


def test_recover_interrupted_render_queue_marks_only_running_jobs_failed(tmp_path, monkeypatch):
    monkeypatch.setenv("SINTU_DATA_DIR", str(tmp_path))
    queued = studio_engine.enqueue_render("owner", "project-1", {"title": "queued"})
    running = studio_engine.enqueue_render("owner", "project-1", {"title": "interrupted"})
    studio_engine.update_render_item("owner", running["id"], "running")
    recovered = studio_engine.recover_interrupted_render_queue()
    assert recovered == 1
    items = {item["id"]: item for item in studio_engine.list_render_queue("owner")}
    assert items[queued["id"]]["status"] == "queued"
    assert items[running["id"]]["status"] == "failed"
    assert items[running["id"]]["result"]["error_type"] == "server_restart"
    assert items[running["id"]]["result"]["retryable"] is True
