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
