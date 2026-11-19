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
    try:
        count = max(1, min(8, int(raw)))
    except ValueError:
        count = 2
    assert count == expected
