import copy

from scripts.repair_media import needs_audio_repair


def metadata(codec="aac", sample_rate="48000", channels=2):
    return {
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p"},
            {"codec_type": "audio", "codec_name": codec,
             "sample_rate": sample_rate, "channels": channels},
        ]
    }


def test_media_repair_leaves_valid_aac_stereo_untouched():
    assert needs_audio_repair(metadata()) is False


def test_media_repair_detects_non_48000_audio():
    assert needs_audio_repair(metadata(sample_rate="44100")) is True


def test_media_repair_detects_mono_audio():
    assert needs_audio_repair(metadata(channels=1)) is True


def test_media_repair_detects_non_aac_audio():
    assert needs_audio_repair(metadata(codec="mp3")) is True


def test_media_repair_does_not_add_audio_to_silent_video():
    assert needs_audio_repair({"streams": [
        {"codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p"}
    ]}) is False


def test_media_repair_handles_invalid_audio_metadata():
    assert needs_audio_repair(metadata(sample_rate="unknown")) is True
