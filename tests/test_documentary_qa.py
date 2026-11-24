"""Pixel-level regression tests for Hindi documentary subtitle rendering."""
import shutil
import subprocess

import pytest

from app.documentary_qa import audit_audio_quality, audit_subtitle_pixel_bounds, audit_visual_scene_content
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



def test_audio_quality_audit_measures_integrated_loudness_and_true_peak(tmp_path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg is unavailable.")
    output = tmp_path / "audio-quality.mp4"
    rendered = subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=navy:s=160x284:r=24:d=3",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-c:a", "aac", "-ar", "48000", "-ac", "2", "-shortest",
            str(output),
        ],
        capture_output=True, text=True, timeout=45, check=False,
    )
    assert rendered.returncode == 0, rendered.stderr
    report = audit_audio_quality(output)
    assert report["passed"] is True
    assert -18.0 <= report["integrated_lufs"] <= -14.0
    assert report["true_peak_dbfs"] <= -1.0


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


def test_visual_scene_audit_accepts_full_frame_color_scene_art(tmp_path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg is unavailable.")
    output = tmp_path / "color-scene.mp4"
    rendered = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "color=c=navy:s=160x284:r=24:d=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(output)],
        capture_output=True, text=True, timeout=45, check=False,
    )
    assert rendered.returncode == 0, rendered.stderr
    report = audit_visual_scene_content(output)
    assert report["passed"] is True
    assert report["scene_frames_passed"] == report["sampled_frames"]


def test_visual_scene_audit_rejects_black_text_card(tmp_path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg is unavailable.")
    output = tmp_path / "black-text-card.mp4"
    rendered = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "color=c=black:s=160x284:r=24:d=3", "-vf",
         "drawbox=x=40:y=120:w=80:h=20:color=white:t=fill", "-c:v", "libx264",
         "-pix_fmt", "yuv420p", str(output)],
        capture_output=True, text=True, timeout=45, check=False,
    )
    assert rendered.returncode == 0, rendered.stderr
    with pytest.raises(AssertionError, match="black frames.*text-only visuals"):
        audit_visual_scene_content(output)
