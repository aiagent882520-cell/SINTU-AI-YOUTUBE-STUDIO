import json
from pathlib import Path

from scripts.termux_full_diagnostic import media_inventory, render_text


def test_media_inventory_is_empty_when_directory_is_absent(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.termux_full_diagnostic.MEDIA_DIR", tmp_path / "missing")
    result = media_inventory()
    assert result["count"] == 0
    assert result["files"] == []


def test_text_report_labels_device_and_safety_state():
    report = {
        "created_at": "2026-11-18T00:00:00+00:00",
        "device": {"platform": "Android", "machine": "aarch64", "python": "3.14.0", "termux": True},
        "repository": {"commit": "abc123", "working_tree": "## main", "git_status_exit": 0},
        "dependencies": {"pip_check": {"exit_code": 0}},
        "media_tools": {"ffmpeg": {"version": "ffmpeg version test"}, "ffprobe": {"version": "ffprobe version test"}},
        "backend": {"reachable": False, "url": "http://127.0.0.1:8000/health"},
        "android": {"apk_files_found": []},
        "media": {"count": 0, "directory": "/tmp/generated_videos"},
    }
    text = render_text(report)
    assert "Automation self-test: NOT RUN" in text
    assert "read-only" in text
    assert "Backend reachable: False" in text
