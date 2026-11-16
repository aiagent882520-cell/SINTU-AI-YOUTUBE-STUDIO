import shutil
import subprocess

import pytest
from PIL import Image, ImageChops

from app.animation_2d import _render_scene_frames, render_2d_animation_clips


def test_2d_scene_frames_show_character_motion_and_camera_movement(tmp_path):
    count = _render_scene_frames(
        "पुराने किले के सामने एक यात्री चलता है", 0, 2, 360, 640, tmp_path
    )
    assert count == 24
    first = Image.open(tmp_path / "frame_00000.jpg").convert("RGB")
    middle = Image.open(tmp_path / "frame_00012.jpg").convert("RGB")
    last = Image.open(tmp_path / "frame_00023.jpg").convert("RGB")
    assert ImageChops.difference(first, middle).getbbox() is not None
    assert ImageChops.difference(middle, last).getbbox() is not None


def test_2d_animation_exports_real_mp4_scene_clip_with_camera_motion(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg tools are unavailable")
    clips = render_2d_animation_clips(
        ["एक कार्टून यात्री पुराने किले की ओर चलता है"],
        seconds_per_scene=2, output_dir=tmp_path, resolution="720x1280", fps=24,
    )
    assert len(clips) == 1
    assert clips[0].is_file() and clips[0].stat().st_size > 1000
    probe = subprocess.run(
        [shutil.which("ffprobe"), "-v", "error", "-show_entries",
         "stream=codec_type,width,height", "-show_entries", "format=duration",
         "-of", "json", str(clips[0])],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert probe.returncode == 0
    import json
    metadata = json.loads(probe.stdout)
    video = next(stream for stream in metadata["streams"] if stream["codec_type"] == "video")
    assert video["width"] == 720
    assert video["height"] == 1280
    assert float(metadata["format"]["duration"]) == pytest.approx(2.0, abs=0.2)


@pytest.mark.parametrize("scenes,duration,resolution,fps", [
    ([], 4, "720x1280", 24),
    ([""], 4, "720x1280", 24),
    (["scene"], 1, "720x1280", 24),
    (["scene"], 4, "480x640", 24),
    (["scene"], 4, "720x1280", 25),
])
def test_2d_animation_rejects_invalid_profiles(tmp_path, scenes, duration, resolution, fps):
    with pytest.raises(ValueError):
        render_2d_animation_clips(scenes, duration, tmp_path, resolution, fps)
