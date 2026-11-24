import json
import shutil
import subprocess

import pytest
from PIL import ImageChops

from app.documentary_animation import (
    _render_frame,
    classify_scene,
    render_documentary_animation_clips,
)


@pytest.mark.parametrize(
    "description,expected",
    [
        ("Animated map route across the region", "map"),
        ("Timeline of events from 1857 to 1947", "timeline"),
        ("Diagram comparing industrial output", "diagram"),
        ("A soldier walks through the fort", "character"),
        ("Storm clouds over a coastal fort", "environment"),
    ],
)
def test_documentary_scene_classifier_selects_distinct_visual_grammar(description, expected):
    assert classify_scene(description) == expected


@pytest.mark.parametrize("kind", ["map", "timeline", "diagram", "character", "environment"])
def test_each_documentary_visual_type_has_real_frame_to_frame_motion(kind):
    frames = [
        _render_frame("documentary scene", kind, 0, progress, (360, 640))
        for progress in (0.0, 0.5, 1.0)
    ]
    assert ImageChops.difference(frames[0], frames[1]).getbbox() is not None
    assert ImageChops.difference(frames[1], frames[2]).getbbox() is not None


def test_documentary_animation_exports_real_scene_mp4s_and_motion_report(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg and FFprobe are required")
    clips, report = render_documentary_animation_clips(
        [
            "Animated map route from Delhi to Agra",
            "Timeline of events in the 19th century",
            "Diagram comparing the two systems",
            "A leader walks through the historic city",
            "Storm clouds over the river and fort",
        ],
        seconds_per_scene=2,
        output_dir=tmp_path,
        resolution="360x640",
        fps=24,
    )
    assert len(clips) == 5
    assert report["all_scenes_animated"] is True
    assert report["map_geometry"] == "schematic_not_geospatial"
    assert [item["visual_type"] for item in report["scenes"]] == [
        "map", "timeline", "diagram", "character", "environment"
    ]
    for clip, evidence in zip(clips, report["scenes"]):
        assert clip.is_file() and clip.stat().st_size > 1000
        assert evidence["motion_verified"] is True
        assert evidence["camera_move"] == "slow_push_with_alternating_track"
        probe = subprocess.run(
            [shutil.which("ffprobe"), "-v", "error", "-show_entries",
             "stream=codec_type,width,height,pix_fmt,color_range", "-show_entries", "format=duration",
             "-of", "json", str(clip)],
            capture_output=True, text=True, timeout=30, check=False,
        )
        assert probe.returncode == 0, probe.stderr
        metadata = json.loads(probe.stdout)
        video = next(x for x in metadata["streams"] if x["codec_type"] == "video")
        assert (video["width"], video["height"]) == (360, 640)
        assert video["pix_fmt"] == "yuv420p"
        assert video["color_range"] in {"tv", "mpeg"}
        assert evidence["pixel_format"] == "yuv420p"
        assert evidence["color_range"] in {"tv", "mpeg"}
        assert float(metadata["format"]["duration"]) == pytest.approx(2.0, abs=0.2)
    saved = json.loads((tmp_path / "documentary-animation-report.json").read_text())
    assert saved["all_scenes_animated"] is True


@pytest.mark.parametrize(
    "scenes,duration,resolution,fps",
    [
        ([], 2, "360x640", 24),
        ([""], 2, "360x640", 24),
        (["map"], 1, "360x640", 24),
        (["map"], 2, "480x640", 24),
        (["map"], 2, "360x640", 25),
    ],
)
def test_documentary_animation_rejects_invalid_profiles(tmp_path, scenes, duration, resolution, fps):
    with pytest.raises(ValueError):
        render_documentary_animation_clips(scenes, duration, tmp_path, resolution, fps)
