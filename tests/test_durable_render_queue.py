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
