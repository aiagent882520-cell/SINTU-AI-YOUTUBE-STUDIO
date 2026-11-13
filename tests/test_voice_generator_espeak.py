from pathlib import Path
from types import SimpleNamespace

from app import voice_generator


def test_local_engine_detects_hindi_espeak_when_piper_is_unavailable(monkeypatch):
    def which(name):
        return "/usr/bin/espeak" if name == "espeak" else None

    monkeypatch.setattr(voice_generator.shutil, "which", which)
    monkeypatch.setattr(
        voice_generator.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="Pty Language Age/Gender VoiceName File\n 5 hi M Hindi\n",
            stderr="",
        ),
    )

    assert voice_generator._local_tts_engines() == ("eSpeak NG Hindi", "/usr/bin/espeak", None)


def test_espeak_generates_validated_local_hindi_wav(tmp_path, monkeypatch):
    monkeypatch.setattr(voice_generator, "AUDIO_DIR", tmp_path)
    monkeypatch.setattr(
        voice_generator,
        "voice_status",
        lambda: {"local_available": True},
    )
    monkeypatch.setattr(
        voice_generator,
        "_local_tts_engines",
        lambda: ("eSpeak NG Hindi", "/usr/bin/espeak", None),
    )
    monkeypatch.setattr(
        voice_generator,
        "_validate_audio_file",
        lambda path, expected: {"size_bytes": path.stat().st_size},
    )
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["input"] = kwargs.get("input")
        output = Path(command[command.index("-w") + 1])
        output.write_bytes(
            b"RIFF" + (36).to_bytes(4, "little") + b"WAVE" + b"\x00" * 36
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(voice_generator.subprocess, "run", fake_run)
    result = voice_generator.generate_voiceover("नमस्कार, आपका स्वागत है।")

    assert captured["command"][:4] == ["/usr/bin/espeak", "-v", "hi", "-s"]
    assert "--stdin" in captured["command"]
    assert captured["input"] == "नमस्कार, आपका स्वागत है।"
    assert result["provider"] == "Local TTS"
    assert result["voice"] == "eSpeak NG Hindi"
    assert result["format"] == "WAV"
    assert result["local"] is True
    assert (tmp_path / result["filename"]).is_file()
