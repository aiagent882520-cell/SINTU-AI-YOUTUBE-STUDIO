import pytest

from app import video_renderer


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1", 1),
        ("2", 2),
        ("8", 8),
        ("0", 1),
        ("64", 8),
        ("invalid", 2),
    ],
)
def test_ffmpeg_thread_count_is_bounded(raw, expected, monkeypatch):
    monkeypatch.setenv("SINTU_FFMPEG_THREADS", raw)
    assert video_renderer._ffmpeg_thread_count() == expected
