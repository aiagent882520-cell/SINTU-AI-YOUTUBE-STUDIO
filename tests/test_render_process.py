import subprocess
import threading
import time

import pytest

from app import render_process


def test_render_process_returns_completed_process_without_job():
    result = render_process.run_render_process(
        ["python", "-c", "print('ok')"], timeout=3
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "ok"


def test_render_process_can_be_cancelled_from_another_thread():
    started = threading.Event()
    outcome = []

    def run():
        try:
            with render_process.render_job("job-1"):
                started.set()
                render_process.run_render_process(
                    ["python", "-c", "import time; time.sleep(30)"], timeout=35
                )
        except Exception as exc:
            outcome.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    assert started.wait(2)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        with render_process._lock:
            if "job-1" in render_process._active:
                break
        time.sleep(0.02)
    assert render_process.cancel_render_process("job-1", grace_seconds=1)
    worker.join(3)
    assert not worker.is_alive()
    assert len(outcome) == 1
    assert isinstance(outcome[0], render_process.RenderProcessCancelled)


def test_cancel_unknown_or_finished_job_is_noop():
    assert render_process.cancel_render_process("missing-job") is False
