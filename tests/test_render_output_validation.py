import json
from types import SimpleNamespace

import pytest

from app.video_renderer import RenderFailed, _verify_rendered_output


def _metadata(width=720, height=1280, duration=8.0, audio=True, codec="h264", pix_fmt="yuv420p", audio_codec="aac", sample_rate="48000", channels=2):
    streams = [{"codec_type": "video", "codec_name": codec, "width": width, "height": height, "pix_fmt": pix_fmt, "duration": str(duration), "nb_read_frames": "240", "avg_frame_rate": "30/1"}]
    if audio:
        streams.append({"codec_type": "audio", "codec_name": audio_codec, "sample_rate": sample_rate, "channels": channels, "duration": str(duration)})
    return {"streams": streams, "format": {"format_name": "mov,mp4,m4a", "duration": str(duration)}}


def _run_result(metadata, returncode=0):
    return SimpleNamespace(returncode=returncode, stdout=json.dumps(metadata), stderr="probe failed")


def _setup_probe(monkeypatch, metadata, returncode=0):
    monkeypatch.setattr("app.video_renderer.shutil.which", lambda name: f"/usr/bin/{name}")
    def fake_run(command, **kwargs):
        if "ffprobe" in command[0]:
            return _run_result(metadata, returncode)
        return SimpleNamespace(returncode=0, stdout=bytes(range(256)) * 12, stderr="")
    monkeypatch.setattr("app.video_renderer.subprocess.run", fake_run)


def test_final_mp4_verification_accepts_expected_video_and_audio(tmp_path, monkeypatch):
    _setup_probe(monkeypatch, _metadata())
    output = tmp_path / "final.mp4"
    output.write_bytes(b"mp4")
    result = _verify_rendered_output(output, 720, 1280, 8, require_audio=True)
    assert result == {"verified": True, "duration_seconds": 8.0, "video_duration_seconds": 8.0, "frame_count": 240, "fps": 30.0, "resolution": "720x1280", "video_codec": "h264", "audio": True, "audio_duration_seconds": 8.0, "black_intervals": [], "longest_black_segment_seconds": 0.0, "visible_frame_count": 1, "sampled_frame_count": 1}


@pytest.mark.parametrize("metadata", [
    _metadata(width=1080, height=1920),
    _metadata(duration=20),
    _metadata(codec="vp9"),
    _metadata(pix_fmt="yuv444p"),
    _metadata(audio_codec="opus"),
    _metadata(sample_rate="44100"),
    _metadata(channels=6),
    {"streams": [], "format": {"format_name": "mov,mp4", "duration": "8"}},
    {"streams": [{"codec_type": "video", "codec_name": "h264", "width": 720, "height": 1280}],
     "format": {"format_name": "matroska,webm", "duration": "8"}},
])
def test_final_mp4_verification_rejects_wrong_output_metadata(tmp_path, monkeypatch, metadata):
    _setup_probe(monkeypatch, metadata)
    output = tmp_path / "final.mp4"
    output.write_bytes(b"mp4")
    with pytest.raises(RenderFailed):
        _verify_rendered_output(output, 720, 1280, 8, require_audio=True)


@pytest.mark.parametrize("frame_count,video_duration", [
    ("4", "0.166667"),
    ("240", "4.0"),
])
def test_final_mp4_verification_rejects_incomplete_video_stream(tmp_path, monkeypatch, frame_count, video_duration):
    metadata = _metadata()
    metadata["streams"][0]["nb_read_frames"] = frame_count
    metadata["streams"][0]["duration"] = video_duration
    _setup_probe(monkeypatch, metadata)
    output = tmp_path / "truncated.mp4"
    output.write_bytes(b"mp4")
    with pytest.raises(RenderFailed, match="actual frames"):
        _verify_rendered_output(output, 720, 1280, 8, require_audio=True)


def test_final_mp4_verification_rejects_missing_expected_audio(tmp_path, monkeypatch):
    _setup_probe(monkeypatch, _metadata(audio=False))
    output = tmp_path / "final.mp4"
    output.write_bytes(b"mp4")
    with pytest.raises(RenderFailed, match="audio stream"):
        _verify_rendered_output(output, 720, 1280, 8, require_audio=True)


def test_final_mp4_verification_rejects_ffprobe_failure(tmp_path, monkeypatch):
    _setup_probe(monkeypatch, {}, returncode=1)
    output = tmp_path / "final.mp4"
    output.write_bytes(b"mp4")
    with pytest.raises(RenderFailed, match="corrupt"):
        _verify_rendered_output(output, 720, 1280, 8)


def test_final_mp4_verification_requires_ffprobe(tmp_path, monkeypatch):
    monkeypatch.setattr("app.video_renderer.shutil.which", lambda name: None)
    output = tmp_path / "final.mp4"
    output.write_bytes(b"mp4")
    from app.video_renderer import RendererUnavailable
    with pytest.raises(RendererUnavailable, match="FFprobe"):
        _verify_rendered_output(output, 720, 1280, 8)



def test_sampled_motion_rejects_frozen_frames():
    from app.video_renderer import validate_sampled_motion

    frame = bytes([80]) * (32 * 32 * 3)
    with pytest.raises(RenderFailed, match="slideshow-like"):
        validate_sampled_motion(frame * 12, minimum_ratio=0.60)


def test_sampled_motion_accepts_continuous_camera_movement():
    from app.video_renderer import validate_sampled_motion

    frame_bytes = 32 * 32 * 3
    frames = b"".join(bytes([min(255, 30 + index * 20)]) * frame_bytes for index in range(12))
    result = validate_sampled_motion(frames, minimum_ratio=0.60)
    assert result["motion_ratio"] == 1.0
    assert result["moving_transitions"] == 11


def test_final_mp4_verification_rejects_frozen_long_video(tmp_path, monkeypatch):
    metadata = _metadata(duration=12.0)
    metadata["streams"][0]["nb_read_frames"] = "360"
    monkeypatch.setattr("app.video_renderer.shutil.which", lambda name: f"/usr/bin/{name}")

    def fake_run(command, **kwargs):
        if "ffprobe" in command[0]:
            return _run_result(metadata)
        frame_bytes = 32 * 32 * 3
        return SimpleNamespace(returncode=0, stdout=bytes([80]) * frame_bytes * 12, stderr="")

    monkeypatch.setattr("app.video_renderer.subprocess.run", fake_run)
    output = tmp_path / "frozen.mp4"
    output.write_bytes(b"mp4")
    with pytest.raises(RenderFailed, match="slideshow-like"):
        _verify_rendered_output(output, 720, 1280, 12, require_audio=True)


def test_final_mp4_verification_returns_motion_metrics_for_long_video(tmp_path, monkeypatch):
    metadata = _metadata(duration=12.0)
    metadata["streams"][0]["nb_read_frames"] = "360"
    monkeypatch.setattr("app.video_renderer.shutil.which", lambda name: f"/usr/bin/{name}")

    def fake_run(command, **kwargs):
        if "ffprobe" in command[0]:
            return _run_result(metadata)
        frame_bytes = 32 * 32 * 3
        frames = b"".join(bytes([min(255, 30 + index * 20)]) * frame_bytes for index in range(12))
        return SimpleNamespace(returncode=0, stdout=frames, stderr="")

    monkeypatch.setattr("app.video_renderer.subprocess.run", fake_run)
    output = tmp_path / "moving.mp4"
    output.write_bytes(b"mp4")
    result = _verify_rendered_output(output, 720, 1280, 12, require_audio=True)
    assert result["motion_audit"]["motion_ratio"] == 1.0


def test_publish_gate_rejects_full_duration_black_mp4_even_with_valid_audio(tmp_path):
    import shutil
    import subprocess

    from app.video_renderer import verify_publishable_mp4
    from scripts.repair_media import needs_audio_repair

    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg and FFprobe are required for the real black-frame gate test")
    black = tmp_path / "black-with-valid-audio.mp4"
    created = subprocess.run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=black:s=720x1280:r=24:d=4",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=4",
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-ac", "2",
        "-shortest", "-movflags", "+faststart", str(black),
    ], capture_output=True, timeout=60, check=False)
    assert created.returncode == 0, created.stderr.decode("utf-8", "replace")

    probe = subprocess.run([
        ffprobe, "-v", "error", "-show_streams", "-of", "json", str(black)
    ], capture_output=True, text=True, timeout=30, check=False)
    assert probe.returncode == 0
    metadata = json.loads(probe.stdout)
    assert needs_audio_repair(metadata) is False
    with pytest.raises(RenderFailed, match="full-duration black"):
        verify_publishable_mp4(black)


def test_publish_gate_allows_short_clip_with_visible_content_and_partial_black_intro(tmp_path):
    import shutil
    import subprocess

    from app.video_renderer import verify_publishable_mp4

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg is required for the real partial-black integration test")
    candidate = tmp_path / "visible-after-intro.mp4"
    created = subprocess.run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=black:s=720x1280:r=24:d=2",
        "-f", "lavfi", "-i", "color=c=red:s=720x1280:r=24:d=6",
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
        "-map", "[v]", "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", "-t", "8", "-movflags", "+faststart", str(candidate),
    ], capture_output=True, timeout=60, check=False)
    assert created.returncode == 0, created.stderr.decode("utf-8", "replace")
    result = verify_publishable_mp4(candidate)
    assert result["verified"] is True
    assert result["duration_seconds"] == pytest.approx(8.0, abs=0.1)


def test_publish_gate_rejects_long_black_segment_even_when_most_frames_are_visible(tmp_path, monkeypatch):
    import shutil
    import subprocess

    from app.video_renderer import verify_publishable_mp4

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg is required for the real long-black-segment test")
    candidate = tmp_path / "long-black-segment.mp4"
    created = subprocess.run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=black:s=720x1280:r=24:d=3.2",
        "-f", "lavfi", "-i", "color=c=red:s=720x1280:r=24:d=8.8",
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
        "-map", "[v]", "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", "-t", "12", "-movflags", "+faststart", str(candidate),
    ], capture_output=True, timeout=60, check=False)
    assert created.returncode == 0, created.stderr.decode("utf-8", "replace")
    with pytest.raises(RenderFailed, match="lamba black segment"):
        verify_publishable_mp4(candidate)


def test_render_gate_rejects_long_black_segment_before_publishing_output(tmp_path):
    import shutil
    import subprocess

    from app.video_renderer import _verify_rendered_output

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg is required for the real render-time black-segment test")
    candidate = tmp_path / "render-with-black-intro.mp4"
    created = subprocess.run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=black:s=720x1280:r=24:d=3.2",
        "-f", "lavfi", "-i", "testsrc2=s=720x1280:r=24:d=8.8",
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
        "-map", "[v]", "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", "-r", "24", "-t", "12", "-movflags", "+faststart",
        str(candidate),
    ], capture_output=True, timeout=90, check=False)
    assert created.returncode == 0, created.stderr.decode("utf-8", "replace")
    with pytest.raises(RenderFailed, match="lamba black segment"):
        _verify_rendered_output(
            candidate, 720, 1280, 12, require_audio=False, expected_fps=24,
            minimum_motion_ratio=0.40,
        )


def test_final_mp4_verification_derives_audio_duration_from_time_base(tmp_path, monkeypatch):
    metadata = _metadata()
    audio = metadata["streams"][1]
    audio.pop("duration")
    audio["duration_ts"] = "384000"
    audio["time_base"] = "1/48000"
    _setup_probe(monkeypatch, metadata)
    output = tmp_path / "duration-ts-audio.mp4"
    output.write_bytes(b"mp4")
    result = _verify_rendered_output(output, 720, 1280, 8, require_audio=True)
    assert result["audio_duration_seconds"] == pytest.approx(8.0)
