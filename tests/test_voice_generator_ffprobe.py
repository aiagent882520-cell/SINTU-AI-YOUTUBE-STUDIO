import json
from types import SimpleNamespace

import pytest

from app import voice_generator


def wav_file(path):
    path.write_bytes(b"RIFF" + (36).to_bytes(4, "little") + b"WAVE" + b"\x00" * 36)
    return path


def test_audio_validator_checks_ffprobe_stream_and_duration(tmp_path, monkeypatch):
    output = wav_file(tmp_path / "valid.wav")
    monkeypatch.setattr(voice_generator.shutil, "which", lambda name: "/usr/bin/ffprobe")
    monkeypatch.setattr(voice_generator.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0,
        stdout=json.dumps({"format": {"duration": "1.25"}, "streams": [{"codec_type": "audio"}]}),
    ))
    assert voice_generator._validate_audio_file(output, "wav")["size_bytes"] == 48


@pytest.mark.parametrize("metadata", [
    {"format": {"duration": "601"}, "streams": [{"codec_type": "audio"}]},
    {"format": {"duration": "1.0"}, "streams": [{"codec_type": "video"}]},
])
def test_audio_validator_rejects_invalid_ffprobe_metadata(tmp_path, monkeypatch, metadata):
    output = wav_file(tmp_path / "bad.wav")
    monkeypatch.setattr(voice_generator.shutil, "which", lambda name: "/usr/bin/ffprobe")
    monkeypatch.setattr(voice_generator.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout=json.dumps(metadata),
    ))
    with pytest.raises(voice_generator.VoiceGenerationFailed, match="duration or audio stream"):
        voice_generator._validate_audio_file(output, "wav")
