import json
from types import SimpleNamespace

import pytest

from app.video_renderer import RenderFailed, _verify_rendered_output


def _metadata(width=720, height=1280, duration=8.0, audio=True, codec="h264"):
    streams = [{"codec_type": "video", "codec_name": codec, "width": width, "height": height}]
    if audio:
        streams.append({"codec_type": "audio", "codec_name": "aac"})
    return {"streams": streams, "format": {"format_name": "mov,mp4,m4a", "duration": str(duration)}}


def _run_result(metadata, returncode=0):
    return SimpleNamespace(returncode=returncode, stdout=json.dumps(metadata), stderr="probe failed")


def _setup_probe(monkeypatch, metadata, returncode=0):
    monkeypatch.setattr("app.video_renderer.shutil.which", lambda name: "/usr/bin/ffprobe")
    monkeypatch.setattr("app.video_renderer.subprocess.run", lambda *args, **kwargs: _run_result(metadata, returncode))


def test_final_mp4_verification_accepts_expected_video_and_audio(tmp_path, monkeypatch):
    _setup_probe(monkeypatch, _metadata())
    output = tmp_path / "final.mp4"
    output.write_bytes(b"mp4")
    result = _verify_rendered_output(output, 720, 1280, 8, require_audio=True)
    assert result == {"duration_seconds": 8.0, "resolution": "720x1280", "video_codec": "h264", "audio": True}


@pytest.mark.parametrize("metadata", [
    _metadata(width=1080, height=1920),
    _metadata(duration=20),
    _metadata(codec="vp9"),
    {"streams": [], "format": {"format_name": "mov,mp4", "duration": "8"}},
    {"streams": [{"codec_type": "video", "codec_name": "h264", "width": 720, "height": 1280}],
     "format": {"format_name": "matroska,webm", "duration": "8"}},
])
def test_final_mp4_verification_rejects_wrong_output_metadata(tmp_path, monkeypatch, metadata):
    _setup_probe(monkeypatch, metadata)
    output = tmp_path / "final.mp4"
    output.write_bytes(b"mp4")
    with pytest.raises(RenderFailed):
        _verify_rendered_output(output, 720, 1280, 8, require_audio=True)


def test_final_mp4_verification_rejects_missing_expected_audio(tmp_path, monkeypatch):
    _setup_probe(monkeypatch, _metadata(audio=False))
    output = tmp_path / "final.mp4"
    output.write_bytes(b"mp4")
    with pytest.raises(RenderFailed, match="audio stream"):
        _verify_rendered_output(output, 720, 1280, 8, require_audio=True)


def test_final_mp4_verification_rejects_ffprobe_failure(tmp_path, monkeypatch):
    _setup_probe(monkeypatch, {}, returncode=1)
    output = tmp_path / "final.mp4"
    output.write_bytes(b"mp4")
    with pytest.raises(RenderFailed, match="corrupt"):
        _verify_rendered_output(output, 720, 1280, 8)


def test_final_mp4_verification_requires_ffprobe(tmp_path, monkeypatch):
    monkeypatch.setattr("app.video_renderer.shutil.which", lambda name: None)
    output = tmp_path / "final.mp4"
    output.write_bytes(b"mp4")
    from app.video_renderer import RendererUnavailable
    with pytest.raises(RendererUnavailable, match="FFprobe"):
        _verify_rendered_output(output, 720, 1280, 8)

