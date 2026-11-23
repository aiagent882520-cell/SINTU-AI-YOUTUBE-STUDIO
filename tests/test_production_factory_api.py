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
    assert result["stage_execution_implemented"] is False
    assert result["stage_role_dispatch_integrated"] is True
    assert result["publishing_enabled"] is False
    assert len(result["stages"]) == 21
    assert result["pipeline_stage_count"] == 21
    assert result["pipeline_version"] == "2.0"


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
    assert result["factory"]["stages"][-1]["id"] == "learning"


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
            "result": {"script": "private script content", "video_rendered": True, "render": {"video_id": "b" * 32}},
            "steps": [{"role": "writer"}],
            "pipeline_stages": [
                {"stage_id": "intake", "status": "completed"},
                {"stage_id": "planning", "status": "pending"},
            ],
        }
    ])
    result = main.production_factory_runs(object(), limit=10)
    assert result["summary"]["returned"] == 1
    assert result["summary"]["by_status"]["completed"] == 1
    assert result["runs"][0]["has_result"] is True
    assert result["runs"][0]["has_render"] is True
    assert result["runs"][0]["pipeline_stage_count"] == 2
    assert result["runs"][0]["pipeline_stage_status"] == {"completed": 1, "pending": 1}
    assert result["runs"][0]["pipeline_stage_execution_implemented"] is False
    assert result["runs"][0]["pipeline_stage_role_dispatch_integrated"] is True
    assert result["runs"][0]["video_url"] == "/api/videos/" + "b" * 32
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
    monkeypatch.setattr(type(main.production_factory_supervisor), "is_running", property(lambda self: True))
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
    assert result["engines"]["image"]["comfyui_available"] is False
    assert result["engines"]["image"]["engine"] == "Procedural"
    assert result["engines"]["voice"]["available"] is False
    assert result["policy"]["paid_auto_activation"] is False
    assert result["policy"]["publishing_enabled"] is False
    assert result["background_worker"]["running"] is True
    assert result["background_worker"]["auto_pickup_status"] == "queued_only"
    assert result["background_worker"]["paused_runs_require_owner_review"] is True
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



def test_produce_media_requires_completed_owner_run(monkeypatch):
    import pytest
    from fastapi import HTTPException

    monkeypatch.setattr(main, "_production_project_owner", lambda request: "owner-1")
    monkeypatch.setattr(main, "get_production_run", lambda run_id, owner: {
        "id": run_id, "owner_username": owner, "status": "running", "result": None,
        "format_id": "educational", "topic": "Hindi science",
    })
    payload = main.ProductionMediaInput()
    with pytest.raises(HTTPException) as exc:
        main.produce_approved_run_media("a" * 32, payload, object())
    assert exc.value.status_code == 409


def test_factory_dashboard_exposes_confirmed_local_media_generation():
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "app" / "static" / "factory.js"
    source = script.read_text(encoding="utf-8")
    assert "/api/production/runs/" in source
    assert "/produce-media" in source
    assert "burn_subtitles:false" in source
    assert "window.confirm" in source


def test_produce_media_route_is_owner_feature_gated():
    route = next(
        route for route in main.app.routes
        if getattr(route, "path", None) == "/api/production/runs/{run_id}/produce-media"
    )
    assert "POST" in route.methods
    assert access_control.feature_for_path("/api/production/runs/" + "a" * 32 + "/produce-media") == "production"


def test_factory_runs_dashboard_rejects_unsafe_render_video_id(monkeypatch):
    monkeypatch.setattr(main, "_production_project_owner", lambda request: "owner-1")
    monkeypatch.setattr(main, "list_production_runs", lambda owner, limit: [{
        "id": "a" * 32, "status": "completed", "format_id": "educational",
        "topic": "Hindi science", "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:01:00Z", "attempt_count": 1,
        "cancel_requested": 0, "result": {
            "video_rendered": True, "render": {"video_id": "../private-file"}
        }, "steps": [],
    }])
    result = main.production_factory_runs(object(), limit=10)
    assert result["runs"][0]["has_render"] is False
    assert result["runs"][0]["video_url"] is None



def test_factory_health_dashboard_distinguishes_local_from_remote_engines():
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "app" / "static" / "factory.js"
    source = script.read_text(encoding="utf-8")
    assert "item.local_available" in source
    assert 'item.comfyui_available?"LOCAL AI READY"' in source
    assert '"PROCEDURAL FALLBACK ONLY"' in source
    assert 'localReady?"LOCAL READY":"NOT READY"' in source
    assert "optional remote provider configured, not used for free local rendering" in source
    assert "Remote provider configuration does not count as local readiness" in source


def test_factory_run_details_show_the_persisted_pipeline_ledger():
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "app" / "static" / "factory.js"
    source = script.read_text(encoding="utf-8")
    assert "21-stage pipeline ledger" in source
    assert "run.pipeline_stages||[]" in source
    assert "records Owner Review approval" in source
    assert "Deferred side-effect roles" in source
    assert "deferred_worker_roles" in source
    assert "no actual render, package, upload, scheduling or analytics action is performed" in source


def test_factory_dashboard_labels_the_live_stage_count():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app" / "static"
    html = (root / "factory.html").read_text(encoding="utf-8")
    script = (root / "factory.js").read_text(encoding="utf-8")
    assert "Build 21-stage plan" in html
    assert "plan.pipeline_stage_count" in script
    assert "11-stage factory plan" not in script

def test_produce_media_requires_owner_review_and_rejects_blocked_package(monkeypatch):
    import pytest
    from fastapi import HTTPException

    monkeypatch.setattr(main, "_production_project_owner", lambda request: "owner-1")
    monkeypatch.setattr(main, "get_production_run", lambda run_id, owner: {
        "id": run_id, "owner_username": owner, "status": "completed",
        "result": {"deliverables": {}}, "format_id": "educational", "topic": "Hindi science",
        "pipeline_stages": [{"stage_id": "owner_review", "status": "blocked"}],
    })
    payload = main.ProductionMediaInput()
    with pytest.raises(HTTPException) as exc:
        main.produce_approved_run_media("a" * 32, payload, object())
    assert exc.value.status_code == 409
    assert "Owner Review is blocked" in exc.value.detail


def test_authenticated_media_request_completes_owner_review_gate(monkeypatch):
    import pytest
    from fastapi import HTTPException

    calls = []
    monkeypatch.setattr(main, "_production_project_owner", lambda request: "owner-1")
    monkeypatch.setattr(main, "get_production_run", lambda run_id, owner: {
        "id": run_id, "owner_username": owner, "status": "completed",
        "result": {"deliverables": {}}, "format_id": "educational", "topic": "Hindi science",
        "pipeline_stages": [{"stage_id": "owner_review", "status": "awaiting_owner"}],
    })
    monkeypatch.setattr(main, "transition_pipeline_stage", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(main, "image_status", lambda: {"local_available": True})
    monkeypatch.setattr(main, "voice_status", lambda: {"local_available": True})
    def reject_render_start(*args, **kwargs):
        raise ValueError("render executor fixture stop")
    monkeypatch.setattr(main, "transition_owner_media_stage", reject_render_start)
    payload = main.ProductionMediaInput(
        scene_prompts=["A detailed cinematic scene with a clear subject, setting, lighting and camera composition."],
        narration="यह एक परीक्षण कथन है।",
    )
    with pytest.raises(HTTPException) as exc:
        main.produce_approved_run_media("a" * 32, payload, object())
    assert exc.value.status_code == 409
    assert len(calls) == 1
    assert calls[0][0][2] == "completed"
    assert calls[0][1]["owner_username"] == "owner-1"
    assert calls[0][1]["owner_approved"] is True
    assert "explicitly initiated" in calls[0][1]["evidence"]

def test_general_renderer_cannot_bypass_blocked_owner_review(monkeypatch):
    import pytest
    from fastapi import HTTPException

    monkeypatch.setattr(main, "_production_project_owner", lambda request: "owner-1")
    monkeypatch.setattr(main, "get_production_run", lambda run_id, owner: {
        "id": run_id, "owner_username": owner, "status": "completed",
        "result": {"deliverables": {}}, "format_id": "educational", "topic": "Hindi science",
        "pipeline_stages": [
            {"stage_id": "owner_review", "status": "blocked"},
            {"stage_id": "render", "status": "pending"},
        ],
    })
    payload = main.ProductionRenderInput(
        format_id="educational", title="Hindi science", scenes=["A scene"],
        image_ids=["b" * 32],
    )
    with pytest.raises(HTTPException) as exc:
        main.render_approved_production_run("a" * 32, payload, object())
    assert exc.value.status_code == 409
    assert "Owner Review is blocked" in exc.value.detail




def test_delivery_package_download_is_owner_scoped_and_hash_verified(tmp_path, monkeypatch):
    import hashlib
    from fastapi import HTTPException
    import pytest

    run_id = "c" * 32
    package_path = tmp_path / "production_packages" / f"{run_id}-delivery.zip"
    package_path.parent.mkdir(parents=True)
    package_bytes = b"verified-owner-delivery-zip"
    package_path.write_bytes(package_bytes)
    package = {
        "verified": True,
        "path": f"production_packages/{run_id}-delivery.zip",
        "size_bytes": len(package_bytes),
        "sha256": hashlib.sha256(package_bytes).hexdigest(),
    }
    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main, "_production_project_owner", lambda request: "owner-1")
    monkeypatch.setattr(main, "get_production_run", lambda requested_id, owner: {
        "id": requested_id, "owner_username": owner,
        "result": {"render": {"delivery_package": package}},
    })
    response = main.download_production_delivery_package(run_id, object())
    from pathlib import Path
    assert Path(response.path).resolve() == package_path.resolve()
    assert response.filename == f"SINTU-{run_id}-delivery.zip"

    package_path.write_bytes(b"tampered-zip")
    with pytest.raises(HTTPException) as exc:
        main.download_production_delivery_package(run_id, object())
    assert exc.value.status_code == 409


def test_delivery_package_download_rejects_missing_owner_run(monkeypatch):
    import pytest
    from fastapi import HTTPException

    run_id = "d" * 32
    monkeypatch.setattr(main, "_production_project_owner", lambda request: "owner-1")
    monkeypatch.setattr(main, "get_production_run", lambda requested_id, owner: None)
    with pytest.raises(HTTPException) as exc:
        main.download_production_delivery_package(run_id, object())
    assert exc.value.status_code == 404


def test_delivery_package_download_route_is_feature_gated():
    run_id = "e" * 32
    route = next(
        route for route in main.app.routes
        if getattr(route, "path", None) == "/api/production/runs/{run_id}/package"
    )
    assert "GET" in route.methods
    assert access_control.feature_for_path(f"/api/production/runs/{run_id}/package") == "production"


def test_factory_dashboard_exposes_verified_delivery_package_download():
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "app" / "static" / "factory.js"
    source = script.read_text(encoding="utf-8")
    assert "Download verified production ZIP" in source
    assert "delivery_package_url" in source
    assert "Download Owner-only production ZIP" in source
    assert 'Thumbnail: "+(packageInfo.thumbnail_included?"included":"not generated")' in source
    assert 'Translations: "+(packageInfo.translations_included?"included":"not generated")' in source


def test_local_media_route_builds_package_before_completing_package_stage():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    assert "create_delivery_package(" in source
    assert "create_video_frame_thumbnail(render_output_path, run_id)" in source
    assert "asset_paths=[*image_paths, audio_path, music_matches[0], thumbnail_path]" in source
    assert "captions=caption_lines" in source
    assert "delivery_package['sha256']" in source
    assert '"/api/production/runs/{run_id}/package"' in source
