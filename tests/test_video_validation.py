import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from app.video_generator import VideoGenerationFailed, _validate_video


VALID_MP4_HEADER = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 16


def _probe_result(metadata, returncode=0):
    return SimpleNamespace(
        returncode=returncode,
        stdout=json.dumps(metadata).encode("utf-8"),
        stderr=b"",
    )


def test_validate_video_accepts_probe_verified_mp4(monkeypatch):
    metadata = {
        "streams": [{"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920}],
        "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "8.0"},
    }
    monkeypatch.setattr("app.video_generator.subprocess.run", lambda *a, **k: _probe_result(metadata))
    raw = VALID_MP4_HEADER
    assert _validate_video(raw) is raw


@pytest.mark.parametrize("metadata", [
    {"streams": [], "format": {"format_name": "mov,mp4", "duration": "8"}},
    {"streams": [{"codec_type": "audio", "codec_name": "aac", "width": 0, "height": 0}],
     "format": {"format_name": "mov,mp4", "duration": "8"}},
    {"streams": [{"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920}],
     "format": {"format_name": "matroska,webm", "duration": "8"}},
    {"streams": [{"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920}],
     "format": {"format_name": "mov,mp4", "duration": "0"}},
    {"streams": [{"codec_type": "video", "codec_name": "h264", "width": 9000, "height": 1920}],
     "format": {"format_name": "mov,mp4", "duration": "8"}},
])
def test_validate_video_rejects_invalid_probe_metadata(monkeypatch, metadata):
    monkeypatch.setattr("app.video_generator.subprocess.run", lambda *a, **k: _probe_result(metadata))
    with pytest.raises(VideoGenerationFailed):
        _validate_video(VALID_MP4_HEADER)


def test_validate_video_rejects_ffprobe_decode_failure(monkeypatch):
    monkeypatch.setattr("app.video_generator.subprocess.run", lambda *a, **k: _probe_result({}, 1))
    with pytest.raises(VideoGenerationFailed, match="corrupt"):
        _validate_video(VALID_MP4_HEADER)


def test_validate_video_rejects_missing_ffprobe(monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError("ffprobe")
    monkeypatch.setattr("app.video_generator.subprocess.run", missing)
    with pytest.raises(VideoGenerationFailed, match="FFprobe"):
        _validate_video(VALID_MP4_HEADER)


def test_validate_video_rejects_invalid_mp4_header():
    with pytest.raises(VideoGenerationFailed):
        _validate_video(b"not-an-mp4")



def test_validate_video_accepts_real_ffmpeg_mp4(tmp_path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg and FFprobe are required for the real MP4 integration test")
    candidate = tmp_path / "real-test.mp4"
    result = subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=160x284:r=12:d=1",
            "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(candidate),
        ],
        capture_output=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    video_bytes = candidate.read_bytes()
    assert _validate_video(video_bytes) == video_bytes


def test_validate_video_rejects_truncated_real_mp4(tmp_path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg and FFprobe are required for the real MP4 integration test")
    candidate = tmp_path / "truncated-source.mp4"
    result = subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=160x284:r=12:d=1",
            "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            str(candidate),
        ],
        capture_output=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    video_bytes = candidate.read_bytes()
    with pytest.raises(VideoGenerationFailed):
        _validate_video(video_bytes[: max(16, len(video_bytes) // 2)])
