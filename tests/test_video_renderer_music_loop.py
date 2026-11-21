from types import SimpleNamespace

import pytest

from app import video_renderer


def test_ai_clip_music_loops_only_when_track_is_shorter(monkeypatch, tmp_path):
    calls = []

    def fake_probe(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="4.000000\n", stderr="")

    monkeypatch.setattr(video_renderer.render_process, "run_render_process", fake_probe)
    music = tmp_path / "background.wav"

    assert video_renderer._music_loop_args("ffprobe", music, 4.0) == []
    assert video_renderer._music_loop_args("ffprobe", music, 4.2) == ["-stream_loop", "-1"]
    assert len(calls) == 2
    assert calls[0][0][0] == "ffprobe"
    assert str(music) in calls[0][0]
    assert calls[0][1]["timeout"] == 30


@pytest.mark.parametrize("duration", ["", "nan", "inf", "0", "-1", "not-a-duration"])
def test_ai_clip_music_rejects_invalid_probe_duration(monkeypatch, tmp_path, duration):
    monkeypatch.setattr(
        video_renderer.render_process,
        "run_render_process",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=duration, stderr=""),
    )
    with pytest.raises(video_renderer.RenderFailed):
        video_renderer._music_loop_args("ffprobe", tmp_path / "background.wav", 4.0)


def test_ai_clip_music_rejects_probe_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(
        video_renderer.render_process,
        "run_render_process",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="probe failed"),
    )
    with pytest.raises(video_renderer.RenderFailed, match="duration read"):
        video_renderer._music_loop_args("ffprobe", tmp_path / "background.wav", 4.0)
