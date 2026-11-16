from fastapi.testclient import TestClient

from app import main


def bridge_client(tmp_path, monkeypatch):
    monkeypatch.setenv("SINTU_AUTH_REQUIRED", "false")
    monkeypatch.setenv("SINTU_BRIDGE_TOKEN", "test-bridge-token-that-is-at-least-32-bytes")
    monkeypatch.setenv("SINTU_BRIDGE_DB_PATH", str(tmp_path / "bridge.sqlite3"))
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "studio.sqlite3")
    main._FIREWALL_LIMITER.reset()
    main.init_db()
    return TestClient(main.app), {"Authorization": "Bearer test-bridge-token-that-is-at-least-32-bytes"}


def test_bridge_rejects_missing_and_invalid_tokens(tmp_path, monkeypatch):
    client, headers = bridge_client(tmp_path, monkeypatch)
    assert client.get("/api/termux-bridge/status").status_code == 401
    assert client.get("/api/termux-bridge/status", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/termux-bridge/status", headers=headers).status_code == 200


def test_bridge_queue_claim_complete_and_readback(tmp_path, monkeypatch):
    client, headers = bridge_client(tmp_path, monkeypatch)
    created = client.post("/api/termux-bridge/jobs", headers=headers, json={"action": "git_status"})
    assert created.status_code == 202
    job_id = created.json()["job_id"]
    assert created.json()["status"] == "queued"

    claimed = client.get("/api/termux-bridge/jobs/next", headers=headers)
    assert claimed.status_code == 200
    assert claimed.json()["job_id"] == job_id
    assert claimed.json()["action"] == "git_status"
    assert client.get("/api/termux-bridge/jobs/next", headers=headers).status_code == 204

    completed = client.post(
        f"/api/termux-bridge/jobs/{job_id}/complete", headers=headers,
        json={"status": "succeeded", "exit_code": 0, "output": "## main"},
    )
    assert completed.status_code == 200
    result = client.get(f"/api/termux-bridge/jobs/{job_id}", headers=headers)
    assert result.status_code == 200
    assert result.json()["status"] == "succeeded"
    assert result.json()["output"] == "## main"
    assert result.json()["payload"] == {}


def test_bridge_rejects_arbitrary_commands_and_unsafe_test_paths(tmp_path, monkeypatch):
    client, headers = bridge_client(tmp_path, monkeypatch)
    assert client.post("/api/termux-bridge/jobs", headers=headers, json={"action": "shell", "command": "rm -rf /"}).status_code == 422
    assert client.post(
        "/api/termux-bridge/jobs", headers=headers,
        json={"action": "run_tests", "test_path": "../../secret.py"},
    ).status_code == 400
    assert client.post(
        "/api/termux-bridge/jobs", headers=headers,
        json={"action": "git_status", "test_path": "tests/test_api.py"},
    ).status_code == 400


def test_bridge_requires_a_strong_configured_token(tmp_path, monkeypatch):
    client, _ = bridge_client(tmp_path, monkeypatch)
    monkeypatch.setenv("SINTU_BRIDGE_TOKEN", "short")
    response = client.get(
        "/api/termux-bridge/status",
        headers={"Authorization": "Bearer short"},
    )
    assert response.status_code == 503
