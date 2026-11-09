from fastapi.testclient import TestClient

from app import main

def client_for_test(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "test.sqlite3")
    main.init_db()
    return TestClient(main.app)

def test_health_and_catalog(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/agents").json()["total"] == 61
    workflows = client.get("/api/workflows").json()
    assert workflows["total"] >= 8
    assert "shorts" in [item["id"] for item in workflows["workflows"]]

def test_generate_save_detail_and_export(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "generate_text", lambda prompt, workflow: {
        "provider": "test", "model": "test-model", "output": "Sample production script"
    })
    result = client.post("/api/generate", json={
        "prompt": "Make a Hindi mystery short", "workflow": "shorts"
    })
    assert result.status_code == 200
    body = result.json()
    assert body["status"] == "Completed"
    task = client.get(f"/api/tasks/{body['id']}")
    assert task.status_code == 200
    assert task.json()["output"] == "Sample production script"
    exported = client.get(f"/api/export/{body['id']}")
    assert exported.status_code == 200
    assert "Sample production script" in exported.text

def test_invalid_prompt_is_rejected(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    result = client.post("/api/generate", json={"prompt": "   ", "workflow": "shorts"})
    assert result.status_code == 400

def test_installable_app_shell(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    page = client.get("/")
    assert page.status_code == 200
    assert 'rel="manifest"' in page.text
    assert 'navigator.serviceWorker.register("/sw.js")' in page.text
    manifest = client.get("/static/manifest.json")
    assert manifest.status_code == 200
    assert manifest.json()["display"] == "standalone"
    worker = client.get("/sw.js")
    assert worker.status_code == 200
    assert worker.headers["Service-Worker-Allowed"] == "/"
    assert client.get("/static/icon.svg").status_code == 200

def test_agent_orchestration_catalog_and_teams(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    agents = client.get("/api/agents").json()
    assert agents["total"] == 61
    assert agents["orchestration"]["workflow_teams"] == 8
    assert agents["orchestration"]["independent_agents_running"] == 0
    team = client.get("/api/workflows/shorts/team")
    assert team.status_code == 200
    names = [role["name"] for role in team.json()["team"]]
    assert "Script Writer" in names
    assert "Fact Checker" in names
    assert client.get("/api/workflows/not-real/team").status_code == 404

def test_capabilities_never_expose_provider_secrets(tmp_path, monkeypatch):
    client = client_for_test(tmp_path, monkeypatch)
    response = client.get("/api/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert body["safety"]["public_actions_require_approval"] is True
    assert "OPENAI_API_KEY" not in str(body)
