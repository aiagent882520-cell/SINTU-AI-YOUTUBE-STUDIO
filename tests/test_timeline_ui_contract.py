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
    assert '"/api/images/' in preview and "item.id" in preview
    assert "rows[index].id" not in preview
    assert "try{\n     const playback=video.play();" in preview


def test_video_preview_metadata_is_initialized_once():
    source = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    start = source.index("let activeTimelinePreview = null;")
    end = source.index('\n$("timelinePreviewPlay").addEventListener', start)
    preview = source[start:end]

    assert "metadataHandled=false" in preview
    assert "if(metadataHandled||settled)return;" in preview


def test_invalid_trim_edits_do_not_mutate_previous_value():
    source = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    start = source.index("function updateTimelineTrim(item,field,rawValue)")
    end = source.index('\n$("timelineEditor").addEventListener("change"', start)
    helper = source[start:end]

    assert "const previous=item[field];" in helper
    assert "item.trimEnd<=next" in helper
    assert "next<=item.trimStart" in helper
    assert "item[field]=next;" in helper
    assert helper.index("item.trimEnd<=next") < helper.index("item[field]=next;")
    assert helper.index("next<=item.trimStart") < helper.index("item[field]=next;")


def test_timeline_scene_description_limit_matches_render_api():
    source = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    start = source.index("function renderTimelineEditor(rows=timelineRows())")
    end = source.index('\n$("flowClipImportButton")', start)
    editor = source[start:end]

    assert 'maxlength="500"' in editor
    assert 'maxlength="1000"' not in editor
