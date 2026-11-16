from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_readme_documents_timed_subtitle_burn_in_consistently():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "timed SRT subtitle/lyric burn-in" in readme
    assert "FFmpeg/libass" in readme
    assert "scene-aligned Hindi subtitle tracks automatically" in readme
    assert "reject subtitle/caption burn-in" not in readme
    assert "no burned-in subtitles" not in readme


def test_hindi_readme_documents_subtitle_burn_in_without_overclaiming():
    readme_hi = (ROOT / "README_HI.md").read_text(encoding="utf-8")

    assert "optional timed SRT subtitles/captions/lyrics" in readme_hi
    assert "FFmpeg/libass" in readme_hi
    assert "Specific AI-clip assembly path" in readme_hi
    assert "subtitles/captions burn nahi hote" not in readme_hi
