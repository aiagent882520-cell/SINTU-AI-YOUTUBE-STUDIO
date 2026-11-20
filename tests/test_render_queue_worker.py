import signal

from scripts import render_queue_worker as worker


def _patch_worker_basics(monkeypatch):
    monkeypatch.setattr(worker.durable_render_queue, "ensure_schema", lambda: None)
    monkeypatch.setattr(worker.durable_render_queue, "recover_expired_leases", lambda: {"requeued": 0, "dead_lettered": 0})
    monkeypatch.setattr(worker.signal, "signal", lambda *_args: None)


def test_worker_does_not_claim_jobs_while_production_gate_is_closed(monkeypatch):
    _patch_worker_basics(monkeypatch)
    claims = []
    monkeypatch.setattr(worker, "production_actions_allowed", lambda: False)
    monkeypatch.setattr(worker.durable_render_queue, "claim_next",
                        lambda *args, **kwargs: claims.append((args, kwargs)))
    assert worker.run_worker(once=True, worker_id="paused-worker") == 0
    assert claims == []


def test_worker_claims_renders_and_persists_success(monkeypatch):
    _patch_worker_basics(monkeypatch)
    item = {"id": "job-1", "lease_token": "lease-1",
            "payload": {"title": "safe test"}}
    completed = []
    monkeypatch.setattr(worker, "production_actions_allowed", lambda: True)
    monkeypatch.setattr(worker.durable_render_queue, "claim_next", lambda *a, **k: item)
    monkeypatch.setattr(worker, "RenderInput", lambda **payload: payload)
    monkeypatch.setattr(worker, "render_video", lambda value: {"filename": "verified.mp4"})
    monkeypatch.setattr(worker.durable_render_queue, "complete",
                        lambda job_id, token, result: completed.append((job_id, token, result)) or True)
    monkeypatch.setattr(worker.durable_render_queue, "heartbeat", lambda *a, **k: True)
    assert worker.run_worker(once=True, lease_seconds=15, worker_id="active-worker") == 1
    assert completed == [("job-1", "lease-1", {"filename": "verified.mp4"})]


def test_worker_marks_render_failure_for_queue_retry(monkeypatch):
    _patch_worker_basics(monkeypatch)
    item = {"id": "job-fail", "lease_token": "lease-fail",
            "payload": {"title": "failing test"}}
    failures = []
    monkeypatch.setattr(worker, "production_actions_allowed", lambda: True)
    monkeypatch.setattr(worker.durable_render_queue, "claim_next", lambda *a, **k: item)
    monkeypatch.setattr(worker, "RenderInput", lambda **payload: payload)

    def fail_render(_value):
        raise RuntimeError("private error detail must not enter queue")

    monkeypatch.setattr(worker, "render_video", fail_render)
    monkeypatch.setattr(worker.durable_render_queue, "fail",
                        lambda job_id, token, error: failures.append((job_id, token, error)) or "queued")
    monkeypatch.setattr(worker.durable_render_queue, "heartbeat", lambda *a, **k: True)
    assert worker.run_worker(once=True, lease_seconds=15, worker_id="retry-worker") == 0
    assert failures == [("job-fail", "lease-fail", "RuntimeError")]
