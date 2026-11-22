from app import main
from app import access_control


def test_production_factory_plan_endpoint_is_registered_and_feature_gated():
    route = next(
        route for route in main.app.routes
        if getattr(route, "path", None) == "/api/production-factory/plan"
    )
    assert "POST" in route.methods
    assert access_control.feature_for_path("/api/production-factory/plan") == "production"


def test_production_factory_plan_endpoint_returns_non_executing_plan():
    payload = main.ProductionFactoryPlanInput(topic="Hindi space explainer", format_id="educational")
    result = main.production_factory_plan(payload)
    assert result["topic"] == "Hindi space explainer"
    assert result["execution_started"] is False
    assert result["publishing_enabled"] is False
    assert len(result["stages"]) >= 10


def test_factory_run_api_delegates_to_persistent_worker(monkeypatch):
    from fastapi import BackgroundTasks

    payload = main.ProductionRunInput(topic="Hindi science explainer", format_id="educational")
    scheduled = {"run_id": "a" * 32, "status": "queued"}
    monkeypatch.setattr(main, "start_production_run", lambda p, tasks, request: scheduled)
    result = main.start_production_factory_run(payload, BackgroundTasks(), object())
    assert result["run_id"] == scheduled["run_id"]
    assert result["factory"]["execution_started"] is True
    assert result["factory"]["publishing_enabled"] is False
    assert result["factory"]["paid_auto_activation"] is False
    assert result["factory"]["stages"][-1]["id"] == "analytics"


def test_factory_runs_dashboard_is_owner_scoped_and_summarized(monkeypatch):
    monkeypatch.setattr(main, "_production_project_owner", lambda request: "owner-1")
    monkeypatch.setattr(main, "list_production_runs", lambda owner, limit: [
        {
            "id": "a" * 32,
            "owner_username": owner,
            "status": "completed",
            "format_id": "educational",
            "topic": "Hindi science",
            "current_role": None,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:01:00Z",
            "attempt_count": 1,
            "cancel_requested": 0,
            "result": {"script": "private script content"},
            "steps": [{"role": "writer"}],
        }
    ])
    result = main.production_factory_runs(object(), limit=10)
    assert result["summary"]["returned"] == 1
    assert result["summary"]["by_status"]["completed"] == 1
    assert result["runs"][0]["has_result"] is True
    assert "result" not in result["runs"][0]
    assert "script" not in str(result)
    assert result["publishing_enabled"] is False


def test_factory_runs_dashboard_rejects_unsafe_limit():
    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        main.production_factory_runs(object(), limit=101)
    assert exc.value.status_code == 400


def test_factory_runs_dashboard_route_is_feature_gated():
    route = next(
        route for route in main.app.routes
        if getattr(route, "path", None) == "/api/production-factory/runs"
        and "GET" in getattr(route, "methods", set())
    )
    assert "GET" in route.methods
    assert access_control.feature_for_path("/api/production-factory/runs") == "production"


def test_factory_health_reports_host_capabilities_without_secrets(monkeypatch):
    monkeypatch.setattr(main, "_production_project_owner", lambda request: "owner-1")
    monkeypatch.setattr(main, "provider_status", lambda: {
        "selected": "local",
        "paid_upgrades_allowed": False,
        "local": {"configured": True, "service_running": True, "model_available": True,
                  "backend": "ollama", "model": "qwen-local", "base_url": "http://127.0.0.1:11434"},
        "openai": {"configured": False, "model": "gpt-test"},
        "gemini": {"configured": False, "model": "gemini-test"},
        "deepseek": {"configured": False, "model": "deepseek-test"},
        "claude": {"configured": False, "model": "claude-test"},
    })
    monkeypatch.setattr(main, "image_status", lambda: {
        "available": True, "local_available": True, "local_engine": "Procedural",
        "comfyui_available": False, "local_workflow_configured": False,
    })
    monkeypatch.setattr(main, "voice_status", lambda: {
        "available": False, "local_available": False, "local_engine": "Not installed",
        "local_model_configured": False,
    })
    monkeypatch.setattr(main, "music_status", lambda: {
        "available": True, "local_available": True, "local_engine": "Procedural Composer",
    })
    monkeypatch.setattr(main, "video_status", lambda: {
        "available": False, "local_available": False, "local_engine": None,
        "local_workflow_configured": False,
    })
    result = main.production_factory_health(object())
    assert result["master_brain"]["local"]["model_available"] is True
    assert result["engines"]["image"]["local_available"] is True
    assert result["engines"]["voice"]["available"] is False
    assert result["policy"]["paid_auto_activation"] is False
    assert result["policy"]["publishing_enabled"] is False
    serialized = str(result)
    assert "base_url" not in serialized
    assert "api_key" not in serialized
    assert "secret" not in serialized.lower()


def test_factory_health_route_is_feature_gated():
    route = next(
        route for route in main.app.routes
        if getattr(route, "path", None) == "/api/production-factory/health"
    )
    assert "GET" in route.methods
    assert access_control.feature_for_path("/api/production-factory/health") == "production"


def test_factory_plan_rejects_unknown_production_format():
    import pytest
    from fastapi import HTTPException

    payload = main.ProductionFactoryPlanInput(topic="Hindi science", format_id="not-a-real-format")
    with pytest.raises(HTTPException) as exc:
        main.production_factory_plan(payload)
    assert exc.value.status_code == 400
