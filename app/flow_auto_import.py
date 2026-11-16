"""Automatic Google Flow MP4 pickup for Termux/Android Downloads.

Only completed, stable, regular .mp4 files are copied into SINTU. Source files
are never moved or deleted. Every imported file is validated with FFprobe.
"""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

from .video_renderer import verify_publishable_mp4, RendererUnavailable, RenderFailed

MAX_BYTES = 512 * 1024 * 1024
_POLL_SECONDS = 5.0
_worker: "FlowAutoImporter | None" = None


def default_download_dirs() -> list[Path]:
    configured = os.getenv("SINTU_FLOW_DOWNLOAD_DIRS", "").strip()
    if configured:
        return [Path(item).expanduser() for item in configured.split(os.pathsep) if item.strip()]
    home = Path.home()
    return [
        home / "storage" / "shared" / "Download",
        home / "storage" / "shared" / "Downloads",
        home / "storage" / "downloads",
    ]


class FlowAutoImporter:
    def __init__(self, data_dir: Path, video_dir: Path,
                 source_dirs: list[Path] | None = None,
                 validator: Callable = verify_publishable_mp4):
        self.data_dir = Path(data_dir)
        self.video_dir = Path(video_dir)
        self.source_dirs = source_dirs if source_dirs is not None else default_download_dirs()
        self.validator = validator
        self.ledger_path = self.data_dir / "flow_auto_imported.json"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._seen: dict[str, tuple[int, int]] = {}
        self._lock = threading.Lock()
        self.imported = 0
        self.skipped = 0
        self.last_error = ""
        self.last_import = ""

    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return False
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.video_dir.mkdir(parents=True, exist_ok=True)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="sintu-flow-auto-import", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def status(self) -> dict:
        available = [str(p) for p in self.source_dirs if p.is_dir()]
        return {
            "enabled": bool(self._thread and self._thread.is_alive()),
            "watch_directories": available,
            "imported": self.imported,
            "skipped_or_invalid": self.skipped,
            "last_import": self.last_import,
            "last_error": self.last_error,
            "poll_seconds": int(_POLL_SECONDS),
            "max_file_mb": MAX_BYTES // (1024 * 1024),
        }

    def scan_once(self) -> int:
        try:
            ledger = json.loads(self.ledger_path.read_text("utf-8")) if self.ledger_path.exists() else {}
            if not isinstance(ledger, dict):
                ledger = {}
        except (OSError, ValueError):
            ledger = {}
        added = 0
        for folder in self.source_dirs:
            if not folder.is_dir():
                continue
            try:
                candidates = list(folder.iterdir())
            except OSError as exc:
                self.last_error = str(exc)[:300]
                continue
            for source in candidates:
                try:
                    if source.suffix.lower() != ".mp4" or source.is_symlink() or not source.is_file():
                        continue
                    stat = source.stat()
                    if stat.st_size <= 0 or stat.st_size > MAX_BYTES:
                        continue
                    key = str(source.resolve())
                    signature = (stat.st_size, stat.st_mtime_ns)
                    if ledger.get(key) == [signature[0], signature[1]]:
                        continue
                    if self._seen.get(key) != signature:
                        self._seen[key] = signature
                        continue
                    video_id = uuid.uuid4().hex
                    temporary = self.video_dir / (video_id + ".upload")
                    destination = self.video_dir / (video_id + ".mp4")
                    try:
                        with source.open("rb") as src, temporary.open("xb") as dst:
                            shutil.copyfileobj(src, dst, length=1024 * 1024)
                        copied = temporary.stat()
                        current = source.stat()
                        if (copied.st_size != signature[0] or
                                (current.st_size, current.st_mtime_ns) != signature):
                            continue
                        metadata = self.validator(temporary)
                        temporary.replace(destination)
                        ledger[key] = [signature[0], signature[1]]
                        self.ledger_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), "utf-8")
                        self.imported += 1
                        self.last_import = source.name
                        self.last_error = ""
                        added += 1
                    except (RendererUnavailable, RenderFailed, OSError, ValueError) as exc:
                        self.skipped += 1
                        self.last_error = (source.name + ": " + str(exc))[:300]
                    finally:
                        try:
                            temporary.unlink(missing_ok=True)
                        except OSError:
                            pass
                except OSError as exc:
                    self.last_error = (source.name + ": " + str(exc))[:300]
        return added

    def _run(self) -> None:
        while not self._stop.is_set():
            self.scan_once()
            self._stop.wait(_POLL_SECONDS)


def start_flow_auto_import(data_dir: Path, video_dir: Path) -> bool:
    global _worker
    enabled = os.getenv("SINTU_FLOW_AUTO_IMPORT", "").strip().lower()
    is_termux = "com.termux" in os.getenv("PREFIX", "") or Path("/data/data/com.termux/files/home").exists()
    if enabled == "false" or (enabled != "true" and not is_termux):
        return False
    if _worker is None:
        _worker = FlowAutoImporter(data_dir, video_dir)
    return _worker.start()


def stop_flow_auto_import() -> None:
    if _worker is not None:
        _worker.stop()


def flow_auto_import_status() -> dict:
    if _worker is None:
        return {"enabled": False, "watch_directories": [], "imported": 0,
                "skipped_or_invalid": 0, "last_import": "", "last_error": "",
                "poll_seconds": int(_POLL_SECONDS), "max_file_mb": MAX_BYTES // (1024 * 1024)}
    return _worker.status()
