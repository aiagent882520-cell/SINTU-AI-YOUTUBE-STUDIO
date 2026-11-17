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
