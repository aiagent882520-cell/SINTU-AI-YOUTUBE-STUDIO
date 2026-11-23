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



def create_delivery_package(
    *,
    data_dir: Path,
    run_id: str,
    render_manifest_path: str,
    captions: list[str],
    seconds_per_caption: int,
    metadata: dict[str, Any],
    deliverables: dict[str, Any] | None = None,
    research_evidence: dict[str, Any] | None = None,
    max_total_bytes: int = 1024 * 1024 * 1024,
) -> dict[str, Any]:
    """Build and verify an Owner-local ZIP from a verified render manifest.

    Original media is copied into the archive, never moved or modified. The ZIP contains
    a timed SRT even when captions were not burned into the MP4. Missing editable-project
    and rights records are explicitly documented rather than fabricated.
    """
    if not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise ValueError("Invalid production run ID.")
    if not isinstance(captions, list) or len(captions) > 25:
        raise ValueError("Delivery captions must contain at most 25 scene lines.")
    if not isinstance(seconds_per_caption, int) or not 1 <= seconds_per_caption <= 60:
        raise ValueError("Invalid delivery caption timing.")
    if any(not isinstance(line, str) or len(line) > 1000 for line in captions):
        raise ValueError("Delivery caption lines must be text up to 1000 characters.")
    root = data_dir.expanduser().resolve()
    manifest_candidate = root / render_manifest_path
    manifest_file, manifest_relative = _relative_file(manifest_candidate, root)
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if manifest.get("run_id") != run_id or manifest.get("quality_check", {}).get("verified") is not True:
        raise ValueError("Delivery package requires this run's verified render provenance.")
    records = [manifest.get("output")] + list(manifest.get("inputs") or [])
    if not isinstance(records[0], dict) or any(not isinstance(item, dict) for item in records):
        raise ValueError("Render provenance file records are invalid.")
    verified_files: list[tuple[Path, str, dict[str, Any]]] = []
    total_bytes = 0
    for index, record in enumerate(records):
        relative = record.get("path")
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError("Render provenance contains an unsafe relative path.")
        source = root / relative
        if source.is_symlink():
            raise ValueError("Render provenance cannot package symlinked media.")
        resolved, safe_relative = _relative_file(source, root)
        if resolved.stat().st_size != record.get("size_bytes"):
            raise ValueError("Render provenance media size changed after verification.")
        digest = hashlib.sha256()
        with resolved.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != record.get("sha256"):
            raise ValueError("Render provenance media hash changed after verification.")
        archive_name = ("video/" if index == 0 else "assets/") + f"{index:02d}-" + resolved.name
        total_bytes += resolved.stat().st_size
        if total_bytes > max_total_bytes:
            raise ValueError("Production delivery package exceeds the 1 GiB safety limit.")
        verified_files.append((resolved, archive_name, {
            "path": archive_name, "size_bytes": resolved.stat().st_size,
            "sha256": digest.hexdigest(), "source_path": safe_relative,
        }))

    def srt_timestamp(seconds: int) -> str:
        hours, remainder = divmod(seconds, 3600)
        minutes, whole_seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},000"

    cues = []
    cursor = 0
    cue_index = 1
    for line in captions:
        clean = line.replace("\\r", " ").strip()
        if clean:
            cues.append(
                f"{cue_index}\\n{srt_timestamp(cursor)} --> "
                f"{srt_timestamp(cursor + seconds_per_caption)}\\n{clean}\\n"
            )
            cue_index += 1
        cursor += seconds_per_caption
    srt_content = ("\\n".join(cues) + "\\n") if cues else ""
    json_payloads: dict[str, Any] = {
        "metadata/production.json": metadata,
        "project/deliverables.json": deliverables if isinstance(deliverables, dict) else {},
        "reports/quality-report.json": manifest.get("quality_check", {}).get("report") or {},
    }
    if isinstance(research_evidence, dict):
        json_payloads["research/research-evidence.json"] = research_evidence
    serialized: dict[str, bytes] = {}
    for name, value in json_payloads.items():
        blob = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\\n").encode("utf-8")
        if len(blob) > 2 * 1024 * 1024:
            raise ValueError(f"Delivery metadata file is too large: {name}")
        serialized[name] = blob
    if srt_content:
        serialized["captions/subtitles.hi.srt"] = srt_content.encode("utf-8")
    readme = (
        "SINTU AI YOUTUBE STUDIO — PRODUCTION DELIVERY PACKAGE\\n"
        f"Run: {run_id}\\n"
        "Includes verified rendered media, source assets recorded by provenance, timed captions "
        "when available, production metadata, deliverables, and quality report.\\n"
        "The editable timeline/project file is not exported by the current renderer.\\n"
        "Per-asset third-party license/rights certificates were not supplied by the current "
        "production run; verify rights before external distribution.\\n"
        "Publishing is not performed by package creation and still requires separate Owner approval.\\n"
    )
    serialized["README.txt"] = readme.encode("utf-8")
    serialized["provenance/render-manifest.json"] = manifest_file.read_bytes()
    package_entries = [item[2] for item in verified_files]
    package_entries.extend({
        "path": name, "size_bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest()
    } for name, blob in serialized.items())
    package_index = {
        "schema_version": 1, "run_id": run_id, "verified": True,
        "entries": package_entries,
        "not_included": ["editable timeline project", "per-asset license/rights certificates"],
    }
    serialized["PACKAGE-MANIFEST.json"] = (
        json.dumps(package_index, ensure_ascii=False, indent=2, sort_keys=True) + "\\n"
    ).encode("utf-8")

    package_dir = root / "production_packages"
    package_dir.mkdir(parents=True, exist_ok=True)
    if package_dir.is_symlink() or not package_dir.resolve().is_relative_to(root):
        raise ValueError("Production package directory must remain inside DATA_DIR.")
    destination = package_dir / f"{run_id}-delivery.zip"
    fd, temporary_name = tempfile.mkstemp(prefix=".delivery-", suffix=".tmp", dir=package_dir)
    os.close(fd)
    try:
        with zipfile.ZipFile(temporary_name, "w", allowZip64=True) as archive:
            for source, archive_name, _record in verified_files:
                archive.write(source, archive_name, compress_type=zipfile.ZIP_STORED)
            for archive_name, blob in serialized.items():
                archive.writestr(archive_name, blob, compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
        with zipfile.ZipFile(temporary_name, "r") as archive:
            bad_member = archive.testzip()
            if bad_member is not None:
                raise ValueError("Delivery ZIP integrity check failed: " + bad_member)
            names = archive.namelist()
            if len(names) != len(set(names)) or "PACKAGE-MANIFEST.json" not in names:
                raise ValueError("Delivery ZIP contains duplicate or missing manifest entries.")
        with open(temporary_name, "rb") as stream:
            package_hash = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                package_hash.update(chunk)
        package_size = os.path.getsize(temporary_name)
        os.replace(temporary_name, destination)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise
    return {
        "schema_version": 1,
        "verified": True,
        "path": destination.relative_to(root).as_posix(),
        "filename": destination.name,
        "size_bytes": package_size,
        "sha256": package_hash.hexdigest(),
        "file_count": len(package_entries) + 1,
        "entries": package_entries,
        "render_manifest_path": manifest_relative,
        "captions_included": bool(srt_content),
        "editable_project_included": False,
        "rights_certificates_included": False,
    }
