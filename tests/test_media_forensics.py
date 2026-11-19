import json
from pathlib import Path
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
    def fake_run(command, timeout=120):
        interval = command[command.index("-read_intervals") + 1]
        return {
            "returncode": 0,
            "stdout": '{"frames":[]}' if not interval.startswith("0%+") else "",
            "stderr": "",
        }

    monkeypatch.setattr(media_forensics, "run", fake_run)
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


def test_inspect_video_builds_report_from_five_frame_probes(tmp_path, monkeypatch):
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
            return {"returncode": 0, "stdout": "", "stderr": "pblack:0\n" * 30}
        if command[0] == "ffmpeg" and any("scale=64:64:flags=area" in part for part in command):
            media_forensics.Image.new("RGB", (64, 64), "white").save(command[-1])
            return {"returncode": 0, "stdout": "", "stderr": ""}
        return {"returncode": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(media_forensics, "run", fake_run)
    report = media_forensics.inspect_video(video)
    assert report["safe_regular_file"] is True
    assert media_forensics.has_forensic_tool_failure(report) is False
    assert report["frame_probe_exit"] == 0
    assert report["pixel_probe_exit"] == 0
    assert all(sample["pixel_verification"]["status"] == "PASS"
               for sample in report["decoded_frame_samples"])
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
        "decode_exit": 0, "frame_probe_exit": 0, "pixel_probe_exit": 0,
        "black_frame_metrics": {"sampled_frame_count": 30},
        "metadata": {"format": "mov,mp4", "duration_seconds": 4.0,
                     "streams": [{"type": "video"}]},
        "decoded_frame_samples": [
            {"sample": "first", "timestamp": "0.0", "error": "", "pixel_verification": {"status": "PASS"}},
            {"sample": "quarter", "timestamp": "1.0", "error": "", "pixel_verification": {"status": "PASS"}},
            {"sample": "middle", "timestamp": "2.0", "error": "", "pixel_verification": {"status": "PASS"}},
            {"sample": "three_quarter", "timestamp": "3.0", "error": "", "pixel_verification": {"status": "PASS"}},
            {"sample": "last", "timestamp": "3.9", "error": "", "pixel_verification": {"status": "PASS"}},
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
            "stdout": "4.958333,P\n5.041667,B\n",
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


def test_sequential_fallback_parses_late_timestamp_from_compact_csv(tmp_path, monkeypatch):
    calls = []

    def fake_run(command, timeout=120):
        calls.append(command)
        interval = command[command.index("-read_intervals") + 1]
        if not interval.startswith("0%+"):
            return {"returncode": 0, "stdout": '{"frames":[]}', "stderr": ""}
        rows = [f"{index / 24:.6f},P" for index in range(217)]
        return {"returncode": 0, "stdout": "\n".join(rows), "stderr": ""}

    monkeypatch.setattr(media_forensics, "run", fake_run)
    sample = media_forensics.sample_decoded_frame(tmp_path / "clip.mp4", 8.9, "last")
    assert sample["timestamp"] is not None
    assert float(sample["timestamp"]) >= 8.9
    assert sample["sampling_method"] == "sequential_fallback_from_start"
    assert sample["error"] == ""
    assert calls[-1][calls[-1].index("-of") + 1] == "csv=p=0"


def test_run_preserves_bounded_head_and_tail_for_large_filter_lists(monkeypatch):
    from types import SimpleNamespace

    output = "blackdetect\n" + ("x" * 600_000) + "\nblackframe\nfps\nscale"
    monkeypatch.setattr(
        media_forensics.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=output, stderr=""),
    )
    result = media_forensics.run(["ffmpeg", "-filters"])
    assert "blackdetect" in result["stdout"]
    assert "blackframe" in result["stdout"]
    assert "fps" in result["stdout"]
    assert "scale" in result["stdout"]
    assert len(result["stdout"]) < 513_000


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



def test_compact_forensic_summary_preserves_five_targets_under_relay_tail_cap():
    targets = []
    for index in range(5):
        targets.append({
            "file": f"{index:02d}-" + "clip.mp4",
            "exists": True,
            "size_bytes": 123456,
            "sha256": "a" * 64,
            "metadata": {
                "duration_seconds": 9.04,
                "streams": [
                    {"type": "video", "codec": "h264", "resolution": "720x1280",
                     "pixel_format": "yuv420p", "frame_count": "216"},
                    {"type": "audio", "codec": "aac", "sample_rate": "48000",
                     "channels": 2, "duration": "9.0"},
                ],
            },
            "full_duration_black": True,
            "black_intervals": [[0.0, 9.0]],
            "ffprobe_exit": 0,
            "blackdetect_exit": 0,
            "blackframe_exit": 0,
            "black_frame_metrics": {
                "sampled_frame_count": 30, "black_frame_count": 30,
                "black_frame_percentage": 100.0, "mean_black_pixel_percentage": 100.0,
                "black_pixel_threshold": 32, "black_frame_cutoff_percent": 98,
                "pblack_values": [100] * 30,
            },
            "blackframe_error": "",
            "decode_exit": 0,
            "frame_probe_exit": 0,
            "pixel_probe_exit": 0,
            "decoded_frame_samples": [
                {"sample": label, "seek_seconds": point, "timestamp": str(point),
                 "sampling_method": "sequential_fallback_from_start", "error": "",
                 "pixel_verification": {"status": "PASS", "mean_luma": 0.0,
                                         "luma_stddev": 0.0, "black_pixel_percentage": 100.0,
                                         "near_black": True}}
                for label, point in (
                    ("first", 0.0), ("quarter", 2.26), ("middle", 4.52),
                    ("three_quarter", 6.78), ("last", 9.0)
                )
            ],
            "pre_repair_backups": [{
                "path": "media_backups/" + ("b" * 64) + ".mp4",
                "size_bytes": 100000, "sha256": "b" * 64,
            }],
            "asset_reference_time_utc": "2026-11-13T00:00:00+00:00",
        })
    report = {
        "status": "READ_ONLY_FORENSICS",
        "environment": {
            "python": {"version": "3.14.10", "executable": "/data/data/com.termux/files/usr/bin/python"},
            "platform": "Android-15-aarch64",
            "termux_version": "0.118.3",
            "ffmpeg": {"available": True, "path": "/data/data/com.termux/files/usr/bin/ffmpeg",
                       "version": "ffmpeg version 7.1.5", "filters": {
                           "blackdetect": True, "blackframe": True, "fps": True, "scale": True}},
            "ffprobe": {"available": True, "path": "/data/data/com.termux/files/usr/bin/ffprobe",
                        "version": "ffprobe version 7.1.5"},
            "frame_sampling": "Five FFprobe timestamps plus extracted PNG pixel verification",
            "temporary_storage": {"path": "/data/data/com.termux/files/usr/tmp",
                                  "exists": True, "writable": True,
                                  "write_test": True, "free_bytes": 123456789},
        },
        "summary": {"target_count": 5, "full_duration_black_count": 5,
                    "forensic_tool_failure_count": 0},
        "targets": targets,
        "candidate_source_assets": [
            {"path": f"generated_images/{index}-" + "source.jpg",
             "mean_luma": 25.0, "near_black": False,
             "modified_utc": "2026-11-13T00:00:00+00:00"}
            for index in range(5)
        ],
        "production_log_matches": [
            {"path": "logs/render.log", "line": index,
             "excerpt": "renderer evidence " + ("x" * 100)}
            for index in range(5)
        ],
        "production_database_matches": [
            {"db": "production_runtime.sqlite3", "table": "production_runs",
             "column": "result_json", "record": {"status": "failed", "run_id": index}}
            for index in range(5)
        ],
        "safety": {"files_modified": False, "files_deleted": False},
    }
    footer = media_forensics.compact_forensic_summary(report)
    assert len(footer["targets"]) == 5
    assert all(len(target["samples"]) == 5 for target in footer["targets"])
    assert all(target["backups"][0][2] == "b" * 64 for target in footer["targets"])
    assert all(len(target["black_frames"]["pblack"]) == 30 for target in footer["targets"])
    import json as json_module
    assert len(json_module.dumps(footer, separators=(",", ":"))) < 7000


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
    assert metrics["pblack_values"] == [100, 100, 0, 20]
    assert metrics["black_pixel_threshold"] == 17
    empty_metrics = media_forensics.summarize_black_frame_percentages([])
    assert empty_metrics["black_pixel_threshold"] == 17



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
    assert report["pixel_probe_exit"] == 0
    assert report["pixel_verification"]["near_black_sample_count"] == 5
    assert all(sample["pixel_verification"]["near_black"] is True
               for sample in report["decoded_frame_samples"])
    assert [sample["sample"] for sample in report["decoded_frame_samples"]] == [
        "first", "quarter", "middle", "three_quarter", "last"
    ]
    assert media_forensics.has_forensic_tool_failure(report) is False


def test_forensic_environment_reports_tool_paths_versions_filters_and_temp_storage(monkeypatch):
    monkeypatch.setattr(
        media_forensics.shutil, "which",
        lambda name: f"/opt/termux/bin/{name}",
    )

    def fake_run(command, timeout=120):
        if command[0].endswith("ffmpeg") and "-filters" in command:
            return {
                "returncode": 0,
                "stdout": " T.. blackdetect V->V detect video intervals\n"
                          " T.. blackframe V->V detect frames\n"
                          " ..C fps V->V force constant frame rate\n"
                          " ..C scale V->V scale video\n",
                "stderr": "",
            }
        return {
            "returncode": 0,
            "stdout": f"{Path(command[0]).name} version 7.1.5\n",
            "stderr": "",
        }

    monkeypatch.setattr(media_forensics, "run", fake_run)
    environment = media_forensics.inspect_environment()
    assert environment["python"]["version"]
    assert environment["ffmpeg"]["path"] == "/opt/termux/bin/ffmpeg"
    assert environment["ffmpeg"]["version"].startswith("ffmpeg version 7.1.5")
    assert environment["ffprobe"]["path"] == "/opt/termux/bin/ffprobe"
    assert environment["ffprobe"]["version"].startswith("ffprobe version 7.1.5")
    assert environment["ffmpeg"]["filters"] == {
        "blackdetect": True, "blackframe": True, "fps": True, "scale": True,
    }
    assert environment["frame_sampling"].startswith("Five FFprobe")
    assert environment["temporary_storage"]["exists"] is True
    assert environment["temporary_storage"]["write_test"] is True
    assert environment["temporary_storage"]["free_bytes"] > 0


def test_missing_and_corrupt_video_inputs_fail_closed(tmp_path, monkeypatch):
    missing = media_forensics.inspect_video(tmp_path / "missing.mp4")
    assert media_forensics.has_forensic_tool_failure(missing) is True

    corrupt = tmp_path / "corrupt.mp4"
    corrupt.write_bytes(b"not an MP4 container")

    def fake_run(command, timeout=120):
        return {"returncode": 1, "stdout": "", "stderr": "invalid media data"}

    monkeypatch.setattr(media_forensics, "run", fake_run)
    report = media_forensics.inspect_video(corrupt)
    assert report["exists"] is True
    assert report["ffprobe_exit"] == 1
    assert report["decode_exit"] == 1
    assert media_forensics.has_forensic_tool_failure(report) is True


def test_audio_only_container_is_not_accepted_as_visual_video(tmp_path, monkeypatch):
    video = tmp_path / "audio-only.mp4"
    video.write_bytes(b"fixture")
    metadata = {
        "format": {"format_name": "mov,mp4", "duration": "4.0"},
        "streams": [{
            "codec_type": "audio", "codec_name": "aac", "sample_rate": "48000",
            "channels": 2, "duration": "4.0", "start_time": "0.0",
        }],
    }

    def fake_run(command, timeout=120):
        if command[0] == "ffprobe" and "-count_frames" in command:
            return {"returncode": 0, "stdout": json.dumps(metadata), "stderr": ""}
        if command[0] == "ffprobe" and "-read_intervals" in command:
            interval = command[command.index("-read_intervals") + 1]
            return {"returncode": 0, "stdout": '{"frames":[]}' if not interval.startswith("0%+") else "", "stderr": ""}
        if command[0] == "ffmpeg" and any("blackframe=" in part for part in command):
            return {"returncode": 0, "stdout": "", "stderr": "pblack:0\\n" * 30}
        if command[0] == "ffmpeg" and any("scale=64:64:flags=area" in part for part in command):
            media_forensics.Image.new("RGB", (64, 64), "white").save(command[-1])
            return {"returncode": 0, "stdout": "", "stderr": ""}
        return {"returncode": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(media_forensics, "run", fake_run)
    report = media_forensics.inspect_video(video)
    assert not any(stream["type"] == "video" for stream in report["metadata"]["streams"])
    assert report["frame_probe_exit"] == 1
    assert report["pixel_probe_exit"] == 1
    assert media_forensics.has_forensic_tool_failure(report) is True


def test_vfr_frame_sampling_uses_best_effort_decoded_timestamps(tmp_path, monkeypatch):
    monkeypatch.setattr(media_forensics, "run", lambda *args, **kwargs: {
        "returncode": 0,
        "stdout": '{"frames":['
                  '{"best_effort_timestamp_time":"4.900000","pict_type":"P"},'
                  '{"best_effort_timestamp_time":"5.130000","pict_type":"B"},'
                  '{"best_effort_timestamp_time":"5.400000","pict_type":"P"}]}',
        "stderr": "",
    })
    sample = media_forensics.sample_decoded_frame(tmp_path / "vfr.mp4", 5.02, "middle")
    assert sample["timestamp"] == "5.130000"
    assert sample["picture_type"] == "B"
    assert sample["error"] == ""


def test_forensic_environment_reports_temporary_storage_write_failure(tmp_path, monkeypatch):
    import shutil

    monkeypatch.setattr(media_forensics.shutil, "which", lambda name: f"/opt/bin/{name}")
    monkeypatch.setattr(media_forensics.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(
        media_forensics.tempfile, "NamedTemporaryFile",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("temporary storage full")),
    )

    def fake_run(command, timeout=120):
        if "-filters" in command:
            return {"returncode": 0, "stdout": "blackdetect blackframe fps scale", "stderr": ""}
        return {"returncode": 0, "stdout": "tool version 1.0", "stderr": ""}

    monkeypatch.setattr(media_forensics, "run", fake_run)
    environment = media_forensics.inspect_environment()
    assert environment["temporary_storage"]["exists"] is True
    assert environment["temporary_storage"]["write_test"] is False
    assert "temporary storage full" in environment["temporary_storage"]["error"]
    assert environment["temporary_storage"]["free_bytes"] == shutil.disk_usage(tmp_path).free


def test_forensic_main_returns_nonzero_when_any_target_has_tool_failure(tmp_path, monkeypatch, capsys):
    import sys

    monkeypatch.setattr(media_forensics, "TARGETS", ("missing.mp4",))
    monkeypatch.setattr(media_forensics, "MEDIA_DIR", tmp_path)
    monkeypatch.setattr(media_forensics, "inspect_video", lambda path: {
        "file": path.name, "exists": False, "safe_regular_file": False,
    })
    monkeypatch.setattr(media_forensics, "inspect_environment", lambda: {})
    monkeypatch.setattr(media_forensics, "scan_text_logs", lambda needles: [])
    monkeypatch.setattr(media_forensics, "scan_database_records", lambda needles: [])
    monkeypatch.setattr(sys, "argv", ["media_forensics.py", "--json"])
    assert media_forensics.main() == 1
    assert "forensic_tool_failure_count" in capsys.readouterr().out


def test_real_nonblack_mp4_forensics_passes_with_decoded_samples(tmp_path, monkeypatch):
    import shutil
    import subprocess
    import pytest

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg is required for the real non-black MP4 regression")
    clip = tmp_path / "visible-test-pattern.mp4"
    created = subprocess.run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=s=160x120:r=24:d=4",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip),
    ], capture_output=True, timeout=60, check=False)
    if created.returncode != 0:
        pytest.skip("FFmpeg build does not provide the libx264 test encoder")
    report = media_forensics.inspect_video(clip)
    assert report["full_duration_black"] is False
    assert report["frame_probe_exit"] == 0
    assert report["pixel_probe_exit"] == 0
    assert report["pixel_verification"]["near_black_sample_count"] == 0
    assert any(sample["pixel_verification"]["mean_luma"] > 2.0
               for sample in report["decoded_frame_samples"])
    assert media_forensics.has_forensic_tool_failure(report) is False


def test_real_partial_black_mp4_is_not_misclassified_as_full_duration_black(tmp_path):
    import shutil
    import subprocess
    import pytest

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg is required for the partial-black regression")
    clip = tmp_path / "partial-black.mp4"
    created = subprocess.run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=black:s=160x120:r=24:d=1",
        "-f", "lavfi", "-i", "color=c=white:s=160x120:r=24:d=3",
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0,format=yuv420p[v]",
        "-map", "[v]", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip),
    ], capture_output=True, timeout=60, check=False)
    if created.returncode != 0:
        pytest.skip("FFmpeg build does not provide the libx264 test encoder")
    report = media_forensics.inspect_video(clip)
    assert report["blackdetect_full_duration_black"] is False
    assert report["full_duration_black"] is False
    assert report["black_intervals"]
    assert report["black_intervals"][0][1] < report["metadata"]["duration_seconds"] * 0.95
    assert report["frame_probe_exit"] == 0
    assert report["pixel_probe_exit"] == 0
    assert report["decoded_frame_samples"][0]["pixel_verification"]["near_black"] is True
    assert all(sample["pixel_verification"]["near_black"] is False
               for sample in report["decoded_frame_samples"][1:])
    assert media_forensics.has_forensic_tool_failure(report) is False


def test_missing_ffmpeg_and_ffprobe_are_reported_by_environment_probe(monkeypatch):
    monkeypatch.setattr(media_forensics.shutil, "which", lambda name: None)
    environment = media_forensics.inspect_environment()
    assert environment["ffmpeg"]["available"] is False
    assert environment["ffmpeg"]["path"] is None
    assert environment["ffprobe"]["available"] is False
    assert environment["ffprobe"]["path"] is None
    assert environment["ffmpeg"]["filters"] == {
        "blackdetect": False, "blackframe": False, "fps": False, "scale": False,
    }


def test_inspect_video_marks_middle_and_last_sampling_failures_as_tool_failure(tmp_path, monkeypatch):
    video = tmp_path / "sampling-failure.mp4"
    video.write_bytes(b"fixture")
    metadata = {
        "format": {"format_name": "mov,mp4", "duration": "4.0"},
        "streams": [{
            "codec_type": "video", "codec_name": "h264", "width": 160, "height": 120,
            "pix_fmt": "yuv420p", "avg_frame_rate": "24/1", "nb_read_frames": "96",
            "duration": "4.0", "start_time": "0.0",
        }],
    }

    def fake_run(command, timeout=120):
        if command[0] == "ffprobe" and "-count_frames" in command:
            return {"returncode": 0, "stdout": json.dumps(metadata), "stderr": ""}
        if command[0] == "ffprobe" and "-read_intervals" in command:
            interval = command[command.index("-read_intervals") + 1]
            if interval.startswith("0%+"):
                return {"returncode": 0, "stdout": "", "stderr": ""}
            seek = float(interval.split("%", 1)[0])
            if seek >= 2.0:
                return {"returncode": 0, "stdout": '{"frames":[]}', "stderr": ""}
            return {"returncode": 0, "stdout": json.dumps({
                "frames": [{"best_effort_timestamp_time": f"{seek:.6f}", "pict_type": "P"}]
            }), "stderr": ""}
        if command[0] == "ffmpeg" and any("blackframe=" in part for part in command):
            return {"returncode": 0, "stdout": "", "stderr": "pblack:0\\n" * 30}
        if command[0] == "ffmpeg" and any("scale=64:64:flags=area" in part for part in command):
            media_forensics.Image.new("RGB", (64, 64), "white").save(command[-1])
            return {"returncode": 0, "stdout": "", "stderr": ""}
        return {"returncode": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(media_forensics, "run", fake_run)
    report = media_forensics.inspect_video(video)
    assert [sample["sample"] for sample in report["decoded_frame_samples"] if sample["error"]] == [
        "middle", "three_quarter", "last",
    ]
    assert report["frame_probe_exit"] == 1
    assert report["pixel_probe_exit"] == 1
    assert media_forensics.has_forensic_tool_failure(report) is True


def test_extracted_frame_pixel_verification_distinguishes_black_and_visible_frames(tmp_path, monkeypatch):
    colors = iter(["black", "white"])

    def fake_run(command, timeout=120):
        media_forensics.Image.new("RGB", (64, 64), next(colors)).save(command[-1])
        return {"returncode": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(media_forensics, "run", fake_run)
    black = media_forensics.extract_frame_pixel_verification(tmp_path / "clip.mp4", "0.0", "first")
    visible = media_forensics.extract_frame_pixel_verification(tmp_path / "clip.mp4", "2.0", "middle")
    assert black["status"] == "PASS"
    assert black["near_black"] is True
    assert black["mean_luma"] == 0.0
    assert black["black_pixel_percentage"] == 100.0
    assert visible["status"] == "PASS"
    assert visible["near_black"] is False
    assert visible["mean_luma"] == 255.0
    assert visible["black_pixel_percentage"] == 0.0


def test_extracted_frame_pixel_verification_fails_closed_on_timeout_and_temp_storage_error(tmp_path, monkeypatch):
    monkeypatch.setattr(media_forensics, "run", lambda *args, **kwargs: {
        "returncode": None, "stdout": "", "stderr": "ffmpeg frame extraction timed out",
    })
    timed_out = media_forensics.extract_frame_pixel_verification(tmp_path / "clip.mp4", "1.0", "middle")
    assert timed_out["status"] == "FAIL"
    assert timed_out["extraction_exit"] is None
    assert "timed out" in timed_out["error"]

    monkeypatch.setattr(
        media_forensics.tempfile, "TemporaryDirectory",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("temporary storage unavailable")),
    )
    no_storage = media_forensics.extract_frame_pixel_verification(tmp_path / "clip.mp4", "1.0", "middle")
    assert no_storage["status"] == "FAIL"
    assert no_storage["extraction_exit"] is None
    assert "temporary storage unavailable" in no_storage["error"]


def test_real_dark_gray_mp4_is_not_misclassified_as_full_black(tmp_path):
    import shutil
    import subprocess
    import pytest

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg is required for dark-footage threshold regression")
    clip = tmp_path / "dark-gray-visible.mp4"
    created = subprocess.run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=0x161616:s=160x120:r=24:d=4",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip),
    ], capture_output=True, timeout=60, check=False)
    if created.returncode != 0:
        pytest.skip("FFmpeg build does not provide the libx264 test encoder")
    report = media_forensics.inspect_video(clip)
    assert report["blackdetect_full_duration_black"] is False
    assert report["full_duration_black"] is False
    assert report["pixel_verification"]["near_black_sample_count"] == 0
    assert all(sample["pixel_verification"]["near_black"] is False
               for sample in report["decoded_frame_samples"])
    assert media_forensics.has_forensic_tool_failure(report) is False

