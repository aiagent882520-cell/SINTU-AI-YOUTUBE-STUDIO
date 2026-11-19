"""Interruptible subprocess registry for owner-authorized render cancellation.

The registry is process-local: it supports the current single-process API deployment,
not multi-worker or multi-host coordination.
"""
from __future__ import annotations

import subprocess
import threading
import time
from contextlib import contextmanager
from typing import Iterator

_lock = threading.RLock()
_active: dict[str, subprocess.Popen] = {}
_cancelled: set[str] = set()
_job = threading.local()


class RenderProcessCancelled(RuntimeError):
    """Raised when a render subprocess is stopped by an explicit cancel request."""


@contextmanager
def render_job(job_id: str) -> Iterator[None]:
    previous = getattr(_job, "job_id", None)
    _job.job_id = job_id
    try:
        with _lock:
            _cancelled.discard(job_id)
        yield
    finally:
        _job.job_id = previous
        with _lock:
            _cancelled.discard(job_id)
            _active.pop(job_id, None)


def cancel_render_process(job_id: str, grace_seconds: float = 2.0) -> bool:
    """Terminate only the active process for a currently registered render job."""
    with _lock:
        process = _active.get(job_id)
        if process is None:
            return False
        _cancelled.add(job_id)
        if process.poll() is None:
            process.terminate()
    try:
        process.wait(timeout=max(0.1, grace_seconds))
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    return True


def run_render_process(command, *, timeout: float, text: bool = True):
    """Run one FFmpeg stage with timeout and cooperative job cancellation."""
    job_id = getattr(_job, "job_id", None)
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=text,
    )
    if job_id:
        with _lock:
            if job_id in _cancelled:
                process.terminate()
            _active[job_id] = process
    deadline = time.monotonic() + timeout
    try:
        while process.poll() is None:
            with _lock:
                cancelled = bool(job_id and job_id in _cancelled)
            if cancelled:
                process.terminate()
                try:
                    stdout, stderr = process.communicate(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    stdout, stderr = process.communicate()
                raise RenderProcessCancelled("Render cancelled by user.")
            if time.monotonic() >= deadline:
                process.kill()
                stdout, stderr = process.communicate()
                raise subprocess.TimeoutExpired(command, timeout, output=stdout, stderr=stderr)
            time.sleep(0.05)
        stdout, stderr = process.communicate()
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    finally:
        if job_id:
            with _lock:
                if _active.get(job_id) is process:
                    _active.pop(job_id, None)
