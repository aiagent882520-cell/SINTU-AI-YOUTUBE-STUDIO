"""Fail-closed publishing gate bound to a successful quality audit and exact MP4 hash."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class PublishingQualityError(ValueError):
    """The MP4 lacks an exact, successful, persisted quality/provenance record."""


def require_publishable_provenance(*, data_dir: Path, output_path: Path) -> dict[str, Any]:
    """Require a PASS quality record for this exact unchanged MP4.

    A valid MP4 without a matching provenance manifest is intentionally not enough.
    """
    root = Path(data_dir).expanduser().resolve()
    candidate = Path(output_path).expanduser()
    if candidate.is_symlink() or not candidate.is_file():
        raise PublishingQualityError("Publishing blocked: MP4 is missing or unsafe.")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise PublishingQualityError("Publishing blocked: MP4 is outside SINTU_DATA_DIR.")
    relative = resolved.relative_to(root).as_posix()
    stat = resolved.stat()
    if stat.st_size <= 0:
        raise PublishingQualityError("Publishing blocked: MP4 is empty.")
    digest = hashlib.sha256()
    with resolved.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    output_hash = digest.hexdigest()

    manifest_dir = root / "production_manifests"
    if manifest_dir.is_symlink() or not manifest_dir.is_dir():
        raise PublishingQualityError("Publishing blocked: production provenance is missing.")
    if not manifest_dir.resolve().is_relative_to(root):
        raise PublishingQualityError("Publishing blocked: provenance directory escaped SINTU_DATA_DIR.")

    for manifest_path in sorted(manifest_dir.glob("*.json")):
        if manifest_path.is_symlink() or not manifest_path.is_file():
            continue
        try:
            if manifest_path.stat().st_size > 2 * 1024 * 1024:
                continue
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        output = manifest.get("output") if isinstance(manifest, dict) else None
        quality = manifest.get("quality_check") if isinstance(manifest, dict) else None
        if not isinstance(output, dict) or output.get("path") != relative:
            continue
        if output.get("sha256") != output_hash or output.get("size_bytes") != stat.st_size:
            continue
        if not isinstance(quality, dict) or quality.get("status") != "PASS" or quality.get("verified") is not True:
            raise PublishingQualityError("Publishing blocked: matching provenance has no persisted PASS quality status.")
        report = quality.get("report")
        if not isinstance(report, dict) or report.get("verified") is not True:
            raise PublishingQualityError("Publishing blocked: quality report is missing or invalid.")
        return {
            "status": "PASS",
            "output_sha256": output_hash,
            "size_bytes": stat.st_size,
            "manifest_path": manifest_path.relative_to(root).as_posix(),
            "quality_report": report,
        }
    raise PublishingQualityError("Publishing blocked: no provenance manifest matches this exact MP4 hash.")
