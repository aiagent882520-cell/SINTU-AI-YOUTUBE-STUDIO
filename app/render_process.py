"""Interruptible, progress-aware subprocess registry for render jobs.

The registry is process-local and intended for a single API worker.
"""
from __future__ import annotations

import queue
import subprocess
import tempfile
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


def run_render_process(command, *, timeout: float, text: bool = True,
                       capture_output: bool = True, check: bool = False,
                       total_duration: float | None = None, progress_callback=None):
    """Run an FFmpeg stage, forwarding its real out_time progress when requested."""
    job_id = getattr(_job, "job_id", None)
    ffmpeg_command = list(command)
    report_progress = bool(progress_callback and total_duration and total_duration > 0)
    if report_progress and ffmpeg_command:
        ffmpeg_command[-1:-1] = ["-progress", "pipe:1", "-nostats"]

    stderr_file = tempfile.TemporaryFile(mode="w+t", encoding="utf-8") if capture_output else None
    process = subprocess.Popen(
        ffmpeg_command,
        stdout=subprocess.PIPE if (report_progress or capture_output) else subprocess.DEVNULL,
        stderr=stderr_file if stderr_file is not None else subprocess.DEVNULL,
        text=text,
        bufsize=1,
    )
    if job_id:
        with _lock:
            if job_id in _cancelled:
                process.terminate()
            _active[job_id] = process

    progress_queue = queue.Queue()
    reader = None
    if report_progress and process.stdout is not None:
        def read_progress():
            for line in process.stdout:
                progress_queue.put(line.strip())
        reader = threading.Thread(target=read_progress, daemon=True)
        reader.start()

    deadline = time.monotonic() + timeout
    try:
        while process.poll() is None:
            with _lock:
                cancelled = bool(job_id and job_id in _cancelled)
            if cancelled:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                if reader:
                    reader.join(timeout=1)
                raise RenderProcessCancelled("Render cancelled by user.")

            if report_progress:
                while True:
                    try:
                        line = progress_queue.get_nowait()
                    except queue.Empty:
                        break
                    if line.startswith("out_time_ms="):
                        try:
                            elapsed = int(line.split("=", 1)[1]) / 1_000_000
                            percent = min(99, max(0, int(elapsed * 100 / total_duration)))
                            progress_callback(percent)
                        except (ValueError, TypeError, ZeroDivisionError):
                            pass

            if time.monotonic() >= deadline:
                process.kill()
                process.wait()
                raise subprocess.TimeoutExpired(ffmpeg_command, timeout)
            time.sleep(0.05)

        if reader:
            reader.join(timeout=1)
        if report_progress:
            while True:
                try:
                    line = progress_queue.get_nowait()
                except queue.Empty:
                    break
                if line.startswith("out_time_ms="):
                    try:
                        elapsed = int(line.split("=", 1)[1]) / 1_000_000
                        progress_callback(min(99, max(0, int(elapsed * 100 / total_duration))))
                    except (ValueError, TypeError, ZeroDivisionError):
                        pass
        stdout = None
        if process.stdout is not None:
            if report_progress:
                stdout = ""
            else:
                stdout = process.stdout.read()
        stderr = ""
        if stderr_file is not None:
            stderr_file.seek(0)
            stderr = stderr_file.read()
        completed = subprocess.CompletedProcess(ffmpeg_command, process.returncode, stdout, stderr)
        if check and process.returncode:
            raise subprocess.CalledProcessError(process.returncode, ffmpeg_command, output=stdout, stderr=stderr)
        return completed
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        if stderr_file is not None:
            stderr_file.close()
        if process.stdout is not None:
            process.stdout.close()
        if job_id:
            with _lock:
                if _active.get(job_id) is process:
                    _active.pop(job_id, None)
