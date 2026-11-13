import subprocess
from pathlib import Path

import pytest

from app import video_renderer


def _source_clip(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    return source


def _write_render(command):
    target = Path(command[-1])
    assert target.name.startswith(".sintu-ai-join-")
    target.write_bytes(b"completed-mp4")
    return subprocess.CompletedProcess(command, 0, "", "")


def _mock_probe_and_ffmpeg(monkeypatch, tmp_path, *, fail_verify=False):
    monkeypatch.setattr(video_renderer, "OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr(video_renderer.shutil, "which", lambda name: f"/usr/bin/{name}")
    def fake_run(command, **kwargs):
        if command[0].endswith("ffprobe"):
            return subprocess.CompletedProcess(
                command, 0,
                '{"format":{"duration":"2.0"},"streams":[{"codec_type":"video"}]}', "",
            )
        return _write_render(command)
    monkeypatch.setattr(video_renderer.subprocess, "run", fake_run)
    def verify(path, *args, **kwargs):
        assert path.name.startswith(".sintu-ai-join-")
        assert path.exists()
        if fail_verify:
            raise video_renderer.RenderFailed("verification failed")
    monkeypatch.setattr(video_renderer, "_verify_rendered_output", verify)


def test_ai_clip_render_publishes_only_verified_atomic_mp4(tmp_path, monkeypatch):
    _mock_probe_and_ffmpeg(monkeypatch, tmp_path)
    source = _source_clip(tmp_path)
    result = video_renderer.render_ai_clips([source])
    final_path = tmp_path / "out" / result["filename"]
    assert final_path.read_bytes() == b"completed-mp4"
    assert list((tmp_path / "out").glob("*.mp4")) == [final_path]
    assert not list((tmp_path / "out").glob(".sintu-ai-join-*.mp4"))


def test_ai_clip_render_cleans_temporary_mp4_after_verification_failure(tmp_path, monkeypatch):
    _mock_probe_and_ffmpeg(monkeypatch, tmp_path, fail_verify=True)
    source = _source_clip(tmp_path)
    with pytest.raises(video_renderer.RenderFailed, match="verification failed"):
        video_renderer.render_ai_clips([source])
    assert list((tmp_path / "out").iterdir()) == []
