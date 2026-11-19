from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_timeline_edits_do_not_clear_subtitle_text():
    source = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    start = source.index("function syncTimelineFields(rows)")
    end = source.index("\nfunction renderTimelineEditor", start)
    sync = source[start:end]

    assert '$("renderScenes").value=rows.map(x=>x.scene||"").join("\\n");' in sync
    assert '$("renderSubtitles").value=""' not in sync


def test_subtitle_payload_remains_connected_to_render_queue():
    source = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")

    assert "subtitles:subtitleLines()" in source
