from pathlib import Path
from types import SimpleNamespace

from app import voice_generator


def test_local_engine_detects_hindi_espeak_when_piper_is_unavailable(monkeypatch):
    # Ignore device-level .env overrides so this unit test is deterministic.
    monkeypatch.delenv("ESPEAK_EXECUTABLE", raising=False)
    monkeypatch.delenv("PIPER_EXECUTABLE", raising=False)
    monkeypatch.delenv("PIPER_MODEL_PATH", raising=False)
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


def test_local_engine_prefers_termux_espeak_ng_binary(monkeypatch):
    monkeypatch.delenv("ESPEAK_EXECUTABLE", raising=False)
    monkeypatch.delenv("PIPER_EXECUTABLE", raising=False)
    monkeypatch.delenv("PIPER_MODEL_PATH", raising=False)

    def which(name):
        return "/data/data/com.termux/files/usr/bin/espeak-ng" if name == "espeak-ng" else None

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

    assert voice_generator._local_tts_engines() == (
        "eSpeak NG Hindi",
        "/data/data/com.termux/files/usr/bin/espeak-ng",
        None,
    )


def test_local_engine_discovers_project_managed_hindi_piper_model(tmp_path, monkeypatch):
    model = tmp_path / "models" / "voices" / "hi_IN-pratham-medium.onnx"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"model-placeholder")
    monkeypatch.setattr(voice_generator, "DATA_DIR", tmp_path)
    monkeypatch.delenv("PIPER_MODEL_PATH", raising=False)
    monkeypatch.delenv("PIPER_EXECUTABLE", raising=False)
    monkeypatch.delenv("ESPEAK_EXECUTABLE", raising=False)
    monkeypatch.setattr(voice_generator.shutil, "which", lambda name: "/usr/bin/piper" if name == "piper" else None)
    assert voice_generator._local_tts_engines() == ("Piper TTS", "/usr/bin/piper", str(model))


def test_local_engine_discovers_project_managed_female_piper_model(tmp_path, monkeypatch):
    model = tmp_path / "models" / "voices" / "hi_IN-priyamvada-medium.onnx"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"female-model-placeholder")
    monkeypatch.setattr(voice_generator, "DATA_DIR", tmp_path)
    monkeypatch.delenv("PIPER_FEMALE_MODEL_PATH", raising=False)
    monkeypatch.delenv("PIPER_EXECUTABLE", raising=False)
    monkeypatch.setattr(voice_generator.shutil, "which", lambda name: "/usr/bin/piper" if name == "piper" else None)

    assert voice_generator._local_tts_engines("female") == ("Piper TTS", "/usr/bin/piper", str(model))


def test_female_voice_never_falls_back_to_synthetic_espeak(monkeypatch):
    monkeypatch.delenv("PIPER_FEMALE_MODEL_PATH", raising=False)
    monkeypatch.delenv("PIPER_EXECUTABLE", raising=False)
    monkeypatch.delenv("PIPER_MODEL_PATH", raising=False)
    monkeypatch.delenv("ESPEAK_EXECUTABLE", raising=False)
    monkeypatch.setattr(voice_generator.shutil, "which", lambda name: "/usr/bin/espeak-ng" if name == "espeak-ng" else None)
    monkeypatch.setattr(
        voice_generator.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout="Pty Language Age/Gender VoiceName File\\n 5 hi M Hindi\\n", stderr=""
        ),
    )

    assert voice_generator._local_tts_engines("female") == (None, None, None)


def test_local_piper_voice_selection_uses_requested_female_model(tmp_path, monkeypatch):
    model = tmp_path / "hi_IN-priyamvada-medium.onnx"
    model.write_bytes(b"female-model-placeholder")
    monkeypatch.setattr(voice_generator, "AUDIO_DIR", tmp_path / "audio")
    monkeypatch.setattr(voice_generator, "voice_status", lambda: {"local_available": True})
    monkeypatch.setattr(
        voice_generator, "_local_tts_engines",
        lambda speaker="male": ("Piper TTS", "/usr/bin/piper", str(model) if speaker == "female" else ""),
    )
    monkeypatch.setattr(voice_generator, "_validate_audio_file", lambda path, expected: {"size_bytes": path.stat().st_size})
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        output = Path(command[command.index("--output_file") + 1])
        output.write_bytes(b"RIFF" + (36).to_bytes(4, "little") + b"WAVE" + b"\\x00" * 36)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(voice_generator.subprocess, "run", fake_run)
    result = voice_generator.generate_voiceover("नमस्कार, आपका स्वागत है।", "female")

    assert captured["command"][captured["command"].index("--model") + 1] == str(model)
    assert result["speaker"] == "female"
    assert result["voice_name"] == "Priyamvada"
