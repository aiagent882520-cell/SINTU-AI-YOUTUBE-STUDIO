import shutil
import subprocess

import pytest
from PIL import Image

from app import video_renderer


def _ffmpeg_tools():
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg and FFprobe are required for renderer integration tests")
    return ffmpeg, ffprobe


def _make_source_clip(path):
    ffmpeg, _ = _ffmpeg_tools()
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "color=c=blue:s=160x284:r=12:d=1",
         "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        capture_output=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    return path


def test_storyboard_renderer_creates_verified_watermarked_mp4(tmp_path, monkeypatch):
    _ffmpeg_tools()
    monkeypatch.setattr(video_renderer, "OUTPUT_DIR", tmp_path)
    image_path = tmp_path / "scene.png"
    Image.new("RGB", (160, 284), (30, 80, 120)).save(image_path)

    result = video_renderer.render_storyboard(
        "Test", ["Scene one"], seconds_per_scene=2, image_paths=[image_path],
        resolution="720x1280", fps=24, quality="standard", transition="cut",
    )

    output = tmp_path / result["filename"]
    assert output.is_file() and output.stat().st_size > 1000
    assert result["brand_watermark"] == "SINTU AI YOUTUBE STUDIO"
    assert result["subtitles_burned_in"] is False
    assert result["resolution"] == "720x1280"


def test_ai_clip_renderer_creates_verified_final_mp4(tmp_path, monkeypatch):
    _ffmpeg_tools()
    monkeypatch.setattr(video_renderer, "OUTPUT_DIR", tmp_path)
    source = _make_source_clip(tmp_path / "source.mp4")

    result = video_renderer.render_ai_clips(
        [source], resolution="720x1280", fps=24, quality="standard", transition="cut",
    )

    output = tmp_path / result["filename"]
    assert output.is_file() and output.stat().st_size > 1000
    assert result["brand_watermark"] == "SINTU AI YOUTUBE STUDIO"
    assert result["subtitles_burned_in"] is False
    assert result["resolution"] == "720x1280"
    assert result["duration_seconds"] == pytest.approx(1.0, abs=0.1)



@pytest.mark.parametrize("duration", ["nan", "inf", "-inf"])
def test_ai_clip_renderer_rejects_non_finite_source_duration(tmp_path, monkeypatch, duration):
    from types import SimpleNamespace

    source = tmp_path / "source.mp4"
    source.write_bytes(b"not-probed-because-metadata-is-mocked")
    monkeypatch.setattr(video_renderer.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        video_renderer.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout='{"format":{"duration":"' + duration + '"},"streams":[{"codec_type":"video"}]}',
            stderr="",
        ),
    )

    with pytest.raises(ValueError, match="finite"):
        video_renderer.render_ai_clips([source])


@pytest.mark.parametrize("trim", [
    {"trim_start": float("nan")},
    {"trim_start": float("inf")},
    {"trim_end": float("nan")},
    {"trim_end": float("inf")},
])
def test_mixed_timeline_rejects_non_finite_trim_values(tmp_path, monkeypatch, trim):
    from types import SimpleNamespace

    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    monkeypatch.setattr(video_renderer.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        video_renderer.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="10.0", stderr=""),
    )

    item = {"kind": "video", "path": source, **trim}
    with pytest.raises(ValueError, match="finite"):
        video_renderer.render_mixed_timeline([item], "test", ["scene"])

def test_mixed_timeline_renders_ordered_still_and_video_items(tmp_path, monkeypatch):
    _ffmpeg_tools()
    monkeypatch.setattr(video_renderer, "OUTPUT_DIR", tmp_path)
    image_path = tmp_path / "still.png"
    Image.new("RGB", (160, 284), (180, 80, 30)).save(image_path)
    source = _make_source_clip(tmp_path / "source.mp4")

    result = video_renderer.render_mixed_timeline(
        [
            {"kind": "image", "path": image_path, "duration": 2},
            {"kind": "video", "path": source, "trim_start": 0, "trim_end": 1},
        ],
        "Mixed timeline",
        ["Still scene", "Video scene"],
        resolution="720x1280",
        fps=24,
        quality="standard",
        transition="cut",
    )

    output = tmp_path / result["filename"]
    assert output.is_file() and output.stat().st_size > 1000
    assert result["timeline_order"] == ["image", "video"]
    assert result["timeline_items"] == 2
    assert result["brand_watermark"] == "SINTU AI YOUTUBE STUDIO"
    assert result["subtitles_burned_in"] is False
    assert result["duration_seconds"] == pytest.approx(3.0, abs=0.15)
