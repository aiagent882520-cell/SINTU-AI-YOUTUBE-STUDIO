from pathlib import Path
import json
import pytest

from scripts import safe_media_remux as remux


def _fake_tools(monkeypatch):
    def fake_run(command, timeout=600):
        if command[0] == "ffprobe":
            return {
                "returncode": 0,
                "stdout": json.dumps({
                    "streams": [{
                        "codec_type": "video", "codec_name": "h264",
                        "width": 720, "height": 1280,
                    }, {
                        "codec_type": "audio", "codec_name": "aac",
                        "sample_rate": "48000", "channels": 2,
                    }],
                    "format": {"duration": "4.0"},
                }),
                "stderr": "",
            }
        if command[0] == "ffmpeg" and "-c" in command:
            Path(command[-1]).write_bytes(b"remuxed-container")
        return {"returncode": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(remux, "run", fake_run)


def test_safe_remux_writes_new_file_and_preserves_source(tmp_path, monkeypatch):
    _fake_tools(monkeypatch)
    source = tmp_path / "source.mp4"
    destination = tmp_path / "repaired-copy.mp4"
    source.write_bytes(b"original-container")
    before = remux.sha256_file(source)

    report = remux.safe_remux(source, destination, ffmpeg="ffmpeg", ffprobe="ffprobe")

    assert report["status"] == "REMUXED_TO_NEW_FILE"
    assert report["source_sha256_before"] == before
    assert report["source_sha256_after"] == before
    assert report["source_modified"] is False
    assert report["black_frame_repair_performed"] is False
    assert source.read_bytes() == b"original-container"
    assert destination.read_bytes() == b"remuxed-container"


def test_safe_remux_refuses_existing_destination(tmp_path):
    source = tmp_path / "source.mp4"
    destination = tmp_path / "existing.mp4"
    source.write_bytes(b"source")
    destination.write_bytes(b"keep-me")

    with pytest.raises(FileExistsError):
        remux.safe_remux(source, destination, ffmpeg="ffmpeg", ffprobe="ffprobe")

    assert destination.read_bytes() == b"keep-me"


def test_safe_remux_refuses_same_source_and_destination(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")

    with pytest.raises(ValueError, match="different files"):
        remux.safe_remux(source, source, ffmpeg="ffmpeg", ffprobe="ffprobe")


def test_safe_remux_refuses_symlink_source(tmp_path):
    source = tmp_path / "source.mp4"
    alias = tmp_path / "alias.mp4"
    source.write_bytes(b"source")
    alias.symlink_to(source)

    with pytest.raises(ValueError, match="symlink"):
        remux.safe_remux(alias, tmp_path / "out.mp4",
                         ffmpeg="ffmpeg", ffprobe="ffprobe")


def test_safe_remux_discards_output_when_stream_layout_changes(tmp_path, monkeypatch):
    calls = {"probe": 0}

    def fake_run(command, timeout=600):
        if command[0] == "ffprobe":
            calls["probe"] += 1
            codec = "h264" if calls["probe"] == 1 else "mpeg4"
            return {
                "returncode": 0,
                "stdout": json.dumps({
                    "streams": [{
                        "codec_type": "video", "codec_name": codec,
                        "width": 720, "height": 1280,
                    }],
                    "format": {"duration": "4.0"},
                }),
                "stderr": "",
            }
        if "-c" in command:
            Path(command[-1]).write_bytes(b"bad-remux")
        return {"returncode": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(remux, "run", fake_run)
    source = tmp_path / "source.mp4"
    destination = tmp_path / "out.mp4"
    source.write_bytes(b"source")

    with pytest.raises(RuntimeError, match="stream layout"):
        remux.safe_remux(source, destination, ffmpeg="ffmpeg", ffprobe="ffprobe")

    assert source.read_bytes() == b"source"
    assert not destination.exists()
    assert not list(tmp_path.glob(".sintu-remux-*.mp4"))
