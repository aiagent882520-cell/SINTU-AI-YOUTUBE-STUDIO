import errno
import hashlib
import json
import platform
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from scripts.media_quarantine import _publish_no_replace, process_manifest, safe_source


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

def test_symlinked_quarantine_root_is_rejected_without_touching_source(tmp_path):
    source = tmp_path / "generated_videos" / "clip.mp4"
    source.parent.mkdir()
    source.write_bytes(b"original")
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "media_quarantine").symlink_to(outside, target_is_directory=True)

    report = process_manifest(tmp_path, {
        "targets": [{"path": "generated_videos/clip.mp4", "sha256": digest(source)}]
    }, apply=True)

    assert report["targets"][0]["status"] == "REJECTED"
    assert source.read_bytes() == b"original"
    assert list(outside.iterdir()) == []


@pytest.mark.skipif(
    platform.system() != "Linux"
    or platform.machine().lower() not in {"aarch64", "arm64", "x86_64", "amd64", "i386", "i686", "armv7l"},
    reason="requires Linux renameat2 syscall support",
)
def test_apply_succeeds_when_hardlinks_are_unavailable(tmp_path, monkeypatch):
    source = tmp_path / "generated_videos" / "clip.mp4"
    source.parent.mkdir()
    source.write_bytes(b"original video bytes")
    expected = digest(source)

    def unavailable_link(*args, **kwargs):
        raise OSError(errno.EPERM, "hard links are unavailable")

    monkeypatch.setattr("scripts.media_quarantine.os.link", unavailable_link)
    report = process_manifest(tmp_path, {
        "targets": [{"path": "generated_videos/clip.mp4", "sha256": expected}]
    }, apply=True)

    item = report["targets"][0]
    copied = tmp_path / item["quarantine_copy"]
    assert item["status"] == "COPIED_VERIFIED"
    assert copied.read_bytes() == source.read_bytes()
    assert digest(copied) == expected
    assert source.read_bytes() == b"original video bytes"
    assert not list(copied.parent.glob(".sintu-quarantine-*"))


def test_atomic_publish_refuses_destination_collision(tmp_path):
    temporary = tmp_path / "verified.tmp"
    destination = tmp_path / "destination.mp4"
    temporary.write_bytes(b"verified")
    destination.write_bytes(b"do not replace")

    with pytest.raises(FileExistsError):
        _publish_no_replace(temporary, destination)

    assert temporary.read_bytes() == b"verified"
    assert destination.read_bytes() == b"do not replace"



def test_non_linux_hardlink_fallback_is_atomic_and_no_replace(tmp_path, monkeypatch):
    temporary = tmp_path / "verified.tmp"
    destination = tmp_path / "destination.mp4"
    temporary.write_bytes(b"verified")
    monkeypatch.setattr("scripts.media_quarantine.platform.system", lambda: "Darwin")

    _publish_no_replace(temporary, destination)

    assert destination.read_bytes() == b"verified"
    assert not temporary.exists()


def test_concurrent_publishers_only_one_wins_without_overwrite(tmp_path):
    destination = tmp_path / "destination.mp4"
    temporaries = [tmp_path / "first.tmp", tmp_path / "second.tmp"]
    temporaries[0].write_bytes(b"first verified payload")
    temporaries[1].write_bytes(b"second verified payload")
    barrier = threading.Barrier(2)

    def publish(path):
        barrier.wait()
        try:
            _publish_no_replace(path, destination)
            return "published"
        except FileExistsError:
            return "collision"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(publish, temporaries))

    assert sorted(outcomes) == ["collision", "published"]
    assert destination.read_bytes() in {
        b"first verified payload", b"second verified payload"
    }


def test_partial_copy_failure_cleans_temp_and_preserves_original(tmp_path, monkeypatch):
    source = tmp_path / "generated_videos" / "clip.mp4"
    source.parent.mkdir()
    source.write_bytes(b"original video bytes")
    expected = digest(source)

    def fail_after_partial_copy(source_stream, destination_stream, length=0):
        destination_stream.write(b"partial")
        destination_stream.flush()
        raise OSError(errno.EIO, "simulated interrupted copy")

    monkeypatch.setattr("scripts.media_quarantine.shutil.copyfileobj", fail_after_partial_copy)
    report = process_manifest(tmp_path, {
        "targets": [{"path": "generated_videos/clip.mp4", "sha256": expected}]
    }, apply=True)

    quarantine = tmp_path / "media_quarantine"
    assert report["targets"][0]["status"] == "REJECTED"
    assert source.read_bytes() == b"original video bytes"
    assert not list(quarantine.rglob(".sintu-quarantine-*"))
    assert not list(quarantine.rglob("clip.mp4"))
