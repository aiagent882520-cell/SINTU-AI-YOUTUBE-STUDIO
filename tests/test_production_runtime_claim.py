from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import threading

from app import production_runtime as runtime


def seed_run(tmp_path, monkeypatch, owner="owner-a", status="queued"):
    monkeypatch.setattr(runtime, "DB_PATH", tmp_path / "production-runtime.sqlite3")
    runtime.init_runtime_db()
    run_id = "claim-test-run"
    now = runtime._now()
    with runtime._connect() as conn:
        conn.execute(
            """INSERT INTO production_runs(
                id,format_id,topic,status,current_role,result_json,error,owner_username,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (run_id, "youtube-shorts", "atomic claim test", status, None, None, None, owner, now, now),
        )
    return run_id


def test_production_run_claim_is_atomic_across_concurrent_workers(tmp_path, monkeypatch):
    run_id = seed_run(tmp_path, monkeypatch)
    barrier = threading.Barrier(8)

    def claim():
        barrier.wait(timeout=5)
        return runtime._claim_run(run_id, "owner-a")

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: claim(), range(8)))

    assert results.count(True) == 1
    assert results.count(False) == 7
    with runtime._connect() as conn:
        row = conn.execute(
            "SELECT status,owner_username FROM production_runs WHERE id=?", (run_id,)
        ).fetchone()
    assert row["status"] == "running"
    assert row["owner_username"] == "owner-a"


def test_production_run_claim_enforces_owner_scope(tmp_path, monkeypatch):
    run_id = seed_run(tmp_path, monkeypatch, owner="alice")

    assert runtime._claim_run(run_id, "bob") is False
    with runtime._connect() as conn:
        status = conn.execute(
            "SELECT status FROM production_runs WHERE id=?", (run_id,)
        ).fetchone()["status"]
    assert status == "queued"

    assert runtime._claim_run(run_id, "alice") is True
    assert runtime._claim_run(run_id, "alice") is False


def test_production_run_claim_rejects_missing_and_terminal_runs(tmp_path, monkeypatch):
    run_id = seed_run(tmp_path, monkeypatch, status="completed")
    assert runtime._claim_run("missing-run", "owner-a") is False
    assert runtime._claim_run(run_id, "owner-a") is False
