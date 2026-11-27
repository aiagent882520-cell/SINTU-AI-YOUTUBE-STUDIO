import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import immersive_renderer


def _probe_result(width, height, duration=2.0, codec="h264"):
    return SimpleNamespace(
        returncode=0,
        stdout=json.dumps({
            "format": {"duration": str(duration)},
            "streams": [{
                "codec_type": "video", "width": width, "height": height,
                "codec_name": codec,
            }],
        }),
        stderr="",
    )


def test_360_projection_export_converts_declared_cubemap_and_reports_metadata_gap(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    destination = tmp_path / "converted.mp4"
    calls = []

    monkeypatch.setattr(immersive_renderer.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[0].endswith("ffprobe"):
            if str(destination) in command:
                return _probe_result(1920, 960)
            return _probe_result(300, 200)
        destination.write_bytes(b"rendered")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(immersive_renderer.render_process, "run_render_process", fake_run)
    result = immersive_renderer.render_360_projection(
        source, destination, input_projection="c3x2"
    )

    assert result["success"] is True
    assert result["output_projection"] == "equirectangular"
    assert result["spherical_metadata_embedded"] is False
    assert result["platform_ready"] is False
    ffmpeg_call = next(command for command in calls if command[0].endswith("ffmpeg"))
    assert "v360=input=c3x2:output=e:w=1920:h=960:interp=lanc" in ffmpeg_call


@pytest.mark.parametrize(
    "kwargs",
    [
        {"input_projection": "not-a-projection"},
        {"input_projection": "c3x2", "resolution": "3840x1080"},
        {"input_projection": "c3x2", "fps": 120},
        {"input_projection": "c3x2", "quality": 10},
    ],
)
def test_360_projection_export_rejects_unsupported_options_before_render(tmp_path, monkeypatch, kwargs):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    destination = tmp_path / "out.mp4"
    with pytest.raises(ValueError):
        immersive_renderer.render_360_projection(source, destination, **kwargs)
    assert not destination.exists()


def test_360_projection_export_rejects_wrong_source_aspect_without_touching_source(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"original")
    destination = tmp_path / "out.mp4"
    monkeypatch.setattr(immersive_renderer.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        immersive_renderer.render_process, "run_render_process",
        lambda *args, **kwargs: _probe_result(640, 480),
    )

    with pytest.raises(immersive_renderer.ImmersiveRenderError, match="dimensions"):
        immersive_renderer.render_360_projection(
            source, destination, input_projection="c3x2"
        )
    assert source.read_bytes() == b"original"
    assert not destination.exists()


def test_360_projection_export_refuses_existing_destination_and_symlink_source(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    destination = tmp_path / "existing.mp4"
    destination.write_bytes(b"keep")
    with pytest.raises(immersive_renderer.ImmersiveRenderError, match="overwrite"):
        immersive_renderer.render_360_projection(
            source, destination, input_projection="e"
        )
    assert destination.read_bytes() == b"keep"

    link = tmp_path / "linked.mp4"
    link.symlink_to(source)
    with pytest.raises(immersive_renderer.ImmersiveRenderError, match="regular"):
        immersive_renderer.render_360_projection(
            link, tmp_path / "other.mp4", input_projection="e"
        )

def test_360_projection_export_runs_real_ffmpeg_v360_when_available(tmp_path):
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg and FFprobe are required for the real 360 conversion test")
    filters = subprocess.run(
        [ffmpeg, "-hide_banner", "-filters"],
        capture_output=True, text=True, check=False, timeout=20,
    )
    if filters.returncode != 0 or "v360" not in filters.stdout:
        pytest.skip("Installed FFmpeg does not provide the v360 filter")

    source = tmp_path / "real-cubemap-3x2.mp4"
    destination = tmp_path / "real-equirectangular.mp4"
    generated = subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=300x200:rate=12:duration=1",
            "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
        ],
        capture_output=True, text=True, check=False, timeout=30,
    )
    assert generated.returncode == 0, generated.stderr

    result = immersive_renderer.render_360_projection(
        source, destination, input_projection="c3x2",
        resolution="1920x960", fps=24, quality=24,
    )

    assert result["success"] is True
    assert result["stage"] == "projection_conversion_only"
    assert result["resolution"] == "1920x960"
    assert result["spherical_metadata_embedded"] is False
    assert result["platform_ready"] is False
    assert destination.is_file() and destination.stat().st_size > 1000

@pytest.mark.parametrize("failure", [OSError("disk unavailable"), subprocess.TimeoutExpired("ffmpeg", 1)])
def test_360_projection_export_removes_partial_output_after_process_failure(
    tmp_path, monkeypatch, failure
):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    destination = tmp_path / "partial.mp4"
    monkeypatch.setattr(immersive_renderer.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run(command, **kwargs):
        if command[0].endswith("ffprobe"):
            return _probe_result(300, 200)
        destination.write_bytes(b"partial output")
        raise failure

    monkeypatch.setattr(immersive_renderer.render_process, "run_render_process", fake_run)
    with pytest.raises(immersive_renderer.ImmersiveRenderError, match="failed or timed out"):
        immersive_renderer.render_360_projection(
            source, destination, input_projection="c3x2"
        )
    assert source.read_bytes() == b"source"
    assert not destination.exists()

