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
        return {"returncode": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(media_forensics, "run", fake_run)
    report = media_forensics.inspect_video(video)
    assert report["safe_regular_file"] is True
    assert media_forensics.has_forensic_tool_failure(report) is False
    assert report["frame_probe_exit"] == 0
    assert [item["sample"] for item in report["decoded_frame_samples"]] == [
        "first", "middle", "last"
    ]
    assert [item["timestamp"] for item in report["decoded_frame_samples"]] == [
        "0.000000", "5.000000", "9.958333"
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
        "ffprobe_exit": 0, "blackdetect_exit": 0, "decode_exit": 0,
        "frame_probe_exit": 0,
        "metadata": {"format": "mov,mp4", "duration_seconds": 4.0,
                     "streams": [{"type": "video"}]},
        "decoded_frame_samples": [
            {"sample": "first", "timestamp": "0.0", "error": ""},
            {"sample": "middle", "timestamp": "2.0", "error": ""},
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
