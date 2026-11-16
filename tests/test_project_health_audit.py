import copy

import pytest

from scripts.project_health_audit import validate_mp4_metadata


def _metadata(audio=True):
    streams = [{
        "codec_type": "video",
        "codec_name": "h264",
        "width": 720,
        "height": 1280,
        "pix_fmt": "yuv420p",
    }]
    if audio:
        streams.append({
            "codec_type": "audio",
            "codec_name": "aac",
            "sample_rate": "48000",
            "channels": 2,
        })
    return {
        "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "8.0"},
        "streams": streams,
    }


def test_android_mp4_audit_accepts_h264_aac_stereo():
    result = validate_mp4_metadata(_metadata())
    assert result["video_codec"] == "h264"
    assert result["pixel_format"] == "yuv420p"
    assert result["audio"] == {"codec": "aac", "sample_rate": 48000, "channels": 2}


def test_android_mp4_audit_accepts_silent_h264_video():
    assert validate_mp4_metadata(_metadata(audio=False))["audio"] is None


@pytest.mark.parametrize(("path", "value", "message"), [
    (("format", "format_name"), "matroska,webm", "container"),
    (("format", "duration"), "nan", "duration"),
    (("streams", 0, "codec_name"), "vp9", "H.264"),
    (("streams", 0, "pix_fmt"), "yuv444p", "yuv420p"),
    (("streams", 1, "codec_name"), "opus", "AAC"),
    (("streams", 1, "sample_rate"), "44100", "48000"),
    (("streams", 1, "channels"), 6, "stereo"),
])
def test_android_mp4_audit_rejects_incompatible_metadata(path, value, message):
    data = copy.deepcopy(_metadata())
    target = data
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(ValueError, match=message):
        validate_mp4_metadata(data)


def test_android_mp4_audit_rejects_missing_video_stream():
    data = _metadata()
    data["streams"] = [stream for stream in data["streams"] if stream["codec_type"] != "video"]
    with pytest.raises(ValueError, match="missing video"):
        validate_mp4_metadata(data)
