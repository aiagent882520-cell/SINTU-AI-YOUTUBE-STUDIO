import subprocess
from pathlib import Path
import pytest
from app import video_renderer

def test_storyboard_render_publishes_only_verified_atomic_mp4(tmp_path, monkeypatch):
    monkeypatch.setattr(video_renderer, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(video_renderer.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(video_renderer, "_make_frame", lambda *args, **kwargs: None)
    monkeypatch.setattr(video_renderer, "_verify_rendered_output", lambda path, *args, **kwargs: None)
    captured = {}
    def fake_ffmpeg(command, **kwargs):
        target = Path(command[-1])
        captured["target"] = target
        assert target.parent == tmp_path
        assert target.name.startswith(".sintu-render-")
        target.write_bytes(b"completed-mp4")
        return subprocess.CompletedProcess(command, 0, "", "")
    monkeypatch.setattr(video_renderer.subprocess, "run", fake_ffmpeg)
    result = video_renderer.render_storyboard(title="Atomic render", scenes=["Scene one"], seconds_per_scene=2)
    final_path = tmp_path / result["filename"]
    assert final_path.read_bytes() == b"completed-mp4"
    assert captured["target"] != final_path
    assert list(tmp_path.glob("*.mp4")) == [final_path]
    assert not list(tmp_path.glob(".sintu-render-*.mp4"))

def test_storyboard_render_cleans_temporary_mp4_after_verification_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(video_renderer, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(video_renderer.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(video_renderer, "_make_frame", lambda *args, **kwargs: None)
    def fake_ffmpeg(command, **kwargs):
        Path(command[-1]).write_bytes(b"invalid-mp4")
        return subprocess.CompletedProcess(command, 0, "", "")
    def fail_verification(*args, **kwargs):
        raise video_renderer.RenderFailed("verification failed")
    monkeypatch.setattr(video_renderer.subprocess, "run", fake_ffmpeg)
    monkeypatch.setattr(video_renderer, "_verify_rendered_output", fail_verification)
    with pytest.raises(video_renderer.RenderFailed, match="verification failed"):
        video_renderer.render_storyboard(title="Failed render", scenes=["Scene one"], seconds_per_scene=2)
    assert list(tmp_path.iterdir()) == []
