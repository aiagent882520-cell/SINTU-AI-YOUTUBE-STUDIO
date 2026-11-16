import shutil
import subprocess

import pytest

from app.video_renderer import RenderFailed, verify_publishable_mp4


def _make_video(path, source, duration=6):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg required")
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"{source}:s=720x1280:r=24:d={duration}",
         "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        capture_output=True, check=False, timeout=60,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    return path


def test_publishable_mp4_rejects_long_static_image_video(tmp_path):
    path = _make_video(tmp_path / "static.mp4", "color=c=navy", duration=8)
    with pytest.raises(RenderFailed, match="mostly static"):
        verify_publishable_mp4(path)


def test_publishable_mp4_accepts_genuine_moving_video(tmp_path):
    path = _make_video(tmp_path / "moving.mp4", "testsrc", duration=8)
    result = verify_publishable_mp4(path)
    assert result["verified"] is True
    assert result["motion_checked"] is True
    assert result["motion_transitions"] > 0
    assert result["motion_ratio"] >= 0.10


def test_short_establishing_clip_is_not_rejected_only_for_short_duration(tmp_path):
    path = _make_video(tmp_path / "short.mp4", "color=c=navy", duration=2)
    result = verify_publishable_mp4(path)
    assert result["verified"] is True
    assert result["motion_checked"] is False
