from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_readme_documents_timed_subtitle_burn_in_consistently():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "timed SRT subtitle/lyric burn-in" in readme
    assert "FFmpeg/libass" in readme
    assert "scene-aligned Hindi subtitle tracks automatically" in readme
    assert "reject subtitle/caption burn-in" not in readme
    assert "no burned-in subtitles" not in readme
