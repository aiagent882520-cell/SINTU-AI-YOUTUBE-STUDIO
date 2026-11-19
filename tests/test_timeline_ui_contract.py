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


def test_timeline_preview_has_single_cancellable_session():
    source = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    start = source.index("let activeTimelinePreview = null;")
    end = source.index('\n$("timelinePreviewPlay").addEventListener', start)
    preview = source[start:end]

    assert "stopActiveTimelinePreview(" in preview
    assert "activeTimelinePreview=session" in preview
    assert "finishCurrent(false)" in preview
    assert 'video.removeEventListener("loadedmetadata",onMetadata)' in preview
    assert 'video.removeEventListener("timeupdate",onTimeUpdate)' in preview
    assert 'video.removeEventListener("ended",onEnded)' in preview
    assert "video.pause()" in preview
    assert "item.trimEnd!==null&&video.currentTime>=item.trimEnd" in preview
    assert "playback.catch" in preview


def test_timeline_preview_uses_current_image_item_without_stale_index():
    source = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    start = source.index("let activeTimelinePreview = null;")
    end = source.index('\n$("timelinePreviewPlay").addEventListener', start)
    preview = source[start:end]

    assert "const waitForImage=(item,durationMs)=>" in preview
    assert 'src="/api/images/"+item.id' in preview
    assert "rows[index].id" not in preview
    assert "try{\n     const playback=video.play();" in preview
