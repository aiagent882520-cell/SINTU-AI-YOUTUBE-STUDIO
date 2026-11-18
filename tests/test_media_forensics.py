import json
from scripts import media_forensics
from scripts.media_forensics import parse_black_intervals, redact_secrets


def test_black_interval_parser_preserves_time_ranges():
    assert parse_black_intervals(
        "black_start:0 black_end:4.041667 black_start:7.0 black_end:8.0"
    ) == [[0.0, 4.041667], [7.0, 8.0]]


def test_forensic_output_redacts_bearer_tokens_and_session_urls():
    value = (
        "Authorization: Bearer abc.def.secret "
        "access_token=private-value session_uri=https://example.test/private-session "
        "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=private-session"
    )
    redacted = redact_secrets(value)
    assert "abc.def.secret" not in redacted
    assert "private-value" not in redacted
    assert "private-session" not in redacted
    assert "[REDACTED]" in redacted
    assert "[REDACTED_GOOGLE_UPLOAD_SESSION]" in redacted

def test_forensics_measures_nearby_source_image_brightness(tmp_path, monkeypatch):
    from PIL import Image

    monkeypatch.setattr(media_forensics, "DATA_DIR", tmp_path)
    images = tmp_path / "generated_images"
    images.mkdir()
    black = images / "black.jpg"
    visible = images / "visible.jpg"
    Image.new("RGB", (64, 64), (0, 0, 0)).save(black)
    Image.new("RGB", (64, 64), (180, 120, 60)).save(visible)
    black_stats = media_forensics.inspect_asset(black)
    visible_stats = media_forensics.inspect_asset(visible)
    assert black_stats["near_black"] is True
    assert visible_stats["near_black"] is False
    assert black_stats["mean_luma"] < visible_stats["mean_luma"]

def test_forensics_prefers_pre_repair_backup_mtime_for_asset_correlation(tmp_path, monkeypatch):
    import os
    from datetime import datetime, timezone

    monkeypatch.setattr(media_forensics, "DATA_DIR", tmp_path)
    original = tmp_path / "generated_videos" / "clip.mp4"
    backup = tmp_path / "media_backups" / "repair-1" / "clip.mp4"
    original.parent.mkdir()
    backup.parent.mkdir(parents=True)
    original.write_bytes(b"repaired")
    backup.write_bytes(b"original")
    original_time = 1_700_000_000
    os.utime(backup, (original_time, original_time))
    result = media_forensics.find_backups(original)
    assert len(result) == 1
    assert result[0]["sha256"] == media_forensics.sha256_file(backup)
    assert datetime.fromisoformat(result[0]["pre_repair_mtime_utc"]).timestamp() == original_time


def test_frame_samples_use_independent_timestamp_probes(tmp_path, monkeypatch):
    calls = []

    def fake_run(command, timeout=120):
        calls.append(command)
        seek = command[command.index("-read_intervals") + 1].split("%", 1)[0]
        return {
            "returncode": 0,
            "stdout": json.dumps({"frames": [{
                "best_effort_timestamp_time": seek, "pict_type": "P"
            }]}),
            "stderr": "",
        }

    monkeypatch.setattr(media_forensics, "run", fake_run)
    path = tmp_path / "clip.mp4"
    samples = [
        media_forensics.sample_decoded_frame(path, 0.0, "first"),
        media_forensics.sample_decoded_frame(path, 5.0, "middle"),
        media_forensics.sample_decoded_frame(path, 9.9, "last"),
    ]
    assert [sample["sample"] for sample in samples] == ["first", "middle", "last"]
    assert [sample["seek_seconds"] for sample in samples] == [0.0, 5.0, 9.9]
    assert [sample["timestamp"] for sample in samples] == ["0.000000", "5.000000", "9.900000"]
    assert len(calls) == 3
    assert [calls[i][calls[i].index("-read_intervals") + 1] for i in range(3)] == [
        "0.000000%+1", "5.000000%+1", "9.900000%+1"
    ]


def test_frame_sample_reports_missing_frame_without_failing_report(tmp_path, monkeypatch):
    monkeypatch.setattr(media_forensics, "run", lambda *args, **kwargs: {
        "returncode": 0, "stdout": '{"frames":[]}', "stderr": ""
    })
    sample = media_forensics.sample_decoded_frame(tmp_path / "clip.mp4", 2.0, "middle")
    assert sample["timestamp"] is None
    assert sample["error"] == "no decoded frame found at requested timestamp"


def test_frame_sample_selects_frame_closest_to_requested_timestamp(tmp_path, monkeypatch):
    monkeypatch.setattr(media_forensics, "run", lambda *args, **kwargs: {
        "returncode": 0,
        "stdout": '{"frames":['
                  '{"best_effort_timestamp_time":"4.958333","pict_type":"P"},'
                  '{"best_effort_timestamp_time":"5.000000","pict_type":"B"},'
                  '{"best_effort_timestamp_time":"5.041667","pict_type":"P"}]}',
        "stderr": "",
    })
    sample = media_forensics.sample_decoded_frame(tmp_path / "clip.mp4", 5.02, "middle")
    assert sample["timestamp"] == "5.041667"
    assert sample["picture_type"] == "P"


def test_inspect_video_builds_report_from_three_frame_probes(tmp_path, monkeypatch):
    import json

    monkeypatch.setattr(media_forensics, "DATA_DIR", tmp_path)
    media_dir = tmp_path / "generated_videos"
    media_dir.mkdir()
    video = media_dir / "sample.mp4"
    video.write_bytes(b"sample video bytes")

    def fake_run(command, timeout=120):
        if command[0] == "ffprobe" and "-count_frames" in command:
            return {"returncode": 0, "stdout": json.dumps({
                "format": {"format_name": "mov,mp4", "duration": "10.0"},
                "streams": [{"codec_type": "video", "codec_name": "h264",
                             "width": 720, "height": 1280, "pix_fmt": "yuv420p",
                             "avg_frame_rate": "24/1", "nb_read_frames": "240"}],
            }), "stderr": ""}
        if command[0] == "ffprobe" and "-read_intervals" in command:
            seek = command[command.index("-read_intervals") + 1].split("%", 1)[0]
            return {"returncode": 0, "stdout": json.dumps({
                "frames": [{"best_effort_timestamp_time": seek, "pict_type": "P"}]
            }), "stderr": ""}
        if command[0] == "ffmpeg" and "blackdetect=d=0.10:pix_th=0.10" in command:
            return {"returncode": 0, "stdout": "", "stderr": ""}
        if command[0] == "ffmpeg" and any("blackframe=" in part for part in command):
            return {"returncode": 0, "stdout": "", "stderr": "pblack:0\npblack:0\npblack:0"}
        return {"returncode": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(media_forensics, "run", fake_run)
    report = media_forensics.inspect_video(video)
    assert report["safe_regular_file"] is True
    assert media_forensics.has_forensic_tool_failure(report) is False
    assert report["frame_probe_exit"] == 0
    assert [item["sample"] for item in report["decoded_frame_samples"]] == [
        "first", "quarter", "middle", "three_quarter", "last"
    ]
    assert [item["timestamp"] for item in report["decoded_frame_samples"]] == [
        "0.000000", "2.500000", "5.000000", "7.500000", "9.958333"
    ]


def test_frame_sample_rejects_only_preceding_keyframe_results(tmp_path, monkeypatch):
    monkeypatch.setattr(media_forensics, "run", lambda *args, **kwargs: {
        "returncode": 0,
        "stdout": '{"frames":[{"best_effort_timestamp_time":"4.000000","pict_type":"I"}]}',
        "stderr": "",
    })
    sample = media_forensics.sample_decoded_frame(tmp_path / "clip.mp4", 5.0, "middle")
    assert sample["timestamp"] is None
    assert sample["error"] == "no decoded frame at or after the requested timestamp"


def test_forensic_tool_failure_is_not_hidden_by_existing_video_file():
    good = {
        "exists": True, "safe_regular_file": True,
        "ffprobe_exit": 0, "blackdetect_exit": 0, "blackframe_exit": 0,
        "decode_exit": 0, "frame_probe_exit": 0,
        "black_frame_metrics": {"sampled_frame_count": 5},
        "metadata": {"format": "mov,mp4", "duration_seconds": 4.0,
                     "streams": [{"type": "video"}]},
        "decoded_frame_samples": [
            {"sample": "first", "timestamp": "0.0", "error": ""},
            {"sample": "quarter", "timestamp": "1.0", "error": ""},
            {"sample": "middle", "timestamp": "2.0", "error": ""},
            {"sample": "three_quarter", "timestamp": "3.0", "error": ""},
            {"sample": "last", "timestamp": "3.9", "error": ""},
        ],
        "full_duration_black": True,
    }
    assert media_forensics.has_forensic_tool_failure(good) is False
    broken_probe = {**good, "ffprobe_exit": 1}
    assert media_forensics.has_forensic_tool_failure(broken_probe) is True
    missing_sample = {**good, "decoded_frame_samples": good["decoded_frame_samples"][:2]}
    assert media_forensics.has_forensic_tool_failure(missing_sample) is True


def test_av_sync_reports_start_and_end_offsets():
    report = media_forensics.analyze_av_sync([
        {"type": "video", "start_time": "0.000000", "duration": "10.0"},
        {"type": "audio", "start_time": "0.040000", "duration": "9.96"},
    ])
    assert report["status"] == "within_tolerance"
    assert report["audio_minus_video_start_seconds"] == 0.04
    assert report["audio_minus_video_end_seconds"] == 0.0
    assert "not perceptual" in report["method"]


def test_av_sync_flags_out_of_tolerance_and_missing_audio():
    out_of_sync = media_forensics.analyze_av_sync([
        {"type": "video", "start_time": "0", "duration": "10"},
        {"type": "audio", "start_time": "0.8", "duration": "10"},
    ])
    assert out_of_sync["status"] == "out_of_sync"
    assert media_forensics.analyze_av_sync([
        {"type": "video", "start_time": "0", "duration": "10"}
    ])["status"] == "missing_audio_stream"


def test_av_sync_does_not_assume_missing_start_timestamps_are_zero():
    report = media_forensics.analyze_av_sync([
        {"type": "video", "duration": "10.0"},
        {"type": "audio", "duration": "10.0"},
    ])
    assert report["status"] == "insufficient_stream_timing_metadata"


def test_frame_sample_falls_back_to_sequential_decode_after_inaccurate_seek(tmp_path, monkeypatch):
    calls = []

    def fake_run(command, timeout=120):
        calls.append((command, timeout))
        if len(calls) == 1:
            return {
                "returncode": 0,
                "stdout": '{"frames":[{"best_effort_timestamp_time":"0.000000","pict_type":"I"}]}',
                "stderr": "",
            }
        assert command[command.index("-read_intervals") + 1] == "0%+6.000000"
        return {
            "returncode": 0,
            "stdout": '{"frames":['
                      '{"best_effort_timestamp_time":"4.958333","pict_type":"P"},'
                      '{"best_effort_timestamp_time":"5.041667","pict_type":"B"}]}',
            "stderr": "",
        }

    monkeypatch.setattr(media_forensics, "run", fake_run)
    sample = media_forensics.sample_decoded_frame(tmp_path / "clip.mp4", 5.0, "middle")
    assert sample["timestamp"] == "5.041667"
    assert sample["picture_type"] == "B"
    assert sample["sampling_method"] == "sequential_fallback_from_start"
    assert sample["error"] == ""
    assert len(calls) == 2
    assert calls[1][1] == 120


def test_real_ffprobe_inaccurate_seek_recovers_with_sequential_fallback(tmp_path):
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        import pytest
        pytest.skip("FFmpeg and FFprobe are required for the real seek regression")
    clip = tmp_path / "long-gop.mp4"
    created = subprocess.run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=s=160x120:r=30:d=6",
        "-an", "-c:v", "mpeg4", "-g", "150", "-bf", "0", str(clip),
    ], capture_output=True, timeout=60, check=False)
    if created.returncode != 0:
        import pytest
        pytest.skip("FFmpeg build does not provide the MPEG-4 test encoder")
    sample = media_forensics.sample_decoded_frame(clip, 2.0, "middle")
    assert sample["timestamp"] is not None
    assert float(sample["timestamp"]) >= 1.999
    assert sample["sampling_method"] == "sequential_fallback_from_start"
    assert sample["error"] == ""



def test_compact_forensic_summary_preserves_per_file_evidence_for_relay_tail():
    report = {
        "status": "READ_ONLY_FORENSICS",
        "summary": {"target_count": 1, "forensic_tool_failure_count": 1},
        "targets": [{
            "file": "clip.mp4", "exists": True, "size_bytes": 1234,
            "sha256": "a" * 64, "metadata": {
                "duration_seconds": 4.0,
                "streams": [{"type": "video", "codec": "h264", "resolution": "720x1280",
                             "pixel_format": "yuv420p", "frame_rate": "24/1",
                             "frame_count": "96"}],
            },
            "full_duration_black": True, "black_intervals": [[0.0, 4.0]],
            "decode_exit": 0, "frame_probe_exit": 1,
            "decoded_frame_samples": [{
                "sample": "middle", "seek_seconds": 2.0, "timestamp": None,
                "picture_type": None, "sampling_method": "independent_seek",
                "error": "no decoded frame at or after the requested timestamp",
            }],
            "pre_repair_backups": [{"path": "media_backups/clip.mp4",
                                    "size_bytes": 1000, "sha256": "b" * 64}],
            "asset_reference_time_utc": "2026-11-13T00:00:00+00:00",
        }],
        "candidate_source_assets": [{"path": "generated_images/source.jpg",
                                     "size_bytes": 999, "mean_luma": 100.0}],
        "production_log_matches": [{"path": "logs/render.log", "line": 12,
                                     "excerpt": "renderer exit=1"}],
        "production_database_matches": [{"db": "production_runtime.sqlite3",
                                         "table": "production_runs", "column": "result_json",
                                         "record": {"status": "failed"}}],
        "safety": {"files_modified": False, "files_deleted": False},
    }
    footer = media_forensics.compact_forensic_summary(report)
    assert footer["targets"][0]["file"] == "clip.mp4"
    assert footer["targets"][0]["sha256"] == "a" * 64
    assert footer["targets"][0]["black_intervals"] == [[0.0, 4.0]]
    assert footer["targets"][0]["samples"][0]["error"]
    assert footer["targets"][0]["backups"][0]["sha256"] == "b" * 64
    assert footer["candidate_source_assets"][0]["path"] == "generated_images/source.jpg"
    import json as json_module
    assert len(json_module.dumps(footer, separators=(",", ":"))) < 8000



def test_inspect_video_fails_closed_on_non_finite_duration(tmp_path, monkeypatch):
    monkeypatch.setattr(media_forensics, "DATA_DIR", tmp_path)
    media_dir = tmp_path / "generated_videos"
    media_dir.mkdir()
    video = media_dir / "invalid-duration.mp4"
    video.write_bytes(b"not-used-by-mocked-probes")
    calls = []

    def fake_run(command, timeout=120):
        calls.append(command)
        if command[0] == "ffprobe" and "-count_frames" in command:
            return {"returncode": 0, "stdout": json.dumps({
                "format": {"format_name": "mov,mp4", "duration": "nan"},
                "streams": [{"codec_type": "video", "avg_frame_rate": "24/1"}],
            }), "stderr": ""}
        if command[0] == "ffmpeg":
            return {"returncode": 0, "stdout": "", "stderr": ""}
        raise AssertionError("Frame sampling must not run with an invalid duration")

    monkeypatch.setattr(media_forensics, "run", fake_run)
    report = media_forensics.inspect_video(video)
    assert report["frame_probe_exit"] == 1
    assert all("invalid or missing video duration" in x["error"]
               for x in report["decoded_frame_samples"])
    assert media_forensics.has_forensic_tool_failure(report) is True
    assert report["metadata"]["duration_seconds"] is None
    json.dumps(report, allow_nan=False)
    assert not any("-read_intervals" in command for command in calls)


def test_forensic_run_reports_missing_binary_and_timeout(tmp_path, monkeypatch):
    import subprocess

    monkeypatch.setattr(media_forensics.subprocess, "run",
                        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("ffprobe missing")))
    missing = media_forensics.run(["ffprobe", "-version"])
    assert missing["returncode"] is None
    assert "ffprobe missing" in missing["stderr"]

    monkeypatch.setattr(media_forensics.subprocess, "run",
                        lambda *args, **kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired("ffprobe", 1)))
    timed_out = media_forensics.run(["ffprobe", "-version"], timeout=1)
    assert timed_out["returncode"] is None
    assert "timed out" in timed_out["stderr"].lower()



def test_blackframe_parser_and_percentage_summary():
    values = media_forensics.parse_black_frame_percentages(
        "[Parsed_blackframe] frame:0 pblack:100 pts:0 "
        "[Parsed_blackframe] frame:1 pblack:100 pts:1 "
        "[Parsed_blackframe] frame:2 pblack:0 pts:2 "
        "[Parsed_blackframe] frame:3 pblack:20 pts:3"
    )
    assert values == [100, 100, 0, 20]
    metrics = media_forensics.summarize_black_frame_percentages(values)
    assert metrics["sampled_frame_count"] == 4
    assert metrics["black_frame_count"] == 2
    assert metrics["black_frame_percentage"] == 50.0
    assert metrics["mean_black_pixel_percentage"] == 55.0



def test_real_black_mp4_forensics_reports_black_percentage_and_five_samples(tmp_path, monkeypatch):
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        import pytest
        pytest.skip("FFmpeg and FFprobe are required for the real forensic integration")
    monkeypatch.setattr(media_forensics, "DATA_DIR", tmp_path)
    media_dir = tmp_path / "generated_videos"
    media_dir.mkdir()
    clip = media_dir / "black.mp4"
    created = subprocess.run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=black:s=160x120:r=24:d=4",
        "-an", "-c:v", "mpeg4", "-g", "150", "-bf", "0", str(clip),
    ], capture_output=True, timeout=60, check=False)
    if created.returncode != 0:
        import pytest
        pytest.skip("FFmpeg build does not provide the MPEG-4 test encoder")
    report = media_forensics.inspect_video(clip)
    assert report["full_duration_black"] is True
    assert report["black_frame_metrics"]["sampled_frame_count"] == 30
    assert report["black_frame_metrics"]["black_frame_count"] == 30
    assert report["black_frame_metrics"]["black_frame_percentage"] == 100.0
    assert [sample["sample"] for sample in report["decoded_frame_samples"]] == [
        "first", "quarter", "middle", "three_quarter", "last"
    ]
    assert media_forensics.has_forensic_tool_failure(report) is False
