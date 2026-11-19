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
    assert 'video.removeEventListener("seeked",onSeeked)' in preview
    assert 'video.addEventListener("seeked",onSeeked,{once:true})' in preview
    assert "playbackStarted=false" in preview
    assert "if(!Number.isFinite(video.duration)||trimStart>=video.duration)" in preview
    assert 'video.removeEventListener("timeupdate",onTimeUpdate)' in preview
    assert 'video.removeEventListener("ended",onEnded)' in preview
    assert "video.pause()" in preview
    assert "item.trimEnd!=null&&video.currentTime>=item.trimEnd" in preview
    assert "playback.catch" in preview


def test_timeline_preview_uses_current_image_item_without_stale_index():
    source = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    start = source.index("let activeTimelinePreview = null;")
    end = source.index('\n$("timelinePreviewPlay").addEventListener', start)
    preview = source[start:end]

    assert "const waitForImage=(item,durationMs)=>" in preview
    assert '"/api/images/' in preview and "item.id" in preview
    assert "rows[index].id" not in preview
    assert "const startPlayback=()=>" in preview
    assert "const onSeeked=()=>startPlayback();" in preview
    assert "const playback=video.play();" in preview
    assert "startPlayback();" in preview


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


def test_timeline_trim_limits_match_render_api():
    source = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    start = source.index("function renderTimelineEditor(rows=timelineRows())")
    end = source.index('\n$("flowClipImportButton")', start)
    editor = source[start:end]

    assert 'max="600" step="0.1" data-field="trimStart"' in editor
    assert 'max="600" step="0.1" data-field="trimEnd"' in editor
    helper_start = source.index("function updateTimelineTrim(item,field,rawValue)")
    helper_end = source.index('\n$("timelineEditor").addEventListener("change"', helper_start)
    assert "next>600" in source[helper_start:helper_end]


def test_render_preflight_rejects_timeline_scene_and_subtitle_misalignment():
    source = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    start = source.index('$("renderButton").addEventListener("click"')
    end = source.index('\n$("musicUploadButton")', start)
    handler = source[start:end]

    assert "rawTimelineLines.length && rows.length !== rawTimelineLines.length" in handler
    assert "rawSceneLines.length !== rows.length || rawSceneLines.some(line => !line)" in handler
    assert "subtitles.length !== rows.length" in handler
    assert "timeline_items: structuredTimelineItems(rows)" in handler
    assert "subtitles," in handler


def test_timeline_reorder_and_remove_keep_aligned_subtitle_rows():
    source = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    start = source.index('$("timelineEditor").addEventListener("click"')
    end = source.index('\n$("timelineEditor").addEventListener("input"', start)
    handler = source[start:end]

    assert "const subtitlesAligned=subtitleRows.length===rows.length" in handler
    assert "subtitleRows.splice(i,1)" in handler
    assert "[subtitleRows[i-1],subtitleRows[i]]=[subtitleRows[i],subtitleRows[i-1]]" in handler
    assert "[subtitleRows[i+1],subtitleRows[i]]=[subtitleRows[i],subtitleRows[i+1]]" in handler
    assert "subtitleField.value=subtitleRows.join(" in handler


def test_image_timeline_preview_waits_for_load_and_cleans_up_on_cancel():
    source = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    start = source.index(" const waitForImage=(item,durationMs)=>")
    end = source.index(" const waitForVideo=(item)=>", start)
    preview = source[start:end]

    assert 'image.addEventListener("load",onLoad,{once:true})' in preview
    assert 'image.addEventListener("error",onError,{once:true})' in preview
    assert "if(image.complete){if(image.naturalWidth>0)onLoad();else onError();}" in preview
    assert "timer=setTimeout(()=>finish(true),durationMs)" in preview
    assert "image.removeEventListener(\"load\",onLoad)" in preview
    assert "image.removeEventListener(\"error\",onError)" in preview
    assert "finishCurrent=keepGoing=>finish(keepGoing)" in preview


def test_timeline_subtitle_reorder_ignores_trailing_blank_lines():
    source = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    start = source.index('$("timelineEditor").addEventListener("click"')
    end = source.index('$("timelineEditor").addEventListener("input"', start)
    handler = source[start:end]

    assert 'const subtitleRows=subtitleText.trim()?subtitleText.split("\\n"):[];' in handler
    assert 'while(subtitleRows.length&&!subtitleRows[subtitleRows.length-1].trim())subtitleRows.pop();' in handler
    assert "const subtitlesAligned=subtitleRows.length===rows.length;" in handler
