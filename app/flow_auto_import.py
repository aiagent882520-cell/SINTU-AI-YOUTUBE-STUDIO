"""Automatic Google Flow MP4 pickup for Termux/Android Downloads.

Only completed, stable, regular .mp4 files are copied into SINTU. Source files
are never moved or deleted. Every imported file is validated with FFprobe.
"""
from __future__ import annotations

import json
import os
import hashlib
import re
import shutil
import threading
import time
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .video_renderer import verify_publishable_mp4, render_mixed_timeline, RendererUnavailable, RenderFailed

MAX_BYTES = 512 * 1024 * 1024
_POLL_SECONDS = 5.0
_QUIET_SECONDS = 20.0
_worker: "FlowAutoImporter | None" = None

 
def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write_json(path: Path, value) -> None:
    """Persist queue/ledger JSON without exposing a partially-written state file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + "-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


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
                 validator: Callable = verify_publishable_mp4,
                 renderer: Callable = render_mixed_timeline):
        self.data_dir = Path(data_dir)
        self.video_dir = Path(video_dir)
        self.source_dirs = source_dirs if source_dirs is not None else default_download_dirs()
        self.validator = validator
        self.renderer = renderer
        self.ledger_path = self.data_dir / "flow_auto_imported.json"
        self.pending_path = self.data_dir / "flow_auto_pending.json"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._seen: dict[str, tuple[int, int]] = {}
        self._lock = threading.Lock()
        self.imported = 0
        self.skipped = 0
        self.last_error = ""
        self.last_import = ""
        self.pending: list[str] = self._load_pending()
        self.last_added_at = 0.0
        self.last_render_result: dict = {}
        self.last_render_error = ""

    def _load_pending(self) -> list[str]:
        """Restore queued imports after an app/process restart."""
        try:
            values = json.loads(self.pending_path.read_text("utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(values, list):
            return []
        return list(dict.fromkeys(
            item for item in values
            if isinstance(item, str) and re.fullmatch(r"[a-f0-9]{32}", item)
        ))

    def _save_pending(self) -> None:
        """Atomically persist pending video IDs so a crash cannot lose the queue."""
        _atomic_write_json(self.pending_path, self.pending)

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
            "pending_clips": len(self.pending),
            "last_render": self.last_render_result,
            "last_render_error": self.last_render_error,
            "poll_seconds": int(_POLL_SECONDS),
            "max_file_mb": MAX_BYTES // (1024 * 1024),
        }

    def scan_once(self) -> int:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.video_dir.mkdir(parents=True, exist_ok=True)
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
                    previous = ledger.get(key)
                    if previous == [signature[0], signature[1]]:
                        continue
                    if (isinstance(previous, dict)
                            and previous.get("size_bytes") == signature[0]
                            and previous.get("mtime_ns") == signature[1]):
                        continue
                    if self._seen.get(key) != signature:
                        self._seen[key] = signature
                        continue
                    video_id = uuid.uuid4().hex
                    temporary = self.video_dir / (video_id + ".upload")
                    destination = self.video_dir / (video_id + ".mp4")
                    try:
                        source_hash_before = _sha256_file(source)
                        with source.open("rb") as src, temporary.open("xb") as dst:
                            shutil.copyfileobj(src, dst, length=1024 * 1024)
                            dst.flush()
                            os.fsync(dst.fileno())
                        copied = temporary.stat()
                        current = source.stat()
                        copied_hash = _sha256_file(temporary)
                        source_hash_after = _sha256_file(source)
                        if (copied.st_size != signature[0] or
                                (current.st_size, current.st_mtime_ns) != signature or
                                source_hash_before != copied_hash or source_hash_after != copied_hash):
                            self.last_error = (source.name + ": source changed during import; retrying")[:300]
                            continue
                        duplicate = next((
                            value for value in ledger.values()
                            if isinstance(value, dict) and value.get("sha256") == copied_hash
                        ), None)
                        if duplicate:
                            ledger[key] = {
                                "size_bytes": signature[0], "mtime_ns": signature[1],
                                "sha256": copied_hash, "duplicate_of": duplicate.get("video_id"),
                            }
                            _atomic_write_json(self.ledger_path, ledger)
                            self.skipped += 1
                            continue
                        metadata = self.validator(temporary)
                        if not isinstance(metadata, dict) or not metadata:
                            raise RenderFailed("MP4 validator ne valid video metadata return nahi kiya.")
                        temporary.replace(destination)
                        self.pending.append(video_id)
                        self._save_pending()
                        ledger[key] = {
                            "size_bytes": signature[0], "mtime_ns": signature[1],
                            "sha256": copied_hash, "video_id": video_id,
                        }
                        _atomic_write_json(self.ledger_path, ledger)
                        self.imported += 1
                        self.last_import = source.name
                        self.last_added_at = time.monotonic()
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

    def flush_pending(self, force: bool = False) -> dict | None:
        """Render a batch of imported clips after downloads have gone quiet."""
        if not self.pending or (not force and time.monotonic() - self.last_added_at < _QUIET_SECONDS):
            return None
        if os.getenv("SINTU_FLOW_AUTO_RENDER", "true").strip().lower() == "false":
            return None
        batch = self.pending[:25]
        items = []
        scenes = []
        for video_id in batch:
            path = self.video_dir / (video_id + ".mp4")
            if not path.is_file() or path.is_symlink():
                continue
            items.append({"kind": "video", "path": path, "trim_start": 0,
                          "trim_end": None, "audio_volume": 0.25})
            scenes.append("Google Flow video clip " + str(len(scenes) + 1))
        if not items:
            self.pending = self.pending[len(batch):]
            self._save_pending()
            return None
        title = "SINTU Flow Auto Compilation " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H-%M UTC")
        try:
            result = self.renderer(items, title, scenes, seconds_per_scene=4,
                                   transition="fade", resolution=os.getenv("SINTU_FLOW_AUTO_RESOLUTION", "720x1280"),
                                   fps=30, quality="standard", sound_effects_enabled=False)
            self.last_render_result = result if isinstance(result, dict) else {"result": str(result)}
            self.last_render_error = ""
            completed = set(batch)
            self.pending = [video_id for video_id in self.pending if video_id not in completed]
            self._save_pending()
            return self.last_render_result
        except Exception as exc:
            # Keep the durable queue untouched; the next poll/restart retries it.
            self.last_render_error = str(exc)[:500]
            return None

    def _run(self) -> None:
        while not self._stop.is_set():
            self.scan_once()
            self.flush_pending()
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
                "skipped_or_invalid": 0, "last_import": "", "last_error": "", "pending_clips": 0,
                "last_render": {}, "last_render_error": "",
                "poll_seconds": int(_POLL_SECONDS), "max_file_mb": MAX_BYTES // (1024 * 1024)}
    return _worker.status()
