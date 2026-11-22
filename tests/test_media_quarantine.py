import hashlib
import json
from pathlib import Path

import pytest

from scripts.media_quarantine import process_manifest, safe_source


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_default_manifest_processing_is_read_only_dry_run(tmp_path):
    source = tmp_path / "generated_videos" / "clip.mp4"
    source.parent.mkdir()
    source.write_bytes(b"original video bytes")
    before = source.read_bytes()

    report = process_manifest(tmp_path, {
        "targets": [{"path": "generated_videos/clip.mp4", "sha256": digest(source)}]
    })

    assert report["mode"] == "dry_run_read_only"
    assert report["source_mutations"] == 0
    assert report["targets"][0]["status"] == "WOULD_COPY"
    assert source.read_bytes() == before
    assert not (tmp_path / "media_quarantine").exists()


def test_apply_creates_verified_copy_and_preserves_original(tmp_path):
    source = tmp_path / "generated_videos" / "clip.mp4"
    source.parent.mkdir()
    source.write_bytes(b"original video bytes")
    expected = digest(source)

    report = process_manifest(tmp_path, {
        "targets": [{"path": "generated_videos/clip.mp4", "sha256": expected}]
    }, apply=True)

    item = report["targets"][0]
    copied = tmp_path / item["quarantine_copy"]
    assert item["status"] == "COPIED_VERIFIED"
    assert copied.read_bytes() == source.read_bytes()
    assert digest(copied) == expected
    assert source.exists()
    assert report["source_mutations"] == 0


def test_hash_mismatch_never_copies_or_mutates_source(tmp_path):
    source = tmp_path / "generated_videos" / "clip.mp4"
    source.parent.mkdir()
    source.write_bytes(b"original")
    report = process_manifest(tmp_path, {
        "targets": [{"path": "generated_videos/clip.mp4", "sha256": "0" * 64}]
    }, apply=True)
    assert report["targets"][0]["status"] == "HASH_MISMATCH"
    assert source.read_bytes() == b"original"
    assert not (tmp_path / "media_quarantine").exists()


@pytest.mark.parametrize("path", [
    "../secret.mp4",
    "/tmp/secret.mp4",
    "generated_videos/../../secret.mp4",
    "generated_images/image.png",
    "generated_videos/clip.mov",
])
def test_unsafe_or_non_mp4_paths_are_rejected(tmp_path, path):
    with pytest.raises(ValueError):
        safe_source(tmp_path, path)


def test_symlink_source_is_rejected(tmp_path):
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"outside")
    media = tmp_path / "generated_videos"
    media.mkdir()
    (media / "link.mp4").symlink_to(outside)
    with pytest.raises(ValueError):
        safe_source(tmp_path, "generated_videos/link.mp4")


def test_existing_quarantine_destination_is_not_overwritten(tmp_path):
    source = tmp_path / "generated_videos" / "clip.mp4"
    source.parent.mkdir()
    source.write_bytes(b"original")
    expected = digest(source)
    destination = tmp_path / "media_quarantine" / expected / source.name
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"do not overwrite")
    report = process_manifest(tmp_path, {
        "targets": [{"path": "generated_videos/clip.mp4", "sha256": expected}]
    }, apply=True)
    assert report["targets"][0]["status"] == "REJECTED"
    assert destination.read_bytes() == b"do not overwrite"
    assert source.read_bytes() == b"original"
