"""Exercise generic MP4 export for every format profile at its target aspect ratio.

Only three tiny MP4 fixtures are encoded (one per distinct output profile) and
reused by the 56 formats that advertise generic media assembly. This is not
native generation acceptance for specialized engines.
"""
import pytest
from PIL import Image

from app import video_renderer
from app.format_rendering import format_render_profile
from app.studio_scope import video_formats


FORMAT_ROWS = {row["id"]: row for row in video_formats()}
FORMAT_IDS = tuple(FORMAT_ROWS)
SPECIALIZED_BLOCKED = {"360-video", "vr-video", "ar-video", "virtual-production"}
SMALL_PROFILES = {
    "1080x1920": (160, 284),
    "1080x1080": (160, 160),
    "1920x1080": (284, 160),
}


@pytest.fixture(scope="module")
def generic_render_outputs(tmp_path_factory):
    """Render and fully verify one real tiny MP4 per aspect-ratio profile."""
    ffmpeg = video_renderer.shutil.which("ffmpeg")
    ffprobe = video_renderer.shutil.which("ffprobe")
    assert ffmpeg and ffprobe, "FFmpeg and FFprobe are mandatory for format render acceptance"
    root = tmp_path_factory.mktemp("format-generic-renders")
    previous_dir = video_renderer.OUTPUT_DIR
    previous_profiles = dict(video_renderer.OUTPUT_PROFILES)
    outputs = {}
    try:
        video_renderer.OUTPUT_DIR = root
        video_renderer.OUTPUT_PROFILES = {
            **previous_profiles,
            **SMALL_PROFILES,
        }
        for resolution, (width, height) in SMALL_PROFILES.items():
            image = root / f"scene-{resolution}.png"
            Image.new("RGB", (width, height), (36, 112, 168)).save(image)
            result = video_renderer.render_storyboard(
                f"Format profile {resolution}",
                ["A real visible test scene"],
                seconds_per_scene=2,
                image_paths=[image],
                resolution=resolution,
                fps=24,
                quality="standard",
                transition="cut",
                motion="slow-zoom-in",
            )
            output = root / result["filename"]
            assert output.is_file() and output.stat().st_size > 1000
            verified = video_renderer.verify_publishable_mp4(output)
            assert verified["verified"] is True
            assert verified["resolution"] == f"{width}x{height}"
            assert verified["fps"] == pytest.approx(24, abs=0.1)
            assert verified["video_codec"] == "h264"
            assert verified["visible_frame_count"] >= 1
            outputs[resolution] = {"verified": verified, "render": result}
        yield outputs
    finally:
        video_renderer.OUTPUT_DIR = previous_dir
        video_renderer.OUTPUT_PROFILES = previous_profiles


@pytest.mark.parametrize("format_id", FORMAT_IDS, ids=FORMAT_IDS)
def test_each_format_has_a_real_generic_mp4_output_or_explicit_engine_block(
    format_id, generic_render_outputs
):
    profile = format_render_profile(format_id)
    if format_id in SPECIALIZED_BLOCKED:
        assert profile["generic_export_available"] is False
        assert profile["limitations"]
        return

    assert profile["generic_export_available"] is True
    output = generic_render_outputs[profile["default_resolution"]]
    verified = output["verified"]
    assert output["render"]["brand_watermark"] == "SINTU AI YOUTUBE STUDIO"
    assert output["render"]["subtitles_burned_in"] is False
    expected_size = SMALL_PROFILES[profile["default_resolution"]]
    assert verified["verified"] is True
    assert verified["resolution"] == f"{expected_size[0]}x{expected_size[1]}"
    assert verified["video_codec"] == "h264"
    assert verified["fps"] == pytest.approx(24, abs=0.1)
