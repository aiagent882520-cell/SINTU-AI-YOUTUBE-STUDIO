import copy

import pytest

from scripts.project_health_audit import validate_mp4_metadata


def _metadata(audio=True):
    streams = [{
        "codec_type": "video",
        "codec_name": "h264",
        "width": 720,
        "height": 1280,
        "pix_fmt": "yuv420p",
    }]
    if audio:
        streams.append({
            "codec_type": "audio",
            "codec_name": "aac",
            "sample_rate": "48000",
            "channels": 2,
        })
    return {
        "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "8.0"},
        "streams": streams,
    }


def test_android_mp4_audit_accepts_h264_aac_stereo():
    result = validate_mp4_metadata(_metadata())
    assert result["video_codec"] == "h264"
    assert result["pixel_format"] == "yuv420p"
    assert result["audio"] == {"codec": "aac", "sample_rate": 48000, "channels": 2}


def test_android_mp4_audit_accepts_silent_h264_video():
    assert validate_mp4_metadata(_metadata(audio=False))["audio"] is None


@pytest.mark.parametrize(("path", "value", "message"), [
    (("format", "format_name"), "matroska,webm", "container"),
    (("format", "duration"), "nan", "duration"),
    (("streams", 0, "codec_name"), "vp9", "H.264"),
    (("streams", 0, "pix_fmt"), "yuv444p", "yuv420p"),
    (("streams", 1, "codec_name"), "opus", "AAC"),
    (("streams", 1, "sample_rate"), "44100", "48000"),
    (("streams", 1, "channels"), 6, "stereo"),
])
def test_android_mp4_audit_rejects_incompatible_metadata(path, value, message):
    data = copy.deepcopy(_metadata())
    target = data
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(ValueError, match=message):
        validate_mp4_metadata(data)


def test_android_mp4_audit_rejects_missing_video_stream():
    data = _metadata()
    data["streams"] = [stream for stream in data["streams"] if stream["codec_type"] != "video"]
    with pytest.raises(ValueError, match="missing video"):
        validate_mp4_metadata(data)



def test_motion_audit_rejects_frozen_long_video_frames():
    from scripts.project_health_audit import validate_sampled_motion
    frame = bytes([120]) * (32 * 32 * 3)
    with pytest.raises(ValueError, match="frozen or slideshow-like"):
        validate_sampled_motion(frame * 12, frame_bytes=len(frame))


def test_motion_audit_accepts_sustained_cinematic_motion():
    from scripts.project_health_audit import validate_sampled_motion
    frame_bytes = 32 * 32 * 3
    frames = b"".join(bytes([(index * 24) % 256]) * frame_bytes for index in range(12))
    result = validate_sampled_motion(frames, frame_bytes=frame_bytes)
    assert result["moving_transitions"] == 11
    assert result["motion_ratio"] == 1.0


def test_motion_audit_rejects_still_slideshow_with_only_scene_cuts():
    from scripts.project_health_audit import validate_sampled_motion
    frame_bytes = 32 * 32 * 3
    frames = b"".join(bytes([value]) * frame_bytes for value in
                      [10, 10, 10, 10, 80, 80, 80, 80, 150, 150, 150, 150])
    with pytest.raises(ValueError, match="frozen or slideshow-like"):
        validate_sampled_motion(frames, frame_bytes=frame_bytes)


def test_audit_summary_counts_failures_and_preserves_pytest_tail():
    from scripts.project_health_audit import summarize_audit

    result = summarize_audit([
        {"check": "python-compile", "status": "PASS"},
        {"check": "pytest", "status": "PASS", "output": "tests passed\n531 passed, 5 warnings in 10.2s"},
        {"check": "media:broken.mp4", "status": "FAIL"},
        {"check": "media-tools", "status": "WARN"},
    ])
    assert result["status"] == "FAIL"
    assert result["pass"] == 2
    assert result["warnings"] == 1
    assert result["failures"] == 1
    assert result["failed_checks"] == ["media:broken.mp4"]
    assert result["pytest_summary"] == "531 passed, 5 warnings in 10.2s"


def test_audit_summary_passes_when_no_failures_or_warnings():
    from scripts.project_health_audit import summarize_audit

    result = summarize_audit([{"check": "python-compile", "status": "PASS"}])
    assert result["status"] == "PASS"
    assert result["pass"] == 1
    assert result["warnings"] == 0
    assert result["failures"] == 0


def _create_health_audit_clip(path, color, duration=4):
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg is required for media black-threshold tests")
    created = subprocess.run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"color=c={color}:s=160x120:r=24:d={duration}",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
    ], capture_output=True, timeout=60, check=False)
    if created.returncode != 0:
        pytest.skip("FFmpeg build does not provide the libx264 test encoder")


def test_health_audit_does_not_flag_dark_visible_footage_as_black(tmp_path):
    from scripts.project_health_audit import audit_media

    clip = tmp_path / "dark-visible.mp4"
    _create_health_audit_clip(clip, "0x161616")
    results = []
    assert audit_media(tmp_path, results) is True
    assert results[0]["check"] == "media:dark-visible.mp4"
    assert results[0]["status"] == "PASS"
    assert results[0]["black_intervals"] == []


def test_health_audit_still_fails_a_fully_black_mp4(tmp_path):
    from scripts.project_health_audit import audit_media

    clip = tmp_path / "fully-black.mp4"
    _create_health_audit_clip(clip, "black")
    results = []
    assert audit_media(tmp_path, results) is False
    assert results[0]["check"] == "media:fully-black.mp4"
    assert results[0]["status"] == "FAIL"
    assert results[0]["black_intervals"]


def test_health_audit_allows_partial_black_but_not_full_duration_black(tmp_path):
    import shutil
    import subprocess
    from scripts.project_health_audit import audit_media

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg is required for partial-black health audit regression")
    clip = tmp_path / "partial-black.mp4"
    created = subprocess.run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=black:s=160x120:r=24:d=1",
        "-f", "lavfi", "-i", "color=c=white:s=160x120:r=24:d=3",
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0,format=yuv420p[v]",
        "-map", "[v]", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip),
    ], capture_output=True, timeout=60, check=False)
    if created.returncode != 0:
        pytest.skip("FFmpeg build does not provide the libx264 test encoder")
    results = []
    assert audit_media(tmp_path, results) is True
    assert results[0]["status"] == "PASS"
    assert results[0]["black_intervals"]
    assert results[0]["black_intervals"][0][1] < 3.8

