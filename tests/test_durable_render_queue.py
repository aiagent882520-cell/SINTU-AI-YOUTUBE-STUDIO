from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest

from app import durable_render_queue as queue


def test_atomic_claim_allows_only_one_concurrent_worker(tmp_path, monkeypatch):
    monkeypatch.setenv("SINTU_DATA_DIR", str(tmp_path))
    item = queue.enqueue("owner", "project", {"title": "test"})
    barrier = Barrier(2)

    def claim(worker):
        barrier.wait(timeout=5)
        return queue.claim_next(worker, lease_seconds=60, owner="owner")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ["worker-a", "worker-b"]))
    claimed = [result for result in results if result is not None]
    assert len(claimed) == 1
    assert claimed[0]["id"] == item["id"]
    assert claimed[0]["attempts"] == 1


def test_expired_lease_is_recovered_after_worker_crash(tmp_path, monkeypatch):
    monkeypatch.setenv("SINTU_DATA_DIR", str(tmp_path))
    item = queue.enqueue("owner", "project", {"title": "crash"})
    claim = queue.claim_next("worker-before-crash", lease_seconds=60)
    expired = datetime.now(timezone.utc) + timedelta(seconds=61)
    report = queue.recover_expired_leases(now=expired)
    assert report == {"requeued": 1, "dead_lettered": 0}
    assert queue.get_item("owner", item["id"])["status"] == "queued"
    second = queue.claim_next("worker-after-restart", lease_seconds=60, now=expired)
    assert second["id"] == item["id"]
    assert second["attempts"] == 2
    assert second["lease_token"] != claim["lease_token"]


def test_stale_worker_is_fenced_from_heartbeat_and_completion(tmp_path, monkeypatch):
    monkeypatch.setenv("SINTU_DATA_DIR", str(tmp_path))
    item = queue.enqueue("owner", "project", {"title": "fencing"})
    first = queue.claim_next("worker-a", lease_seconds=60)
    queue.recover_expired_leases(now=datetime.now(timezone.utc) + timedelta(seconds=61))
    second = queue.claim_next("worker-b", lease_seconds=60, now=datetime.now(timezone.utc) + timedelta(seconds=61))
    assert second["id"] == item["id"]
    assert queue.heartbeat(item["id"], first["lease_token"]) is False
    assert queue.complete(item["id"], first["lease_token"], {"video_id": "stale"}) is False
    assert queue.complete(item["id"], second["lease_token"], {"video_id": "fresh"}) is True
    assert queue.get_item("owner", item["id"])["result"] == {"video_id": "fresh"}


def test_retry_uses_exponential_backoff_then_dead_letters(tmp_path, monkeypatch):
    monkeypatch.setenv("SINTU_DATA_DIR", str(tmp_path))
    item = queue.enqueue("owner", "project", {"title": "retry"}, max_attempts=2)
    first = queue.claim_next("worker-a", lease_seconds=60)
    assert queue.fail(item["id"], first["lease_token"], "transient", retry_base_seconds=60) == "queued"
    assert queue.claim_next("worker-b", lease_seconds=60) is None
    with queue._connect() as conn:
        conn.execute("UPDATE studio_render_queue SET available_at=? WHERE id=?", ("2000-01-01T00:00:00+00:00", item["id"]))
    second = queue.claim_next("worker-b", lease_seconds=60)
    assert second["attempts"] == 2
    assert queue.fail(item["id"], second["lease_token"], "permanent", retry_base_seconds=60) == "dead_letter"
    assert queue.claim_next("worker-c", lease_seconds=60) is None


def test_owner_scope_and_invalid_worker_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("SINTU_DATA_DIR", str(tmp_path))
    item = queue.enqueue("owner", "project", {"title": "private"})
    assert queue.claim_item("other", item["id"], "worker") is None
    with pytest.raises(ValueError):
        queue.claim_next("", lease_seconds=60)
    with pytest.raises(ValueError):
        queue.claim_next("worker", lease_seconds=1)


def test_schema_migrates_existing_studio_queue_without_losing_rows(tmp_path, monkeypatch):
    import sqlite3
    monkeypatch.setenv("SINTU_DATA_DIR", str(tmp_path))
    path = tmp_path / "sintu_studio.db"
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE studio_render_queue (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL, project_id TEXT NOT NULL,
            status TEXT NOT NULL, payload_json TEXT NOT NULL, result_json TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")
        conn.execute(
            "INSERT INTO studio_render_queue VALUES(?,?,?,?,?,?,?,?)",
            ("legacy-id", "owner", "project", "queued", '{"title":"legacy"}', None, "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
    queue.ensure_schema()
    columns = {row["name"] for row in queue._connect().execute("PRAGMA table_info(studio_render_queue)")}
    assert {"lease_owner", "lease_token", "lease_expires_at", "heartbeat_at", "available_at", "attempts", "max_attempts", "last_error", "idempotency_key", "cancel_requested"} <= columns
    claimed = queue.claim_next("migration-worker", lease_seconds=60)
    assert claimed["id"] == "legacy-id"
    assert claimed["payload"] == {"title": "legacy"}


def test_expired_lease_at_retry_limit_moves_to_dead_letter(tmp_path, monkeypatch):
    monkeypatch.setenv("SINTU_DATA_DIR", str(tmp_path))
    item = queue.enqueue("owner", "project", {"title": "exhausted"}, max_attempts=1)
    queue.claim_next("worker-crash", lease_seconds=60)
    expired = datetime.now(timezone.utc) + timedelta(seconds=61)
    assert queue.recover_expired_leases(now=expired) == {"requeued": 0, "dead_lettered": 1}
    assert queue.get_item("owner", item["id"])["status"] == "dead_letter"


def _process_claim(db_dir, worker_id, barrier, sender):
    import os
    os.environ["SINTU_DATA_DIR"] = str(db_dir)
    from app import durable_render_queue
    barrier.wait(timeout=10)
    item = durable_render_queue.claim_next(worker_id, lease_seconds=60)
    sender.send(item["id"] if item else None)
    sender.close()


def _claim_then_crash(db_dir, sender):
    import os
    os.environ["SINTU_DATA_DIR"] = str(db_dir)
    from app import durable_render_queue
    item = durable_render_queue.claim_next("worker-that-crashes", lease_seconds=15)
    sender.send(item["lease_token"] if item else "")
    sender.close()
    os._exit(0)


def test_atomic_claim_is_safe_across_separate_worker_processes(tmp_path, monkeypatch):
    import multiprocessing
    monkeypatch.setenv("SINTU_DATA_DIR", str(tmp_path))
    item = queue.enqueue("owner", "project", {"title": "multi-process"})
    context = multiprocessing.get_context("fork")
    barrier = context.Barrier(2)
    receivers = []
    processes = []
    for worker_id in ("process-a", "process-b"):
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=_process_claim, args=(tmp_path, worker_id, barrier, sender))
        process.start()
        sender.close()
        receivers.append(receiver)
        processes.append(process)
    results = [receiver.recv() for receiver in receivers]
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0
    assert results.count(item["id"]) == 1
    assert results.count(None) == 1


def test_actual_worker_process_exit_recovers_after_lease_expiry(tmp_path, monkeypatch):
    import multiprocessing
    monkeypatch.setenv("SINTU_DATA_DIR", str(tmp_path))
    item = queue.enqueue("owner", "project", {"title": "process-crash"})
    context = multiprocessing.get_context("fork")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_claim_then_crash, args=(tmp_path, sender))
    process.start()
    sender.close()
    old_token = receiver.recv()
    process.join(timeout=10)
    assert process.exitcode == 0
    assert old_token
    expired = datetime.now(timezone.utc) + timedelta(seconds=16)
    assert queue.recover_expired_leases(now=expired) == {"requeued": 1, "dead_lettered": 0}
    replacement = queue.claim_next("replacement-after-crash", lease_seconds=60, now=expired)
    assert replacement["id"] == item["id"]
    assert replacement["lease_token"] != old_token


def test_idempotency_key_returns_existing_job_without_duplicate(tmp_path, monkeypatch):
    monkeypatch.setenv("SINTU_DATA_DIR", str(tmp_path))
    first = queue.enqueue("owner", "project", {"title": "same"}, idempotency_key="request-123")
    replay = queue.enqueue("owner", "project", {"title": "same"}, idempotency_key="request-123")
    assert replay["id"] == first["id"]
    assert replay["idempotency_key"] == "request-123"
    assert queue.claim_next("worker", lease_seconds=60)["id"] == first["id"]
    assert queue.claim_next("worker", lease_seconds=60) is None


def test_idempotency_key_rejects_different_payload_or_project(tmp_path, monkeypatch):
    monkeypatch.setenv("SINTU_DATA_DIR", str(tmp_path))
    queue.enqueue("owner", "project-a", {"title": "original"}, idempotency_key="request-456")
    with pytest.raises(ValueError, match="different render request"):
        queue.enqueue("owner", "project-a", {"title": "changed"}, idempotency_key="request-456")
    with pytest.raises(ValueError, match="different render request"):
        queue.enqueue("owner", "project-b", {"title": "original"}, idempotency_key="request-456")


def test_idempotency_keys_are_scoped_to_owner_and_validate_length(tmp_path, monkeypatch):
    monkeypatch.setenv("SINTU_DATA_DIR", str(tmp_path))
    first = queue.enqueue("owner-a", "project", {"title": "same"}, idempotency_key="shared-key")
    second = queue.enqueue("owner-b", "project", {"title": "same"}, idempotency_key="shared-key")
    assert first["id"] != second["id"]
    with pytest.raises(ValueError, match="1-200"):
        queue.enqueue("owner-a", "project", {"title": "bad"}, idempotency_key="x" * 201)


def test_running_job_cancellation_is_owner_scoped_and_lease_fenced(tmp_path, monkeypatch):
    monkeypatch.setenv("SINTU_DATA_DIR", str(tmp_path))
    item = queue.enqueue("owner-a", "project", {"title": "active"})
    claim = queue.claim_next("worker", lease_seconds=60)
    assert queue.request_cancel("owner-b", item["id"]) is None
    requested = queue.request_cancel("owner-a", item["id"])
    assert requested["status"] == "running"
    assert requested["cancel_requested"] == 1
    assert queue.cancellation_requested(item["id"], claim["lease_token"])
    assert queue.finalize_cancelled(item["id"], "stale-token") is False
    assert queue.finalize_cancelled(item["id"], claim["lease_token"]) is True
    persisted = queue.get_item("owner-a", item["id"])
    assert persisted["status"] == "cancelled"
    assert persisted["lease_token"] is None
    assert persisted["lease_expires_at"] is None
    assert persisted["cancel_requested"] == 0


def test_cancelled_running_job_recovers_as_cancelled_after_worker_crash(tmp_path, monkeypatch):
    monkeypatch.setenv("SINTU_DATA_DIR", str(tmp_path))
    item = queue.enqueue("owner", "project", {"title": "cancel-crash"})
    claim = queue.claim_next("worker", lease_seconds=15)
    queue.request_cancel("owner", item["id"])
    expired = datetime.now(timezone.utc) + timedelta(seconds=16)
    queue.recover_expired_leases(now=expired)
    persisted = queue.get_item("owner", item["id"])
    assert persisted["status"] == "cancelled"
    assert persisted["lease_token"] is None
    assert persisted["cancel_requested"] == 0


def test_cancellation_intent_fences_completion_and_retry(tmp_path, monkeypatch):
    monkeypatch.setenv("SINTU_DATA_DIR", str(tmp_path))
    item = queue.enqueue("owner", "project", {"title": "cancel-race"}, max_attempts=3)
    claim = queue.claim_next("worker", lease_seconds=60)
    queue.request_cancel("owner", item["id"])
    assert queue.complete(item["id"], claim["lease_token"], {"filename": "must-not-publish.mp4"}) is False
    assert queue.fail(item["id"], claim["lease_token"], "renderer stopped") == "cancelled"
    persisted = queue.get_item("owner", item["id"])
    assert persisted["status"] == "cancelled"
    assert persisted["result"] is None
    assert persisted["lease_token"] is None
    assert persisted["attempts"] == 1


def test_concurrent_cancel_and_completion_have_one_durable_winner(tmp_path, monkeypatch):
    import threading

    monkeypatch.setenv("SINTU_DATA_DIR", str(tmp_path))
    item = queue.enqueue("owner", "project", {"title": "cancel-complete-race"})
    claim = queue.claim_next("worker", lease_seconds=60)
    barrier = threading.Barrier(3)
    outcomes = {}

    def cancel():
        barrier.wait()
        outcomes["cancel"] = queue.request_cancel("owner", item["id"])

    def complete():
        barrier.wait()
        outcomes["complete"] = queue.complete(
            item["id"], claim["lease_token"], {"filename": "race-result.mp4"}
        )

    threads = [threading.Thread(target=cancel), threading.Thread(target=complete)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(5)
        assert not thread.is_alive()

    persisted = queue.get_item("owner", item["id"])
    if persisted["status"] == "running" and persisted["cancel_requested"]:
        assert queue.finalize_cancelled(item["id"], claim["lease_token"])
        persisted = queue.get_item("owner", item["id"])
    assert persisted["status"] in {"completed", "cancelled"}
    assert persisted["cancel_requested"] == 0
    if persisted["status"] == "completed":
        assert persisted["result"] == {"filename": "race-result.mp4"}
        assert persisted["lease_token"] is None
    else:
        assert persisted["result"] is None
        assert persisted["lease_token"] is None
