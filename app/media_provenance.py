"""Private, content-addressed provenance manifests for successful production renders."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _relative_file(path: Path, root: Path) -> tuple[Path, str]:
    resolved_root = root.expanduser().resolve()
    resolved = path.expanduser().resolve(strict=True)
    if not resolved.is_file() or not resolved.is_relative_to(resolved_root):
        raise ValueError("Production provenance paths must be existing files inside DATA_DIR.")
    return resolved, resolved.relative_to(resolved_root).as_posix()


def _file_record(path: Path, root: Path) -> dict[str, Any]:
    resolved, relative = _relative_file(path, root)
    digest = hashlib.sha256()
    with resolved.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "path": relative,
        "size_bytes": resolved.stat().st_size,
        "sha256": digest.hexdigest(),
    }


def write_render_manifest(
    *,
    data_dir: Path,
    run_id: str,
    format_id: str,
    topic: str,
    output_path: Path,
    asset_paths: list[Path],
    settings: dict[str, Any] | None = None,
    engines: dict[str, str] | None = None,
    quality_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Atomically record hashes and relative paths for a successful render and its inputs.

    The manifest stays under DATA_DIR, contains no credentials or absolute paths, and
    intentionally stores only a topic hash rather than the user's topic text.
    """
    if not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise ValueError("Invalid production run ID.")
    if not isinstance(format_id, str) or not format_id or len(format_id) > 100:
        raise ValueError("Invalid production format ID.")
    if not isinstance(topic, str):
        raise ValueError("Invalid production topic.")
    root = data_dir.expanduser().resolve()
    output = _file_record(output_path, root)
    assets = [_file_record(path, root) for path in asset_paths]
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "format_id": format_id,
        "topic_sha256": hashlib.sha256(topic.encode("utf-8")).hexdigest(),
        "output": output,
        "inputs": assets,
        "settings": settings or {},
        "engines": engines or {},
        "quality_check": ({
            "status": "PASS",
            "verified": True,
            "report": quality_report,
        } if isinstance(quality_report, dict) and quality_report.get("verified") is True else {
            "status": "MISSING",
            "verified": False,
        }),
    }
    manifest_dir = root / "production_manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    if manifest_dir.is_symlink() or not manifest_dir.resolve().is_relative_to(root):
        raise ValueError("Production manifest directory must remain inside DATA_DIR.")
    destination = manifest_dir / f"{run_id}-{Path(output['path']).stem}.json"
    fd, temporary_name = tempfile.mkstemp(prefix=".manifest-", suffix=".tmp", dir=manifest_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, destination)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise
    manifest["manifest_path"] = destination.relative_to(root).as_posix()
    return manifest
