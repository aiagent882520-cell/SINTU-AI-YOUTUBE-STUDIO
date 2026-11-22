"""Durable in-process supervisor for queued production runs.

Only status='queued' is eligible for automatic pickup. Paused runs are deliberately
excluded because they represent failed independent checks, missing documentary
evidence, or an explicit human-review checkpoint.
"""
from __future__ import annotations

import logging
import threading
from typing import Callable

from .production_runtime import execute_run, list_queued_runs

logger = logging.getLogger(__name__)


class ProductionRunSupervisor:
    def __init__(
        self,
        *,
        poll_interval: float = 5.0,
        batch_size: int = 5,
        queued_reader: Callable[..., list[dict[str, str]]] = list_queued_runs,
        run_executor: Callable[[str, str], None] = execute_run,
    ) -> None:
        self.poll_interval = max(0.25, float(poll_interval))
        self.batch_size = max(1, min(int(batch_size), 50))
        self._queued_reader = queued_reader
        self._run_executor = run_executor
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        """Whether the background supervisor thread is currently alive."""
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        """Start one daemon worker loop; repeated startup calls are harmless."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="sintu-production-run-supervisor",
                daemon=True,
            )
            self._thread.start()
            return True

    def stop(self, timeout: float = 2.0) -> None:
        """Stop queue polling without forcibly interrupting an active model call."""
        self._stop_event.set()
        with self._lock:
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(max(0.0, float(timeout)))
        with self._lock:
            if self._thread is thread and (thread is None or not thread.is_alive()):
                self._thread = None

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                queued = self._queued_reader(limit=self.batch_size)
                for run in queued:
                    if self._stop_event.is_set():
                        break
                    run_id = str(run.get("id") or "")
                    owner = str(run.get("owner_username") or "")
                    if not run_id or not owner:
                        logger.error("Skipping malformed queued production run record.")
                        continue
                    try:
                        # Runtime's atomic fenced claim prevents duplicate execution when
                        # FastAPI BackgroundTasks or another process races this supervisor.
                        self._run_executor(run_id, owner)
                    except Exception:
                        logger.exception("Production run supervisor caught an unexpected worker error.")
            except Exception:
                logger.exception("Production run supervisor could not inspect its queue.")
            self._stop_event.wait(self.poll_interval)


supervisor = ProductionRunSupervisor()
