import pytest

from app import voice_generator


def test_bounded_audio_writer_saves_chunks(tmp_path):
    output = tmp_path / "voice.mp3"
    size = voice_generator._write_bounded_audio([b"ID3", b"audio-data"], output)
    assert size == 13
    assert output.read_bytes() == b"ID3audio-data"


def test_bounded_audio_writer_rejects_oversized_stream_and_cleans_file(tmp_path):
    output = tmp_path / "voice.mp3"
    with pytest.raises(voice_generator.VoiceGenerationFailed, match="50 MB"):
        voice_generator._write_bounded_audio(
            [b"x" * voice_generator.MAX_AUDIO_BYTES, b"x"], output
        )
    assert not output.exists()


def test_bounded_audio_writer_rejects_empty_stream(tmp_path):
    output = tmp_path / "voice.mp3"
    with pytest.raises(voice_generator.VoiceGenerationFailed, match="empty"):
        voice_generator._write_bounded_audio([], output)
    assert not output.exists()


def test_audio_validator_accepts_wav_header_without_optional_ffprobe(tmp_path, monkeypatch):
    monkeypatch.setattr(voice_generator.shutil, "which", lambda _: None)
    output = tmp_path / "voice.wav"
    output.write_bytes(b"RIFF" + (36).to_bytes(4, "little") + b"WAVE" + b"\x00" * 36)
    result = voice_generator._validate_audio_file(output, "wav")
    assert result["size_bytes"] == 48


def test_audio_validator_rejects_invalid_mp3_header(tmp_path, monkeypatch):
    monkeypatch.setattr(voice_generator.shutil, "which", lambda _: None)
    output = tmp_path / "voice.mp3"
    output.write_bytes(b"not-a-real-mp3-audio-file" + b"\x00" * 30)
    with pytest.raises(voice_generator.VoiceGenerationFailed, match="signature"):
        voice_generator._validate_audio_file(output, "mp3")


def test_audio_validator_rejects_oversized_file(tmp_path, monkeypatch):
    monkeypatch.setattr(voice_generator.shutil, "which", lambda _: None)
    output = tmp_path / "voice.wav"
    output.write_bytes(b"RIFF" + b"\x00" * (voice_generator.MAX_AUDIO_BYTES))
    with pytest.raises(voice_generator.VoiceGenerationFailed, match="safe limits"):
        voice_generator._validate_audio_file(output, "wav")
