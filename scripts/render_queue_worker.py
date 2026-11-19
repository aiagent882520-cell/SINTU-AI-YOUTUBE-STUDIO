#!/usr/bin/env python3
"""Run durable SINTU render jobs in a separately supervised process.

Run from repository root:
  python -m scripts.render_queue_worker
  python -m scripts.render_queue_worker --once
"""
from __future__ import annotations

import argparse
import os
import signal
import threading
import time
import uuid

from app import durable_render_queue
from app.main import RenderInput, render_video


def run_worker(*, once: bool = False, poll_seconds: float = 2.0,
               lease_seconds: int = 1800, worker_id: str | None = None) -> int:
    worker_id = worker_id or f"render-worker-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    stopping = threading.Event()

    def stop(_signum, _frame):
        stopping.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    durable_render_queue.ensure_schema()
    durable_render_queue.recover_expired_leases()
    processed = 0
    while not stopping.is_set():
        item = durable_render_queue.claim_next(worker_id, lease_seconds=lease_seconds)
        if item is None:
            if once:
                break
            stopping.wait(poll_seconds)
            continue

        lease_token = item["lease_token"]
        lease_lost = threading.Event()

        def renew():
            while not stopping.wait(min(30, max(5, lease_seconds // 3))):
                if not durable_render_queue.heartbeat(item["id"], lease_token, lease_seconds=lease_seconds):
                    lease_lost.set()
                    return

        heartbeat = threading.Thread(target=renew, name="render-lease-heartbeat", daemon=True)
        heartbeat.start()
        try:
            result = render_video(RenderInput(**item["payload"]))
            if lease_lost.is_set() or not durable_render_queue.complete(item["id"], lease_token, result):
                print(f"STALE_OUTPUT_DISCARDED job={item['id']} worker={worker_id}", flush=True)
            else:
                processed += 1
                print(f"COMPLETED job={item['id']} worker={worker_id}", flush=True)
        except Exception as exc:
            status = durable_render_queue.fail(item["id"], lease_token, type(exc).__name__)
            print(f"FAILED job={item['id']} retry_state={status or 'lease-lost'} error={type(exc).__name__}", flush=True)
        finally:
            # Do not interrupt an active FFmpeg render on graceful shutdown; it
            # finishes or its lease expires and another worker recovers it.
            stopping.clear() if stopping.is_set() else None
            heartbeat.join(timeout=2)
        if once:
            break
    return processed


def main():
    parser = argparse.ArgumentParser(description="SINTU durable render queue worker")
    parser.add_argument("--once", action="store_true", help="claim at most one job and exit")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--lease-seconds", type=int, default=1800)
    parser.add_argument("--worker-id", default=None)
    args = parser.parse_args()
    if not 0.1 <= args.poll_seconds <= 60:
        parser.error("--poll-seconds must be between 0.1 and 60")
    if not 15 <= args.lease_seconds <= 86400:
        parser.error("--lease-seconds must be between 15 and 86400")
    run_worker(once=args.once, poll_seconds=args.poll_seconds,
               lease_seconds=args.lease_seconds, worker_id=args.worker_id)


if __name__ == "__main__":
    main()
