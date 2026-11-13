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


def voice_status():
    enabled = os.getenv("ENABLE_PAID_MEDIA_GENERATION", "false").strip().lower() == "true" and paid_upgrades_allowed()
    configured = bool(os.getenv("OPENAI_API_KEY"))
    token_configured = bool(os.getenv("MEDIA_GENERATION_TOKEN"))
    configured_executable = os.getenv("PIPER_EXECUTABLE") or "piper"
    piper_executable = shutil.which(configured_executable) or (configured_executable if Path(configured_executable).is_file() else None)
    piper_model = os.getenv("PIPER_MODEL_PATH", "")
    local_available = bool(piper_executable and piper_model and Path(piper_model).is_file())
    return {
        "available": local_available or (enabled and configured and token_configured),
        "local_available": local_available,
        "local_engine": "Piper TTS",
        "local_model_configured": bool(piper_model and Path(piper_model).is_file()),
        "enabled_by_admin": enabled,
        "provider_configured": configured,
        "access_token_required": True,
        "access_token_configured": token_configured,
        "provider": "Piper local / optional OpenAI",
        "model": os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"),
        "format": "MP3",
        "notice": "Paid APIs remain locked until revenue is confirmed and the user explicitly approves upgrades.",
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
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        audio_id = uuid.uuid4().hex
        output = AUDIO_DIR / f"{audio_id}.wav"
        configured_executable = os.getenv("PIPER_EXECUTABLE") or "piper"
        executable = shutil.which(configured_executable) or (configured_executable if Path(configured_executable).is_file() else None)
        if not executable:
            raise VoiceUnavailable("Piper executable is not installed or not on PATH.")
        model = os.environ["PIPER_MODEL_PATH"]
        try:
            completed = subprocess.run([executable, "--model", model, "--output_file", str(output)],
                                       input=text.strip(), text=True, capture_output=True, timeout=180, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise VoiceGenerationFailed("Piper local TTS could not start or timed out.") from None
        if completed.returncode != 0 or not output.is_file():
            output.unlink(missing_ok=True)
            raise VoiceGenerationFailed("Piper local TTS failed. Check the selected voice model.")
        try:
            audio_info = _validate_audio_file(output, "wav")
        except VoiceGenerationFailed:
            output.unlink(missing_ok=True)
            raise
        return {"audio_id": audio_id, "filename": output.name, "url": f"/api/audio/{audio_id}",
                "format": "WAV", "voice": "Piper local", "provider": "Piper (local)", "model": Path(model).name,
                "size_bytes": audio_info["size_bytes"], "local": True,
                "notice": "Locally generated speech. Review pronunciation and voice-model license before publishing."}
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
