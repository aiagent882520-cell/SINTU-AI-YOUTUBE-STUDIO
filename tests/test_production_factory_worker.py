from __future__ import annotations

import threading

from app.production_factory_worker import ProductionRunSupervisor


def test_supervisor_claims_queued_runs_and_starts_once():
    finished = threading.Event()
    reads = {"count": 0}
    executed = []

    def read_queue(*, limit):
        reads["count"] += 1
        if reads["count"] == 1:
            return [{"id": "a" * 32, "owner_username": "owner-1"}]
        return []

    def execute(run_id, owner):
        executed.append((run_id, owner))
        finished.set()

    worker = ProductionRunSupervisor(
        poll_interval=0.01,
        batch_size=2,
        queued_reader=read_queue,
        run_executor=execute,
    )
    assert worker.start() is True
    assert worker.start() is False
    assert finished.wait(2)
    worker.stop()
    assert executed == [("a" * 32, "owner-1")]


def test_supervisor_stop_is_safe_when_never_started():
    worker = ProductionRunSupervisor(poll_interval=0.01)
    worker.stop()
    assert worker.start() is True
    worker.stop()
    worker.stop()
