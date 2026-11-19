import pytest
import shutil
import subprocess
from types import SimpleNamespace

from app.video_renderer import _validate_source_video


def test_source_video_validation_accepts_mp4(tmp_path, monkeypatch):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"valid-source")
    monkeypatch.setattr("app.video_renderer.shutil.which", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setattr("app.video_renderer.subprocess.run", lambda *a, **k: SimpleNamespace(returncode=0, stdout=bytes([80, 120, 160]) * (32 * 32), stderr=b""))
    _validate_source_video(path)


def test_source_video_validation_rejects_all_black_real_mp4(tmp_path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg is required for the real MP4 integration test")
    path = tmp_path / "black.mp4"
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "color=c=black:s=160x284:r=12:d=1", "-an", "-c:v", "libx264",
         "-pix_fmt", "yuv420p", str(path)],
        capture_output=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    with pytest.raises(ValueError, match="visual check"):
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


def test_source_video_validation_rejects_symlink(tmp_path):
    target = tmp_path / "real.mp4"
    target.write_bytes(b"video")
    link = tmp_path / "clip.mp4"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are not available on this platform.")
    with pytest.raises(ValueError, match="safe regular file"):
        _validate_source_video(link)


@pytest.mark.parametrize("label", ["Voiceover audio", "Background music"])
def test_audio_input_validation_accepts_regular_nonempty_file(tmp_path, label):
    from app.video_renderer import _validate_audio_file

    path = tmp_path / "audio.wav"
    path.write_bytes(b"audio")
    _validate_audio_file(path, label)


@pytest.mark.parametrize("label", ["Voiceover audio", "Background music"])
def test_audio_input_validation_rejects_symlink(tmp_path, label):
    from app.video_renderer import _validate_audio_file

    target = tmp_path / "real.wav"
    target.write_bytes(b"audio")
    link = tmp_path / "linked.wav"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are not available on this platform.")
    with pytest.raises(ValueError, match="safe regular file"):
        _validate_audio_file(link, label)


@pytest.mark.parametrize("contents, expected", [(b"", "empty"), (None, "safe regular file")])
def test_audio_input_validation_rejects_empty_or_missing_file(tmp_path, contents, expected):
    from app.video_renderer import _validate_audio_file

    path = tmp_path / "audio.wav"
    if contents is not None:
        path.write_bytes(contents)
    with pytest.raises(ValueError, match=expected):
        _validate_audio_file(path, "Voiceover audio")
