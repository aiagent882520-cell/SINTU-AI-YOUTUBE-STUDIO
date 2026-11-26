#!/usr/bin/env python3
"""Evidence-preserving quarantine copies for suspect generated MP4s.

The default mode is a read-only dry run. --apply copies exact SHA-256-matched
inputs into a content-addressed quarantine directory and leaves originals in
place. This tool never repairs, overwrites, moves, or deletes source media.
"""
from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import os
import platform
import shutil
import tempfile
from pathlib import Path, PurePosixPath


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_source(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError("unsafe source path")
    rel = PurePosixPath(relative)
    if rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
        raise ValueError("unsafe source path")
    if len(rel.parts) < 2 or rel.parts[0] != "generated_videos" or rel.suffix.lower() != ".mp4":
        raise ValueError("source must be an MP4 inside generated_videos/")
    current = root
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("symlink source paths are not allowed")
    resolved_root = root.resolve()
    resolved = current.resolve()
    if not resolved.is_relative_to(resolved_root) or not resolved.is_file():
        raise ValueError("source is missing or outside the data directory")
    return resolved


def _publish_no_replace(temporary: Path, destination: Path) -> None:
    """Atomically publish a verified file without replacing an existing path.

    Linux/Android renameat2(RENAME_NOREPLACE) works on filesystems where hard links are
    unavailable (notably some Android/Termux storage setups). If the syscall is
    unavailable, retain the portable hard-link implementation: link creation is
    also atomic and fails if the destination already exists.
    """
    if os.name == "posix" and platform.system() in {"Linux", "Android"}:
        syscall_numbers = {
            "aarch64": 276,
            "arm64": 276,
            "x86_64": 316,
            "amd64": 316,
            "i386": 353,
            "i686": 353,
            "armv7l": 382,
        }
        syscall_number = syscall_numbers.get(platform.machine().lower())
        if syscall_number is not None:
            libc = ctypes.CDLL(None, use_errno=True)
            result = libc.syscall(
                ctypes.c_long(syscall_number),
                ctypes.c_int(-100),  # AT_FDCWD
                ctypes.c_char_p(os.fsencode(temporary)),
                ctypes.c_int(-100),  # AT_FDCWD
                ctypes.c_char_p(os.fsencode(destination)),
                ctypes.c_uint(1),  # RENAME_NOREPLACE
            )
            if result == 0:
                return
            error = ctypes.get_errno()
            if error not in {errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP, errno.EPERM}:
                raise OSError(error, os.strerror(error), str(destination))
    # Atomic, no-overwrite fallback for platforms without renameat2.
    os.link(temporary, destination)


def copy_verified(root: Path, source: Path, destination: Path, expected_sha256: str) -> None:
    quarantine_root = root / "media_quarantine"
    if quarantine_root.is_symlink():
        raise ValueError("quarantine root must not be a symlink")
    quarantine_root.mkdir(parents=True, exist_ok=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if (not destination.parent.resolve().is_relative_to(quarantine_root.resolve())
            or destination.parent.is_symlink() or destination.exists() or destination.is_symlink()):
        raise FileExistsError("quarantine destination already exists or is unsafe")
    fd, temporary_name = tempfile.mkstemp(prefix=".sintu-quarantine-", dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as output, source.open("rb") as input_file:
            shutil.copyfileobj(input_file, output, length=1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        if sha256_file(temporary) != expected_sha256:
            raise ValueError("copied quarantine file failed SHA-256 verification")
        # Atomic no-replace publication; supports Termux where os.link may fail.
        _publish_no_replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def process_manifest(root: Path, manifest: dict, *, apply: bool = False) -> dict:
    if not isinstance(manifest, dict) or not isinstance(manifest.get("targets"), list):
        raise ValueError("manifest must contain a targets array")
    results = []
    for index, item in enumerate(manifest["targets"]):
        if not isinstance(item, dict):
            results.append({"index": index, "status": "REJECTED", "reason": "target must be an object"})
            continue
        relative = item.get("path")
        expected = item.get("sha256")
        if not isinstance(expected, str) or len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected.lower()):
            results.append({"path": relative, "status": "REJECTED", "reason": "expected sha256 must be 64 hexadecimal characters"})
            continue
        try:
            source = safe_source(root, relative)
            actual = sha256_file(source)
            if actual != expected.lower():
                results.append({"path": relative, "status": "HASH_MISMATCH", "expected_sha256": expected.lower(), "actual_sha256": actual})
                continue
            destination = root / "media_quarantine" / actual / source.name
            if apply:
                copy_verified(root, source, destination, actual)
                status = "COPIED_VERIFIED"
            else:
                status = "WOULD_COPY"
            results.append({
                "path": relative,
                "status": status,
                "sha256": actual,
                "size_bytes": source.stat().st_size,
                "quarantine_copy": str(destination.relative_to(root)) if apply else None,
                "original_preserved": True,
            })
        except (OSError, ValueError) as exc:
            results.append({"path": relative, "status": "REJECTED", "reason": str(exc)[:240]})
    return {
        "mode": "apply_copy_only" if apply else "dry_run_read_only",
        "source_mutations": 0,
        "targets": results,
        "human_review_required_before_repair_or_publish": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path, required=True,
                        help="JSON file with targets: [{path, sha256}, ...]")
    parser.add_argument("--apply", action="store_true",
                        help="Create verified quarantine copies; originals remain untouched")
    args = parser.parse_args()
    try:
        root = args.data_dir.expanduser().resolve()
        manifest = json.loads(args.manifest.expanduser().read_text(encoding="utf-8"))
        report = process_manifest(root, manifest, apply=args.apply)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)[:300]}, indent=2))
        return 2
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if all(item["status"] in {"WOULD_COPY", "COPIED_VERIFIED"} for item in report["targets"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
