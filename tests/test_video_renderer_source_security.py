import pytest

from app.video_renderer import _validate_source_video


def test_source_video_validation_accepts_mp4(tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"valid-source")
    _validate_source_video(path)


def test_source_video_validation_rejects_wrong_extension(tmp_path):
    path = tmp_path / "clip.mov"
    path.write_bytes(b"video")
    with pytest.raises(ValueError, match="MP4"):
        _validate_source_video(path)


def test_source_video_validation_rejects_empty_file(tmp_path):
    path = tmp_path / "clip.mp4"
    path.touch()
    with pytest.raises(ValueError, match="empty"):
        _validate_source_video(path)


def test_source_video_validation_rejects_oversized_file(tmp_path, monkeypatch):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"x")
    monkeypatch.setattr("app.video_renderer.MAX_SOURCE_VIDEO_BYTES", 0)
    with pytest.raises(ValueError, match="100 MB"):
        _validate_source_video(path)
