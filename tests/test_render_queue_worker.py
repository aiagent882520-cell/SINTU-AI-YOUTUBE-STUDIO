import signal
import threading

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


def test_worker_cancels_real_active_subprocess_and_releases_lease(tmp_path, monkeypatch):
    import shutil
    import tempfile
    import time
    from pathlib import Path
    from app import durable_render_queue, render_process

    monkeypatch.setenv("SINTU_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(worker.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(worker, "production_actions_allowed", lambda: True)
    monkeypatch.setattr(worker, "RenderInput", lambda **payload: payload)
    durable_render_queue.ensure_schema()
    item = durable_render_queue.enqueue("owner", "project", {"title": "active-cancel"})
    started = threading.Event()

    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg, "FFmpeg must be installed in the automation integration-test environment"
    temporary_root = tmp_path / "render-temporaries"
    temporary_root.mkdir()

    def actual_subprocess_render(_payload):
        with tempfile.TemporaryDirectory(prefix="active-cancel-", dir=temporary_root) as work:
            output = Path(work) / "partial.mp4"
            started.set()
            result = render_process.run_render_process(
                [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-re",
                 "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30",
                 "-t", "30", "-an", "-c:v", "libx264", "-preset", "ultrafast",
                 "-pix_fmt", "yuv420p", str(output)],
                timeout=35, capture_output=True, text=True, check=False,
            )
            return {"returncode": result.returncode}

    monkeypatch.setattr(worker, "render_video", actual_subprocess_render)
    result = []
    thread = threading.Thread(
        target=lambda: result.append(worker.run_worker(once=True, lease_seconds=60, worker_id="cancel-worker")),
        daemon=True,
    )
    thread.start()
    assert started.wait(5)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with render_process._lock:
            if item["id"] in render_process._active:
                break
        time.sleep(0.02)
    else:
        raise AssertionError("render subprocess was not registered")
    requested = durable_render_queue.request_cancel("owner", item["id"])
    assert requested["cancel_requested"] == 1
    thread.join(8)
    assert not thread.is_alive(), "worker did not stop after active render cancellation"
    persisted = durable_render_queue.get_item("owner", item["id"])
    assert persisted["status"] == "cancelled"
    assert persisted["lease_token"] is None
    assert persisted["lease_expires_at"] is None
    assert persisted["cancel_requested"] == 0
    with render_process._lock:
        assert item["id"] not in render_process._active
    assert result == [0]
    assert list(temporary_root.iterdir()) == [], "cancelled render temporary directory leaked"
