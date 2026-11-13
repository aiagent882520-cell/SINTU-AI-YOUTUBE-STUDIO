from pathlib import Path

import pytest

from app import video_generator


def test_store_video_atomically_writes_final_mp4(tmp_path, monkeypatch):
    monkeypatch.setattr(video_generator, "AI_VIDEO_DIR", tmp_path)
    video_id, output = video_generator._store_video_atomically(b"validated-mp4")
    assert output == tmp_path / f"{video_id}.mp4"
    assert output.read_bytes() == b"validated-mp4"
    assert not list(tmp_path.glob("*.tmp"))
    assert not list(tmp_path.glob(".*.tmp"))


def test_store_video_atomically_cleans_partial_file_on_replace_error(tmp_path, monkeypatch):
    monkeypatch.setattr(video_generator, "AI_VIDEO_DIR", tmp_path)

    def fail_replace(source, destination):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(video_generator.os, "replace", fail_replace)
    with pytest.raises(video_generator.VideoGenerationFailed, match="safely save"):
        video_generator._store_video_atomically(b"validated-mp4")
    assert list(tmp_path.iterdir()) == []


def test_store_video_atomically_does_not_overwrite_existing_temp(tmp_path, monkeypatch):
    monkeypatch.setattr(video_generator, "AI_VIDEO_DIR", tmp_path)
    monkeypatch.setattr(video_generator.uuid, "uuid4", lambda: type("UUID", (), {"hex": "a" * 32})())
    temporary = tmp_path / f".{'a' * 32}.tmp"
    temporary.write_bytes(b"pre-existing")
    with pytest.raises(FileExistsError):
        video_generator._store_video_atomically(b"new-data")
    assert temporary.read_bytes() == b"pre-existing"
