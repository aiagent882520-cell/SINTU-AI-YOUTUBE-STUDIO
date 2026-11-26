"""Optional OpenAI text-to-speech integration for SINTU AI STUDIO.

Paid generation is disabled unless ENABLE_PAID_MEDIA_GENERATION=true.
"""
from pathlib import Path
from .policy import paid_upgrades_allowed
import json
import os
import shutil
import subprocess
import uuid

DATA_DIR = Path(os.getenv("SINTU_DATA_DIR", str(Path(__file__).resolve().parent.parent))).expanduser().resolve()
AUDIO_DIR = DATA_DIR / "generated_audio"
ALLOWED_VOICES = {"alloy", "ash", "ballad", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer", "verse"}


class VoiceUnavailable(Exception):
    pass


class VoiceGenerationFailed(Exception):
    pass


MAX_AUDIO_BYTES = 50 * 1024 * 1024
MAX_AUDIO_SECONDS = 600


def _write_bounded_audio(chunks, output: Path) -> int:
    """Write streamed provider audio without allowing unbounded disk consumption."""
    output.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    try:
        with output.open("wb") as stream:
            for chunk in chunks:
                if not isinstance(chunk, (bytes, bytearray)):
                    raise VoiceGenerationFailed("Voice provider returned invalid audio chunks.")
                total += len(chunk)
                if total > MAX_AUDIO_BYTES:
                    raise VoiceGenerationFailed("Generated audio exceeded the 50 MB size limit.")
                stream.write(chunk)
        if total == 0:
            raise VoiceGenerationFailed("Voice provider returned an empty audio file.")
        return total
    except VoiceGenerationFailed:
        output.unlink(missing_ok=True)
        raise
    except Exception:
        output.unlink(missing_ok=True)
        raise VoiceGenerationFailed("Voice provider audio stream could not be saved.") from None


def _validate_audio_file(output: Path, expected_format: str) -> dict:
    """Check audio container signature, size, and duration when FFprobe is available."""
    try:
        size = output.stat().st_size
        with output.open("rb") as stream:
            header = stream.read(12)
    except OSError:
        raise VoiceGenerationFailed("Generated audio file could not be read.") from None
    if size < 44 or size > MAX_AUDIO_BYTES:
        raise VoiceGenerationFailed("Generated audio size is outside the safe limits.")
    if expected_format == "wav":
        valid_header = len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WAVE"
    elif expected_format == "mp3":
        valid_header = header.startswith(b"ID3") or (
            len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0
        )
    else:
        valid_header = False
    if not valid_header:
        raise VoiceGenerationFailed("Generated audio has an invalid file signature.")

    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        try:
            probe = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_type",
                 "-of", "json", str(output)],
                capture_output=True, text=True, timeout=20, check=False
            )
            metadata = json.loads(probe.stdout) if probe.returncode == 0 else {}
            duration = float(metadata.get("format", {}).get("duration", 0))
            has_audio = any(item.get("codec_type") == "audio" for item in metadata.get("streams", []))
        except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, json.JSONDecodeError):
            raise VoiceGenerationFailed("FFprobe could not verify the generated audio.") from None
        if not has_audio or not 0.1 <= duration <= MAX_AUDIO_SECONDS:
            raise VoiceGenerationFailed("Generated audio duration or audio stream is invalid.")
    return {"size_bytes": size}


def _find_executable(configured: str) -> str | None:
    return shutil.which(configured) or (configured if Path(configured).is_file() else None)


def _normalize_local_voice(voice: str) -> str:
    """Normalize an explicit Hindi speaker choice; legacy 'alloy' remains male."""
    value = str(voice or "male").strip().casefold()
    if value in {"male", "pratham", "alloy", "onyx", "ash", "echo"}:
        return "male"
    if value in {"female", "priyamvada", "nova", "shimmer", "coral", "sage", "ballad", "fable", "verse"}:
        return "female"
    raise ValueError("Hindi local voice must be male/pratham or female/priyamvada.")


def _piper_model_for_voice(voice: str) -> str:
    """Resolve only an installed, speaker-matched Hindi Piper model."""
    speaker = _normalize_local_voice(voice)
    filename = f"hi_IN-{'pratham' if speaker == 'male' else 'priyamvada'}-medium.onnx"
    configured = os.getenv("PIPER_MODEL_PATH" if speaker == "male" else "PIPER_FEMALE_MODEL_PATH", "").strip()
    if configured:
        return configured if Path(configured).is_file() else ""
    candidates = [
        DATA_DIR / "models" / "voices" / filename,
        Path(__file__).resolve().parent.parent / "models" / "voices" / filename,
    ]
    return str(next((candidate for candidate in candidates if candidate.is_file()), ""))


def _local_tts_engines(voice: str = "male") -> tuple[str | None, str | None, str | None]:
    """Return (engine, executable, model) for the requested speaker.

    eSpeak is deliberately male-only here: it must never silently replace a requested
    female neural voice with a different synthetic speaker.
    """
    speaker = _normalize_local_voice(voice)
    piper_executable = _find_executable(os.getenv("PIPER_EXECUTABLE") or "piper")
    piper_model = _piper_model_for_voice(speaker)
    if piper_executable and piper_model:
        return "Piper TTS", piper_executable, piper_model
    if speaker == "female":
        return None, None, None

    configured_espeak = os.getenv("ESPEAK_EXECUTABLE")
    espeak_names = [configured_espeak] if configured_espeak else ["espeak-ng", "espeak"]
    for espeak_name in espeak_names:
        espeak_executable = _find_executable(espeak_name)
        if not espeak_executable:
            continue
        try:
            voices = subprocess.run(
                [espeak_executable, "--voices=hi"],
                capture_output=True, text=True, timeout=10, check=False
            )
            if voices.returncode == 0 and any(
                line.split() and line.split()[1].lower() == "hi"
                for line in voices.stdout.splitlines()[1:]
            ):
                return "eSpeak NG Hindi", espeak_executable, None
        except (OSError, subprocess.TimeoutExpired):
            continue
    return None, None, None


def voice_status():
    enabled = os.getenv("ENABLE_PAID_MEDIA_GENERATION", "false").strip().lower() == "true" and paid_upgrades_allowed()
    configured = bool(os.getenv("OPENAI_API_KEY"))
    token_configured = bool(os.getenv("MEDIA_GENERATION_TOKEN"))
    male = _local_tts_engines("male")
    female = _local_tts_engines("female")
    local_available = bool((male[0] and male[1]) or (female[0] and female[1]))
    selected = male if male[0] and male[1] else female
    return {
        "available": local_available or (enabled and configured and token_configured),
        "local_available": local_available,
        "local_engine": selected[0] or "Not installed",
        "local_model_configured": bool(selected[2]),
        "local_voices": {
            "male": {"available": bool(male[0] and male[1]), "engine": male[0] or "Not installed",
                     "model": Path(male[2]).name if male[2] else None},
            "female": {"available": bool(female[0] and female[1]), "engine": female[0] or "Not installed",
                       "model": Path(female[2]).name if female[2] else None},
        },
        "enabled_by_admin": enabled,
        "provider_configured": configured,
        "access_token_required": not local_available,
        "access_token_configured": token_configured,
        "provider": "Piper / eSpeak NG local / optional OpenAI",
        "model": os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"),
        "format": "WAV or MP3",
        "notice": "Piper Hindi male/female models are selectable when installed. eSpeak NG is synthetic and is never presented as natural human voice. Paid APIs remain locked until revenue is confirmed and the user explicitly approves upgrades.",
    }

def hindi_letter_ratio(text: str) -> float:
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return 0.0
    hindi_letters = sum("\u0900" <= char <= "\u097F" for char in letters)
    return hindi_letters / len(letters)


def generate_voiceover(text: str, voice: str = "alloy") -> dict:
    status = voice_status()
    if not text.strip() or len(text) > 4000:
        raise ValueError("Voiceover text must contain 1 to 4000 characters.")
    if status["local_available"]:
        if hindi_letter_ratio(text) < 0.95:
            raise ValueError("Video voiceover must be at least 95% Hindi in Devanagari. Rewrite the narration in Hindi.")
        speaker = _normalize_local_voice(voice)
        engine, executable, model = _local_tts_engines(speaker)
        if not executable or not engine:
            requested = "female (Priyamvada)" if speaker == "female" else "male (Pratham)"
            raise VoiceUnavailable(f"Hindi {requested} Piper model is not installed. Run scripts/setup_hindi_voice.sh and verify the model paths.")
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        audio_id = uuid.uuid4().hex
        output = AUDIO_DIR / f"{audio_id}.wav"
        try:
            if engine == "Piper TTS":
                completed = subprocess.run(
                    [executable, "--model", model, "--output_file", str(output)],
                    input=text.strip(), text=True, capture_output=True, timeout=180, check=False
                )
            else:
                speed = os.getenv("ESPEAK_SPEED", "135")
                try:
                    speed_value = max(80, min(250, int(speed)))
                except ValueError:
                    speed_value = 135
                completed = subprocess.run(
                    [executable, "-v", "hi", "-s", str(speed_value), "-w", str(output), "--stdin"],
                    input=text.strip(), text=True, capture_output=True, timeout=180, check=False
                )
        except (OSError, subprocess.TimeoutExpired):
            output.unlink(missing_ok=True)
            raise VoiceGenerationFailed(f"{engine} could not start or timed out.") from None
        if completed.returncode != 0 or not output.is_file():
            output.unlink(missing_ok=True)
            raise VoiceGenerationFailed(f"{engine} failed to generate Hindi speech.")
        try:
            audio_info = _validate_audio_file(output, "wav")
        except VoiceGenerationFailed:
            output.unlink(missing_ok=True)
            raise
        return {
            "audio_id": audio_id, "filename": output.name,
            "url": f"/api/audio/{audio_id}", "format": "WAV",
            "voice": engine, "speaker": "female" if speaker == "female" else "male",
            "voice_name": "Priyamvada" if speaker == "female" and engine == "Piper TTS" else
                          "Pratham" if speaker == "male" and engine == "Piper TTS" else "eSpeak NG Hindi (synthetic)",
            "provider": "Local TTS", "model": model and Path(model).name or "Hindi",
            "size_bytes": audio_info["size_bytes"], "local": True,
            "notice": ("Piper neural Hindi voice. Review pronunciation and listen to the result before publishing."
                       if engine == "Piper TTS" else
                       "eSpeak NG is synthetic speech, not a natural human voice. Review pronunciation; it is a fallback only.")
        }
    if not status["enabled_by_admin"]:
        raise VoiceUnavailable("Paid media generation is disabled by server administrator.")
    if not status["provider_configured"]:
        raise VoiceUnavailable("OpenAI API key is not configured on the server.")
    if hindi_letter_ratio(text) < 0.95:
        raise ValueError("Video voiceover must be at least 95% Hindi in Devanagari. Rewrite the narration in Hindi.")
    if voice not in ALLOWED_VOICES:
        raise ValueError("Unsupported voice selection.")
    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=90.0, max_retries=1)
        response = client.audio.speech.create(
            model=status["model"],
            voice=voice,
            input=text.strip(),
            response_format="mp3",
        )
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        audio_id = uuid.uuid4().hex
        output = AUDIO_DIR / f"{audio_id}.mp3"
        _write_bounded_audio(response.iter_bytes(chunk_size=64 * 1024), output)
        audio_info = _validate_audio_file(output, "mp3")
        return {
            "audio_id": audio_id,
            "filename": output.name,
            "url": f"/api/audio/{audio_id}",
            "format": "MP3",
            "voice": voice,
            "model": status["model"],
            "size_bytes": audio_info["size_bytes"],
            "notice": "AI-generated voiceover. Review pronunciation and rights before publishing.",
        }
    except (VoiceUnavailable, VoiceGenerationFailed, ValueError):
        raise
    except Exception as exc:
        if "output" in locals():
            output.unlink(missing_ok=True)
        raise VoiceGenerationFailed(f"Voice generation failed ({type(exc).__name__}). Check API quota and model access.") from None
