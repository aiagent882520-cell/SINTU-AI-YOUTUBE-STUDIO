"""Pixel-level regression tests for Hindi documentary subtitle rendering."""
import shutil

import pytest

from app.documentary_qa import audit_subtitle_pixel_bounds
from app.video_renderer import _ffmpeg_supports_subtitles


def test_hindi_subtitles_stay_inside_rendered_pixel_safe_area():
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or not _ffmpeg_supports_subtitles(ffmpeg):
        pytest.skip("FFmpeg libass subtitle filter is unavailable.")

    report = audit_subtitle_pixel_bounds(
        [
            "कुंभलगढ़: अरावली पर लगभग 36 किलोमीटर लंबी दीवार।",
            "इतिहास, स्थापत्य और लोककथाओं को प्रमाणों से अलग पहचानें।",
        ],
        [4.0, 4.0],
        720,
        1280,
    )

    assert report["passed"] is True
    assert report["cue_count"] == 2
    assert all(cue["pixel_bounds"][0] >= cue["safe_x_bounds"][0] for cue in report["cues"])
    assert all(cue["pixel_bounds"][2] - 1 <= cue["safe_x_bounds"][1] for cue in report["cues"])
    assert all(cue["pixel_bounds"][1] >= cue["safe_y_bounds"][0] for cue in report["cues"])
    assert all(cue["pixel_bounds"][3] - 1 <= cue["safe_y_bounds"][1] for cue in report["cues"])


def test_subtitle_pixel_audit_rejects_vertical_clipping():
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or not _ffmpeg_supports_subtitles(ffmpeg):
        pytest.skip("FFmpeg libass subtitle filter is unavailable.")

    long_subtitle = "इतिहास " * 130
    with pytest.raises(AssertionError, match="safe pixel area"):
        audit_subtitle_pixel_bounds([long_subtitle], [4.0], 720, 1280)


def test_subtitle_pixel_audit_rejects_empty_cue():
    with pytest.raises(ValueError, match="empty"):
        audit_subtitle_pixel_bounds([""], [4.0], 720, 1280)
