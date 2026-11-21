import shutil
from pathlib import Path
import subprocess

import pytest
from PIL import Image, ImageDraw

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



def test_ai_clip_renderer_uses_configured_mobile_render_timeout(tmp_path, monkeypatch):
    ffmpeg, _ = _ffmpeg_tools()
    monkeypatch.setattr(video_renderer, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(video_renderer, "RENDER_TIMEOUT_SECONDS", 123)
    source = _make_source_clip(tmp_path / "timeout-source.mp4")
    real_run = subprocess.run
    captured = {}

    def recording_run(command, **kwargs):
        if "-filter_complex" in command and str(command[-1]).endswith(".mp4"):
            captured["timeout"] = kwargs.get("timeout")
        return real_run(command, **kwargs)

    monkeypatch.setattr(video_renderer.subprocess, "run", recording_run)
    result = video_renderer.render_ai_clips(
        [source], resolution="720x1280", fps=24, quality="standard", transition="cut",
    )

    assert captured["timeout"] == 123
    assert (tmp_path / result["filename"]).is_file()


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
    monkeypatch.setattr(video_renderer, "_validate_source_video", lambda path: None)
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
    monkeypatch.setattr(video_renderer, "_validate_source_video", lambda path: None)
    monkeypatch.setattr(
        video_renderer.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="10.0", stderr=""),
    )

    item = {"kind": "video", "path": source, **trim}
    with pytest.raises(ValueError, match="finite"):
        video_renderer.render_mixed_timeline([item], "test", ["scene"])


def test_mixed_timeline_preprocessing_honors_mobile_render_timeout(tmp_path, monkeypatch):
    ffmpeg, _ = _ffmpeg_tools()
    source = _make_source_clip(tmp_path / "timeout-mixed-source.mp4")
    still = tmp_path / "timeout-mixed-still.png"
    Image.new("RGB", (160, 284), (180, 80, 30)).save(still)
    monkeypatch.setattr(video_renderer, "OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr(video_renderer, "RENDER_TIMEOUT_SECONDS", 60)
    real_run = subprocess.run
    captured = {}

    def recording_run(command, **kwargs):
        command_text = [str(part) for part in command]
        if command_text and command_text[0] == ffmpeg:
            output_name = command_text[-1]
            if output_name.endswith("trimmed-002.mp4") or output_name.endswith("still-001.mp4"):
                captured[Path(output_name).name] = kwargs.get("timeout")
        return real_run(command, **kwargs)

    monkeypatch.setattr(video_renderer.subprocess, "run", recording_run)
    result = video_renderer.render_mixed_timeline(
        [
            {"kind": "image", "path": still, "duration": 2},
            {"kind": "video", "path": source, "trim_start": 0, "trim_end": 1},
        ],
        "Timeout policy test", ["Still", "Clip"], resolution="720x1280",
        fps=24, quality="standard", transition="cut",
    )

    assert captured == {"still-001.mp4": 60, "trimmed-002.mp4": 60}
    assert (tmp_path / "out" / result["filename"]).is_file()


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


def test_storyboard_renderer_preserves_full_multiscene_timeline_and_voiceover(tmp_path, monkeypatch):
    ffmpeg, _ = _ffmpeg_tools()
    monkeypatch.setattr(video_renderer, "OUTPUT_DIR", tmp_path)
    image_paths = []
    for index, color in enumerate(((30, 80, 120), (90, 40, 20), (20, 110, 70)), start=1):
        image_path = tmp_path / f"scene-{index}.png"
        canvas = Image.new("RGB", (160, 284), color)
        draw = ImageDraw.Draw(canvas)
        contrast = tuple(255 - channel for channel in color)
        for offset in range(0, 180, 20):
            draw.line((offset, 0, 160 - offset // 2, 284), fill=contrast, width=5)
        draw.ellipse((18 + index * 9, 70, 100 + index * 7, 165), outline=(255, 240, 80), width=9)
        draw.rectangle((8, 8, 151, 275), outline=(245, 245, 245), width=5)
        draw.text((16, 18), f"SCENE {index}", fill=(255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0))
        canvas.save(image_path)
        image_paths.append(image_path)

    voice_path = tmp_path / "voice.wav"
    audio = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-c:a", "pcm_s16le", str(voice_path)],
        capture_output=True, check=False, timeout=30,
    )
    assert audio.returncode == 0, audio.stderr.decode("utf-8", "replace")

    result = video_renderer.render_storyboard(
        "Three scene regression", ["Opening", "Middle", "Closing"],
        seconds_per_scene=3, image_paths=image_paths, audio_path=voice_path,
        resolution="720x1280", fps=24, quality="standard", transition="fade",
        motion="slow-zoom-in",
    )

    output = tmp_path / result["filename"]
    assert output.is_file() and output.stat().st_size > 1000
    verified = video_renderer._verify_rendered_output(
        output, 720, 1280, expected_duration=9, require_audio=True, expected_fps=24,
    )
    assert verified["frame_count"] >= 9 * 24 * 0.95
    assert verified["video_duration_seconds"] >= 9 - (2 / 24)
    assert verified["audio"] is True
    assert result["duration_seconds"] == 9

def test_publish_verifier_accepts_real_mp4_and_rejects_corrupt_file(tmp_path):
    ffmpeg, _ = _ffmpeg_tools()
    source = tmp_path / "publishable.mp4"
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "color=c=green:s=720x1280:r=24:d=2",
         "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)],
        capture_output=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    verified = video_renderer.verify_publishable_mp4(source)
    assert verified["verified"] is True
    assert verified["frame_count"] >= 45
    assert verified["fps"] == pytest.approx(24, abs=0.1)
    assert verified["resolution"] == "720x1280"

    corrupt = tmp_path / "corrupt.mp4"
    corrupt.write_bytes(b"not-an-mp4")
    with pytest.raises(video_renderer.RenderFailed, match="corrupt"):
        video_renderer.verify_publishable_mp4(corrupt)




def test_storyboard_renderer_burns_hindi_subtitles_into_final_mp4(tmp_path, monkeypatch):
    ffmpeg, ffprobe = _ffmpeg_tools()
    if not video_renderer._ffmpeg_supports_subtitles(ffmpeg):
        pytest.skip("FFmpeg libass subtitles filter is unavailable")
    monkeypatch.setattr(video_renderer, "OUTPUT_DIR", tmp_path)
    image_path = tmp_path / "scene.png"
    Image.new("RGB", (160, 284), (30, 80, 120)).save(image_path)

    result = video_renderer.render_storyboard(
        "Hindi subtitle test", ["Scene one"], seconds_per_scene=2,
        image_paths=[image_path], subtitles=["नमस्ते दोस्तों, SINTU में आपका स्वागत है।"],
        resolution="720x1280", fps=24, quality="standard", transition="cut",
    )

    output = tmp_path / result["filename"]
    assert output.is_file() and output.stat().st_size > 1000
    assert result["subtitles_burned_in"] is True
    probe = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "stream=codec_type",
         "-of", "csv=p=0", str(output)],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert probe.returncode == 0
    assert "video" in probe.stdout


def test_ai_clip_renderer_burns_timed_subtitles_into_final_mp4(tmp_path, monkeypatch):
    ffmpeg, _ = _ffmpeg_tools()
    if not video_renderer._ffmpeg_supports_subtitles(ffmpeg):
        pytest.skip("FFmpeg libass subtitles filter is unavailable")
    monkeypatch.setattr(video_renderer, "OUTPUT_DIR", tmp_path)
    source = _make_source_clip(tmp_path / "source.mp4")

    result = video_renderer.render_ai_clips(
        [source], subtitles=["यह AI clip का हिंदी subtitle है।"],
        resolution="720x1280", fps=24, quality="standard", transition="cut",
    )

    output = tmp_path / result["filename"]
    assert output.is_file() and output.stat().st_size > 1000
    assert result["subtitles_burned_in"] is True
    assert result["duration_seconds"] == pytest.approx(1.0, abs=0.1)



def test_storyboard_renderer_mixes_procedural_sound_effects(tmp_path, monkeypatch):
    ffmpeg, ffprobe = _ffmpeg_tools()
    monkeypatch.setattr(video_renderer, "OUTPUT_DIR", tmp_path)
    image_paths = []
    for index, color in enumerate(((40, 80, 120), (90, 50, 30))):
        path = tmp_path / f"sfx-scene-{index}.png"
        Image.new("RGB", (160, 284), color).save(path)
        image_paths.append(path)

    result = video_renderer.render_storyboard(
        "SFX integration", ["किले का दरवाज़ा", "रहस्यमयी जंगल की रात"],
        seconds_per_scene=2, image_paths=image_paths,
        sound_effects_enabled=True, sound_effects_volume=0.2,
        resolution="720x1280", fps=24, quality="standard", transition="cut",
    )

    output = tmp_path / result["filename"]
    assert output.is_file() and output.stat().st_size > 1000
    assert result["sound_effects"] is True
    assert result["sound_effect_cue_count"] >= 3
    assert "sound-effects" in result["audio"]
    probe = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "stream=codec_type",
         "-of", "csv=p=0", str(output)],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert probe.returncode == 0
    assert "audio" in probe.stdout



def test_ai_clip_renderer_mixes_procedural_scene_sound_effects(tmp_path, monkeypatch):
    ffmpeg, ffprobe = _ffmpeg_tools()
    monkeypatch.setattr(video_renderer, "OUTPUT_DIR", tmp_path)
    source = _make_source_clip(tmp_path / "source-sfx.mp4")

    result = video_renderer.render_ai_clips(
        [source], scene_descriptions=["किले का भारी दरवाज़ा खुलता है"],
        sound_effects_enabled=True, sound_effects_volume=0.2,
        resolution="720x1280", fps=24, quality="standard", transition="cut",
    )

    output = tmp_path / result["filename"]
    assert output.is_file() and output.stat().st_size > 1000
    assert result["sound_effects"] is True
    assert result["sound_effect_cue_count"] >= 1
    assert "sound-effects" in result["audio"]
    probe = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "stream=codec_type",
         "-of", "csv=p=0", str(output)],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert probe.returncode == 0
    assert "audio" in probe.stdout


def test_storyboard_motion_filter_repeats_camera_move_for_each_scene():
    zoom_in = video_renderer._storyboard_motion_filter(
        "slow-zoom-in", width=720, height=1280, fps=24, seconds_per_scene=4
    )
    assert zoom_in is not None
    assert "mod(on,96)" in zoom_in
    assert "sin(" in zoom_in and "cos(" in zoom_in
    assert "1+0.160" in zoom_in
    assert "0.22" in zoom_in and "0.12" in zoom_in


def test_storyboard_zoom_out_reverses_zoom_direction_and_none_disables_motion():
    zoom_out = video_renderer._storyboard_motion_filter(
        "slow-zoom-out", width=720, height=1280, fps=30, seconds_per_scene=5
    )
    assert zoom_out is not None
    assert "mod(on,150)" in zoom_out
    assert "1.160-0.160" in zoom_out
    assert video_renderer._storyboard_motion_filter(
        "none", width=720, height=1280, fps=24, seconds_per_scene=4
    ) is None


def test_long_storyboard_rejects_static_no_motion_mode(monkeypatch):
    monkeypatch.setattr(video_renderer.shutil, "which", lambda _name: "/usr/bin/ffmpeg")
    with pytest.raises(ValueError, match="static slideshow disabled"):
        video_renderer.render_storyboard(
            "No slideshow", ["Opening", "Middle", "Closing"],
            seconds_per_scene=3, image_paths=[], motion="none",
        )


def test_publish_verifier_rejects_long_frozen_mp4(tmp_path):
    ffmpeg, _ = _ffmpeg_tools()
    source = tmp_path / "frozen-long.mp4"
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "color=c=green:s=720x1280:r=24:d=12",
         "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)],
        capture_output=True, check=False, timeout=60,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    with pytest.raises(video_renderer.RenderFailed, match="slideshow-like"):
        video_renderer.verify_publishable_mp4(source)


def test_two_scene_fade_render_preserves_visible_pixels(tmp_path, monkeypatch):
    """Regression for the old concat + chained per-scene fade graph turning all frames black."""
    _ffmpeg_tools()
    monkeypatch.setattr(video_renderer, "OUTPUT_DIR", tmp_path)
    image_paths = []
    for index, color in enumerate(((220, 80, 40), (30, 180, 120)), start=1):
        path = tmp_path / f"fade-scene-{index}.png"
        canvas = Image.new("RGB", (160, 284), color)
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((12, 12, 148, 272), outline=(255, 255, 255), width=6)
        draw.ellipse((30, 60, 130, 200), fill=(245, 220, 40))
        canvas.save(path)
        image_paths.append(path)

    result = video_renderer.render_storyboard(
        "Two scene fade regression",
        ["Bright opening", "Bright closing"],
        seconds_per_scene=2,
        image_paths=image_paths,
        transition="fade",
        motion="none",
        resolution="720x1280",
        fps=24,
        quality="standard",
    )

    output = tmp_path / result["filename"]
    assert output.is_file() and output.stat().st_size > 1000
    verified = video_renderer._verify_rendered_output(
        output, 720, 1280, expected_duration=4, require_audio=False, expected_fps=24,
    )
    assert verified["frame_count"] >= 96
    assert verified["visible_frame_count"] >= 3
    assert verified["longest_black_segment_seconds"] < 3.8


def test_storyboard_renderer_rejects_missing_scene_images(tmp_path, monkeypatch):
    monkeypatch.setattr(video_renderer, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(video_renderer.shutil, "which", lambda _name: "/usr/bin/ffmpeg")

    def unexpected_ffmpeg(*args, **kwargs):
        raise AssertionError("FFmpeg must not run when scene images are missing")

    monkeypatch.setattr(video_renderer.subprocess, "run", unexpected_ffmpeg)
    with pytest.raises(ValueError, match="real scene image required"):
        video_renderer.render_storyboard(
            "No blank placeholders", ["Opening", "Closing"],
            seconds_per_scene=2, image_paths=[], transition="fade", motion="none",
        )
    assert list(tmp_path.iterdir()) == []



def test_mixed_timeline_mixes_source_voice_music_and_burns_subtitles(tmp_path, monkeypatch):
    """Exercise the complete mixed image/video FFmpeg graph with all audio layers."""
    ffmpeg, ffprobe = _ffmpeg_tools()
    if not video_renderer._ffmpeg_supports_subtitles(ffmpeg):
        pytest.skip("FFmpeg libass subtitles filter is unavailable")
    monkeypatch.setattr(video_renderer, "OUTPUT_DIR", tmp_path)
    # Keep this full FFmpeg graph test CPU-bounded; production portrait dimensions
    # are exercised by the offline end-to-end render job. The graph is under test,
    # not the production encoding preset, so use a tiny frame and ultrafast x264.
    test_profiles = dict(video_renderer.OUTPUT_PROFILES)
    test_profiles["160x284"] = (160, 284)
    monkeypatch.setattr(video_renderer, "OUTPUT_PROFILES", test_profiles)
    monkeypatch.setenv("SINTU_FFMPEG_THREADS", "1")
    monkeypatch.setattr(
        video_renderer, "_render_settings",
        lambda resolution, fps, quality: (160, 284, 35, "ultrafast"),
    )

    source = tmp_path / "source-with-audio.mp4"
    generated = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=size=160x284:rate=12:duration=1.5",
         "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000:duration=1.5",
         "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-ar", "48000", "-ac", "2", str(source)],
        capture_output=True, check=False, timeout=45,
    )
    assert generated.returncode == 0, generated.stderr.decode("utf-8", "replace")

    still = tmp_path / "still.png"
    Image.new("RGB", (160, 284), (180, 80, 30)).save(still)
    voice = tmp_path / "voice.wav"
    music = tmp_path / "music.wav"
    for destination, frequency in ((voice, 660), (music, 220)):
        audio = subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", f"sine=frequency={frequency}:sample_rate=48000:duration=4",
             "-c:a", "pcm_s16le", str(destination)],
            capture_output=True, check=False, timeout=30,
        )
        assert audio.returncode == 0, audio.stderr.decode("utf-8", "replace")

    result = video_renderer.render_mixed_timeline(
        [
            {"kind": "image", "path": still, "duration": 2},
            {"kind": "video", "path": source, "trim_start": 0.1, "trim_end": 1.4,
             "audio_volume": 0.35},
        ],
        "Full mixed timeline",
        ["Opening scene", "Moving scene"],
        audio_path=voice,
        music_path=music,
        music_volume=0.12,
        subtitles=["पहला दृश्य", "दूसरा दृश्य"],
        transitions=["cut", "fade"],
        resolution="160x284",
        fps=12,
        quality="standard",
    )

    output = tmp_path / result["filename"]
    assert output.is_file() and output.stat().st_size > 1000
    assert result["timeline_order"] == ["image", "video"]
    assert result["scene_durations"] == [2, 1.3]
    assert result["subtitles_burned_in"] is True
    assert result["audio"] == "source+voiceover+music"
    metadata = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries",
         "stream=codec_type,codec_name,sample_rate,channels,width,height,r_frame_rate",
         "-of", "json", str(output)],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert metadata.returncode == 0, metadata.stderr
    import json
    streams = json.loads(metadata.stdout)["streams"]
    video_streams = [stream for stream in streams if stream["codec_type"] == "video"]
    assert len(video_streams) == 1
    assert (video_streams[0]["width"], video_streams[0]["height"]) == (160, 284)
    assert video_streams[0]["r_frame_rate"] == "12/1"
    audio_streams = [stream for stream in streams if stream["codec_type"] == "audio"]
    assert len(audio_streams) == 1
    assert audio_streams[0]["codec_name"] == "aac"
    assert audio_streams[0]["sample_rate"] == "48000"
    assert audio_streams[0]["channels"] == 2

    measured = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(output), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert measured.returncode == 0, measured.stderr
    assert "mean_volume: -inf dB" not in measured.stderr


def test_render_verifier_rejects_audio_video_duration_drift(tmp_path):
    ffmpeg, _ = _ffmpeg_tools()
    mismatched = tmp_path / "audio-shorter-than-video.mp4"
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=24:duration=2",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-ar", "48000", "-ac", "2", "-t", "2", str(mismatched)],
        capture_output=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    with pytest.raises(video_renderer.RenderFailed, match="not synchronized"):
        video_renderer._verify_rendered_output(
            mismatched, 320, 240, expected_duration=2,
            require_audio=True, expected_fps=24,
        )


def test_render_verifier_reports_synchronized_audio_video_durations(tmp_path):
    ffmpeg, _ = _ffmpeg_tools()
    matched = tmp_path / "audio-matches-video.mp4"
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=24:duration=2",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-ar", "48000", "-ac", "2", "-t", "2", str(matched)],
        capture_output=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    verified = video_renderer._verify_rendered_output(
        matched, 320, 240, expected_duration=2,
        require_audio=True, expected_fps=24,
    )
    assert verified["verified"] is True
    assert abs(verified["audio_duration_seconds"] - verified["video_duration_seconds"]) <= 0.5


def test_publish_verifier_rejects_unsynchronized_audio_track(tmp_path):
    ffmpeg, _ = _ffmpeg_tools()
    mismatched = tmp_path / "publish-audio-drift.mp4"
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=size=720x1280:rate=24:duration=2",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-ar", "48000", "-ac", "2", "-t", "2", str(mismatched)],
        capture_output=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    with pytest.raises(video_renderer.RenderFailed, match="not synchronized"):
        video_renderer.verify_publishable_mp4(mismatched)

def test_portrait_hindi_subtitles_wrap_to_safe_width(tmp_path, monkeypatch):
    monkeypatch.setattr(video_renderer, "_ffmpeg_supports_subtitles", lambda _ffmpeg: True)
    subtitle_path, subtitle_filter = video_renderer._create_subtitle_track(
        tmp_path,
        ["कुंभलगढ़: अरावली पर लगभग 36 किलोमीटर लंबी दीवार।"],
        [4.0],
        720,
        1280,
        "ffmpeg",
    )
    assert subtitle_path is not None
    assert subtitle_filter and "subtitles=" in subtitle_filter
    caption_lines = [
        line for line in subtitle_path.read_text(encoding="utf-8").splitlines()
        if line and not line.isdigit() and "-->" not in line
    ]
    assert len(caption_lines) >= 2
    assert max(map(len, caption_lines)) <= 21

