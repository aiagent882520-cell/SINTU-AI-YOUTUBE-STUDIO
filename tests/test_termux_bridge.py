import pytest
from fastapi.testclient import TestClient

from app import main


API_TOKEN = "test-bridge-token-that-is-at-least-32-bytes"
WORKER_TOKEN = "test-worker-token-that-is-at-least-32-bytes"


def bridge_client(tmp_path, monkeypatch):
    monkeypatch.setenv("SINTU_AUTH_REQUIRED", "false")
    monkeypatch.setenv("SINTU_BRIDGE_TOKEN", API_TOKEN)
    monkeypatch.setenv("SINTU_BRIDGE_WORKER_TOKEN", WORKER_TOKEN)
    monkeypatch.setenv("SINTU_BRIDGE_DB_PATH", str(tmp_path / "bridge.sqlite3"))
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "studio.sqlite3")
    main._FIREWALL_LIMITER.reset()
    main.init_db()
    return (
        TestClient(main.app),
        {"Authorization": f"Bearer {API_TOKEN}"},
        {"Authorization": f"Bearer {WORKER_TOKEN}"},
    )


def test_bridge_rejects_missing_and_invalid_tokens(tmp_path, monkeypatch):
    client, api_headers, _ = bridge_client(tmp_path, monkeypatch)
    assert client.get("/api/termux-bridge/status").status_code == 401
    assert client.get("/api/termux-bridge/status", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/termux-bridge/status", headers=api_headers).status_code == 200


def test_bridge_queue_claim_complete_and_readback(tmp_path, monkeypatch):
    client, api_headers, worker_headers = bridge_client(tmp_path, monkeypatch)
    created = client.post("/api/termux-bridge/jobs", headers=api_headers, json={"action": "git_status"})
    assert created.status_code == 202
    job_id = created.json()["job_id"]
    assert created.json()["status"] == "queued"

    # The worker credential, not the ChatGPT/API credential, owns execution.
    assert client.get("/api/termux-bridge/jobs/next", headers=api_headers).status_code == 401
    claimed = client.get("/api/termux-bridge/jobs/next", headers=worker_headers)
    assert claimed.status_code == 200
    assert claimed.json()["job_id"] == job_id
    assert claimed.json()["action"] == "git_status"
    assert client.get("/api/termux-bridge/jobs/next", headers=worker_headers).status_code == 204

    completed = client.post(
        f"/api/termux-bridge/jobs/{job_id}/complete", headers=worker_headers,
        json={"status": "succeeded", "exit_code": 0, "output": "## main"},
    )
    assert completed.status_code == 200
    result = client.get(f"/api/termux-bridge/jobs/{job_id}", headers=api_headers)
    assert result.status_code == 200
    assert result.json()["status"] == "succeeded"
    assert result.json()["output"] == "## main"
    assert result.json()["payload"] == {}


def test_bridge_rejects_arbitrary_commands_and_unsafe_test_paths(tmp_path, monkeypatch):
    client, api_headers, _ = bridge_client(tmp_path, monkeypatch)
    assert client.post("/api/termux-bridge/jobs", headers=api_headers, json={"action": "shell", "command": "rm -rf /"}).status_code == 422
    assert client.post(
        "/api/termux-bridge/jobs", headers=api_headers,
        json={"action": "run_tests", "test_path": "../../secret.py"},
    ).status_code == 400
    assert client.post(
        "/api/termux-bridge/jobs", headers=api_headers,
        json={"action": "git_status", "test_path": "tests/test_api.py"},
    ).status_code == 400


def test_bridge_requires_a_strong_configured_token(tmp_path, monkeypatch):
    client, _, _ = bridge_client(tmp_path, monkeypatch)
    monkeypatch.setenv("SINTU_BRIDGE_TOKEN", "short")
    response = client.get(
        "/api/termux-bridge/status",
        headers={"Authorization": "Bearer short"},
    )
    assert response.status_code == 503


def test_bridge_worker_requires_its_own_strong_token(tmp_path, monkeypatch):
    client, api_headers, _ = bridge_client(tmp_path, monkeypatch)
    response = client.get("/api/termux-bridge/jobs/next", headers=api_headers)
    assert response.status_code == 401



def test_bridge_requeues_jobs_abandoned_by_crashed_worker(tmp_path, monkeypatch):
    import sqlite3
    from datetime import datetime, timedelta, timezone

    client, api_headers, worker_headers = bridge_client(tmp_path, monkeypatch)
    created = client.post("/api/termux-bridge/jobs", headers=api_headers, json={"action": "git_status"})
    job_id = created.json()["job_id"]
    claimed = client.get("/api/termux-bridge/jobs/next", headers=worker_headers)
    assert claimed.status_code == 200

    stale_time = (datetime.now(timezone.utc) - timedelta(minutes=40)).isoformat()
    with sqlite3.connect(tmp_path / "bridge.sqlite3") as conn:
        conn.execute("UPDATE bridge_jobs SET started_at=? WHERE id=?", (stale_time, job_id))

    reclaimed = client.get("/api/termux-bridge/jobs/next", headers=worker_headers)
    assert reclaimed.status_code == 200
    assert reclaimed.json()["job_id"] == job_id



def test_bridge_bearer_auth_works_without_admin_browser_session(tmp_path, monkeypatch):
    client, api_headers, _ = bridge_client(tmp_path, monkeypatch)
    monkeypatch.setenv("SINTU_AUTH_REQUIRED", "true")
    # Bridge's own API token must be sufficient; browser login is a separate
    # authentication system and should not block the dedicated service API.
    response = client.get("/api/termux-bridge/status", headers=api_headers)
    assert response.status_code == 200
    assert response.json()["enabled"] is True
    assert response.json()["automation_only"] is True
    assert set(response.json()["paused_actions"]) == {"offline_video_e2e", "full_self_test", "full_studio_e2e"}
    assert client.get("/api/termux-bridge/status").status_code == 401


def test_bridge_queues_automation_actions_and_pauses_video_jobs(tmp_path, monkeypatch):
    client, api_headers, worker_headers = bridge_client(tmp_path, monkeypatch)
    readiness = client.post("/api/termux-bridge/jobs", headers=api_headers,
                            json={"action": "operational_readiness"})
    assert readiness.status_code == 202
    preflight = client.post("/api/termux-bridge/jobs", headers=api_headers,
                            json={"action": "live_preflight"})
    probe = client.post("/api/termux-bridge/jobs", headers=api_headers,
                        json={"action": "engine_probe"})
    assert probe.status_code == 202
    assert preflight.status_code == 202
    video = client.post("/api/termux-bridge/jobs", headers=api_headers,
                        json={"action": "offline_video_e2e", "topic": "भारत के किले"})
    full_studio = client.post("/api/termux-bridge/jobs", headers=api_headers,
                              json={"action": "full_studio_e2e", "topic": "भारत के किले"})
    assert video.status_code == 423

    assert full_studio.status_code == 423
    jobs = [client.get("/api/termux-bridge/jobs/next", headers=worker_headers).json()
            for _ in range(3)]
    assert [job["action"] for job in jobs] == [
        "operational_readiness", "live_preflight", "engine_probe"
    ]


def test_bridge_restricts_topics_to_offline_video_e2e(tmp_path, monkeypatch):
    client, api_headers, _ = bridge_client(tmp_path, monkeypatch)
    assert client.post("/api/termux-bridge/jobs", headers=api_headers,
                       json={"action": "git_status", "topic": "not allowed"}).status_code == 400
    assert client.post("/api/termux-bridge/jobs", headers=api_headers,
                       json={"action": "offline_video_e2e", "topic": "x" * 301}).status_code == 422


def test_worker_maps_e2e_actions_to_fixed_argument_arrays(monkeypatch):
    monkeypatch.setattr("scripts.termux_bridge_worker.AUTOMATION_ONLY", False)
    from scripts import termux_bridge_worker as worker

    monkeypatch.setattr(worker, "PYTHON", "/sintu/.venv/bin/python")
    assert worker.command_for({"action": "operational_readiness", "payload": {}}) == [
        "/sintu/.venv/bin/python", "scripts/operational_readiness.py", "--json"
    ]
    assert worker.command_for({"action": "engine_probe", "payload": {}}) == [
        "/sintu/.venv/bin/python", "scripts/engine_probe.py"
    ]
    assert worker.command_for({"action": "live_preflight", "payload": {}}) == [
        "/sintu/.venv/bin/python", "scripts/live_e2e.py"
    ]
    assert worker.command_for({"action": "offline_video_e2e", "payload": {"topic": "भारत के किले"}}) == [
        "/sintu/.venv/bin/python", "scripts/live_e2e.py", "--offline-video", "--topic", "भारत के किले"
    ]
    assert worker.command_for({"action": "full_studio_e2e", "payload": {"topic": "भारत के किले"}}) == [
        "/sintu/.venv/bin/python", "scripts/live_e2e.py", "--full-studio-e2e", "--topic", "भारत के किले"
    ]
    with pytest.raises(ValueError, match="Rejected offline video topic"):
        worker.command_for({"action": "offline_video_e2e", "payload": {"topic": "x" * 301}})


def test_bridge_queues_full_self_test_with_optional_topic(tmp_path, monkeypatch):
    client, api_headers, worker_headers = bridge_client(tmp_path, monkeypatch)
    created = client.post(
        "/api/termux-bridge/jobs", headers=api_headers,
        json={"action": "full_self_test", "topic": "भारत की विरासत"},
    )
    assert created.status_code == 423


def test_worker_maps_full_self_test_to_fixed_local_script(monkeypatch):
    monkeypatch.setattr("scripts.termux_bridge_worker.AUTOMATION_ONLY", False)
    from scripts import termux_bridge_worker as worker

    monkeypatch.setattr(worker, "PYTHON", "/sintu/.venv/bin/python")
    assert worker.command_for({"action": "full_self_test", "payload": {}}) == [
        "/sintu/.venv/bin/python", "scripts/sintu_self_test.py"
    ]
    assert worker.command_for({"action": "full_self_test", "payload": {"topic": "भारत की विरासत"}}) == [
        "/sintu/.venv/bin/python", "scripts/sintu_self_test.py", "--topic", "भारत की विरासत"
    ]
    with pytest.raises(ValueError, match="Rejected full self-test topic"):
        worker.command_for({"action": "full_self_test", "payload": {"topic": "x" * 301}})



def test_bridge_queues_full_studio_e2e(tmp_path, monkeypatch):
    client, api_headers, worker_headers = bridge_client(tmp_path, monkeypatch)
    created = client.post("/api/termux-bridge/jobs", headers=api_headers,
                          json={"action": "full_studio_e2e", "topic": "भारत के किले"})
    assert created.status_code == 423


def test_worker_maps_full_studio_e2e_to_full_production_pipeline(monkeypatch):
    monkeypatch.setattr("scripts.termux_bridge_worker.AUTOMATION_ONLY", False)
    from scripts import termux_bridge_worker as worker
    monkeypatch.setattr(worker, "PYTHON", "/sintu/.venv/bin/python")
    assert worker.command_for({"action": "full_studio_e2e", "payload": {"topic": "भारत"}}) == [
        "/sintu/.venv/bin/python", "scripts/live_e2e.py", "--full-studio-e2e", "--topic", "भारत"
    ]
    with pytest.raises(ValueError, match="Rejected full studio topic"):
        worker.command_for({"action": "full_studio_e2e", "payload": {"topic": "x" * 301}})


def test_worker_blocks_production_jobs_while_automation_only(monkeypatch):
    from scripts import termux_bridge_worker as worker
    monkeypatch.setattr(worker, "AUTOMATION_ONLY", True)
    for action in ("offline_video_e2e", "full_self_test", "full_studio_e2e"):
        with pytest.raises(ValueError, match="paused"):
            worker.command_for({"action": action, "payload": {}})


def test_bridge_queues_safe_optional_install_and_worker_maps_it(tmp_path, monkeypatch):
    client, api_headers, worker_headers = bridge_client(tmp_path, monkeypatch)
    created = client.post(
        "/api/termux-bridge/jobs", headers=api_headers,
        json={"action": "safe_optional_install"},
    )
    assert created.status_code == 202
    job = client.get("/api/termux-bridge/jobs/next", headers=worker_headers)
    assert job.status_code == 200
    assert job.json()["action"] == "safe_optional_install"


def test_worker_maps_safe_optional_install_to_fixed_script(monkeypatch):
    from scripts import termux_bridge_worker as worker

    monkeypatch.setattr(worker, "AUTOMATION_ONLY", True)
    assert worker.command_for({"action": "safe_optional_install", "payload": {}}) == [
        "bash", "scripts/termux_safe_optional_install.sh"
    ]


def test_bridge_queues_read_only_media_forensics_action(tmp_path, monkeypatch):
    client, api_headers, worker_headers = bridge_client(tmp_path, monkeypatch)
    created = client.post("/api/termux-bridge/jobs", headers=api_headers,
                          json={"action": "media_forensics"})
    assert created.status_code == 202
    job = client.get("/api/termux-bridge/jobs/next", headers=worker_headers)
    assert job.status_code == 200
    assert job.json()["action"] == "media_forensics"


def test_bridge_queues_restart_and_media_repair_actions(tmp_path, monkeypatch):
    client, api_headers, worker_headers = bridge_client(tmp_path, monkeypatch)
    for action in ("restart_services", "media_repair"):
        created = client.post(
            "/api/termux-bridge/jobs", headers=api_headers,
            json={"action": action},
        )
        assert created.status_code == 202
        job = client.get("/api/termux-bridge/jobs/next", headers=worker_headers)
        assert job.status_code == 200
        assert job.json()["action"] == action
        completed = client.post(
            f"/api/termux-bridge/jobs/{job.json()['job_id']}/complete",
            headers=worker_headers,
            json={"status": "succeeded", "exit_code": 0, "output": "ok"},
        )
        assert completed.status_code == 200


def test_worker_maps_read_only_media_forensics_to_fixed_script(monkeypatch):
    from scripts import termux_bridge_worker as worker
    monkeypatch.setattr(worker, "PYTHON", "/sintu/.venv/bin/python")
    assert worker.command_for({"action": "media_forensics", "payload": {}}) == [
        "/sintu/.venv/bin/python", "scripts/media_forensics.py", "--json"
    ]


def test_worker_maps_device_maintenance_actions_to_fixed_commands(monkeypatch):
    from scripts import termux_bridge_worker as worker

    monkeypatch.setattr(worker, "AUTOMATION_ONLY", True)
    monkeypatch.setattr(worker, "PYTHON", "/sintu/.venv/bin/python")
    assert worker.command_for({"action": "restart_services", "payload": {}}) == [
        "bash", "scripts/start_services.sh"
    ]
    assert worker.command_for({"action": "media_repair", "payload": {}}) == [
        "/sintu/.venv/bin/python", "scripts/repair_media.py", "--apply", "--json"
    ]


def test_bridge_queues_watchdog_recovery_test_and_worker_maps_it(tmp_path, monkeypatch):
    client, api_headers, worker_headers = bridge_client(tmp_path, monkeypatch)
    created = client.post(
        "/api/termux-bridge/jobs", headers=api_headers,
        json={"action": "watchdog_recovery_test"},
    )
    assert created.status_code == 202
    job = client.get("/api/termux-bridge/jobs/next", headers=worker_headers)
    assert job.status_code == 200
    assert job.json()["action"] == "watchdog_recovery_test"


def test_worker_maps_watchdog_recovery_test_to_fixed_script(monkeypatch):
    from scripts import termux_bridge_worker as worker

    monkeypatch.setattr(worker, "AUTOMATION_ONLY", True)
    monkeypatch.setattr(worker, "PYTHON", "/sintu/.venv/bin/python")
    assert worker.command_for({"action": "watchdog_recovery_test", "payload": {}}) == [
        "/sintu/.venv/bin/python", "scripts/watchdog_recovery_test.py", "--json"
    ]


def test_bridge_worker_returns_restart_after_successful_restart_job(monkeypatch):
    from scripts import termux_bridge_worker as worker

    calls = []

    def fake_request_json(path, method="GET", payload=None):
        calls.append((path, method, payload))
        if path.endswith("/jobs/next"):
            return {
                "job_id": "a" * 32,
                "action": "restart_services",
                "payload": {},
            }
        return {}

    monkeypatch.setattr(worker, "request_json", fake_request_json)
    monkeypatch.setattr(worker, "execute", lambda job: (0, "restart scheduled"))

    assert worker.run_once() == "restart"
    assert calls[-1][1] == "POST"
    assert calls[-1][2]["status"] == "succeeded"


def test_bridge_worker_exits_instead_of_polling_after_restart(monkeypatch):
    import sys
    from scripts import termux_bridge_worker as worker

    calls = []
    monkeypatch.setattr(worker, "TOKEN", "worker-token-that-is-at-least-32-bytes")
    monkeypatch.setattr(sys, "argv", ["termux_bridge_worker"])
    monkeypatch.setattr(worker, "run_once", lambda: calls.append("restart") or "restart")

    assert worker.main() == 0
    assert calls == ["restart"]


def test_bridge_worker_stops_after_restart_even_if_acknowledgement_fails(monkeypatch):
    from scripts import termux_bridge_worker as worker

    def fake_request_json(path, method="GET", payload=None):
        if path.endswith("/jobs/next"):
            return {
                "job_id": "b" * 32,
                "action": "restart_services",
                "payload": {},
            }
        raise RuntimeError("temporary bridge outage")

    monkeypatch.setattr(worker, "request_json", fake_request_json)
    monkeypatch.setattr(worker, "execute", lambda job: (0, "restart scheduled"))

    assert worker.run_once() == "restart"
