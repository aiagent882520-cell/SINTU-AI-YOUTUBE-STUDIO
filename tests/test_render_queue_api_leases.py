import pytest

from app import main, durable_render_queue


def test_render_queue_api_uses_durable_claim_and_completion(tmp_path, monkeypatch):
    monkeypatch.setenv("SINTU_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "sintu_studio.db")
    monkeypatch.setattr(main, "_studio_owner", lambda request: "owner")
    monkeypatch.setattr(main, "_studio_project_or_404", lambda project_id, request: {"id": project_id})
    monkeypatch.setattr(main, "render_video", lambda payload: {
        "video_id": "a" * 32, "filename": "a" * 32 + ".mp4", "duration_seconds": 4
    })
    project_id = "b" * 32
    created = main.studio_enqueue_render(
        main.StudioRenderInput(project_id=project_id, payload={"title": "lease integration", "scenes": ["fort at dawn"]}),
        object(),
    )
    item_id = created["item"]["id"]
    result = main.studio_execute_render_queue(item_id, object())
    assert result["item"]["status"] == "completed"
    assert result["render"]["video_id"] == "a" * 32
    persisted = durable_render_queue.get_item("owner", item_id)
    assert persisted["status"] == "completed"
    assert persisted["attempts"] == 1
    assert persisted["lease_token"] is None


def test_render_queue_api_failure_is_durable_and_retryable(tmp_path, monkeypatch):
    monkeypatch.setenv("SINTU_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "sintu_studio.db")
    monkeypatch.setattr(main, "_studio_owner", lambda request: "owner")
    monkeypatch.setattr(main, "_studio_project_or_404", lambda project_id, request: {"id": project_id})
    monkeypatch.setattr(main, "render_video", lambda payload: (_ for _ in ()).throw(RuntimeError("ffmpeg failed")))
    project_id = "c" * 32
    created = main.studio_enqueue_render(
        main.StudioRenderInput(project_id=project_id, payload={"title": "failure", "scenes": ["fort at night"]}),
        object(),
    )
    item_id = created["item"]["id"]
    try:
        main.studio_execute_render_queue(item_id, object())
    except main.HTTPException as exc:
        assert exc.status_code == 500
    else:
        raise AssertionError("render failure must propagate")
    persisted = durable_render_queue.get_item("owner", item_id)
    assert persisted["status"] == "queued"
    assert persisted["attempts"] == 1
    assert persisted["last_error"] == "RuntimeError"
    assert persisted["lease_token"] is None


def test_clients_cannot_forge_worker_completion_and_can_cancel_queued_jobs(tmp_path, monkeypatch):
    monkeypatch.setenv("SINTU_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "sintu_studio.db")
    monkeypatch.setattr(main, "_studio_owner", lambda request: "owner")
    item = durable_render_queue.enqueue("owner", "d" * 32, {"title": "cancel"})
    with pytest.raises(main.HTTPException) as blocked:
        main.studio_update_render_queue(
            item["id"], main.StudioRenderUpdateInput(status="completed", result={"video_id": "fake"}), object()
        )
    assert blocked.value.status_code == 409
    cancelled = main.studio_cancel_render_queue(item["id"], object())
    assert cancelled["cancelled"] is True
    assert cancelled["item"]["status"] == "cancelled"


def test_external_worker_respects_production_pause(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SINTU_DATA_DIR", str(tmp_path))
    from scripts import render_queue_worker
    monkeypatch.setattr(render_queue_worker, "production_actions_allowed", lambda: False)
    monkeypatch.setattr(durable_render_queue, "ensure_schema", lambda: None)
    monkeypatch.setattr(durable_render_queue, "recover_expired_leases", lambda: {"requeued": 0, "dead_lettered": 0})
    monkeypatch.setattr(durable_render_queue, "claim_next", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("paused worker must not claim")))
    assert render_queue_worker.run_worker(once=True) == 0
    output = capsys.readouterr().out
    assert "STARTED worker=" in output
    assert "PAUSED: rendering is disabled" in output
    assert "STOPPED worker=" in output


def test_render_queue_api_replays_idempotent_request_and_rejects_key_reuse(tmp_path, monkeypatch):
    monkeypatch.setenv("SINTU_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "sintu_studio.db")
    monkeypatch.setattr(main, "_studio_owner", lambda request: "owner")
    monkeypatch.setattr(main, "_studio_project_or_404", lambda project_id, request: {"id": project_id})
    payload = main.StudioRenderInput(project_id="e" * 32, payload={"title": "idempotent"})
    request = type("Request", (), {"headers": {"Idempotency-Key": "api-request-1"}})()
    first = main.studio_enqueue_render(payload, request)
    replay = main.studio_enqueue_render(payload, request)
    assert replay["item"]["id"] == first["item"]["id"]
    with pytest.raises(main.HTTPException) as conflict:
        main.studio_enqueue_render(
            main.StudioRenderInput(project_id="e" * 32, payload={"title": "different"}),
            request,
        )
    assert conflict.value.status_code == 409


def test_running_render_cancellation_endpoint_persists_intent(tmp_path, monkeypatch):
    monkeypatch.setenv("SINTU_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "sintu_studio.db")
    monkeypatch.setattr(main, "_studio_owner", lambda request: "owner")
    item = durable_render_queue.enqueue("owner", "f" * 32, {"title": "active-cancel-api"})
    claim = durable_render_queue.claim_next("worker", lease_seconds=60)
    response = main.studio_cancel_render_queue(item["id"], object())
    assert response["cancellation_requested"] is True
    assert durable_render_queue.cancellation_requested(item["id"], claim["lease_token"])
    assert durable_render_queue.get_item("owner", item["id"])["status"] == "running"
