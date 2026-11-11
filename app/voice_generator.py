"""Optional OpenAI text-to-speech integration for SINTU AI STUDIO.

Paid generation is disabled unless ENABLE_PAID_MEDIA_GENERATION=true.
"""
from pathlib import Path
from .policy import paid_upgrades_allowed
import os
import uuid

DATA_DIR = Path(os.getenv("SINTU_DATA_DIR", str(Path(__file__).resolve().parent.parent))).expanduser().resolve()
AUDIO_DIR = DATA_DIR / "generated_audio"
ALLOWED_VOICES = {"alloy", "ash", "ballad", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer", "verse"}


class VoiceUnavailable(Exception):
    pass


class VoiceGenerationFailed(Exception):
    pass


def voice_status():
    enabled = os.getenv("ENABLE_PAID_MEDIA_GENERATION", "false").strip().lower() == "true" and paid_upgrades_allowed()
    configured = bool(os.getenv("OPENAI_API_KEY"))
    token_configured = bool(os.getenv("MEDIA_GENERATION_TOKEN"))
    return {
        "available": enabled and configured and token_configured,
        "enabled_by_admin": enabled,
        "provider_configured": configured,
        "access_token_required": True,
        "access_token_configured": token_configured,
        "provider": "OpenAI",
        "model": os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"),
        "format": "MP3",
        "notice": "Paid APIs remain locked until revenue is confirmed and the user explicitly approves upgrades.",
    }


def generate_voiceover(text: str, voice: str = "alloy") -> dict:
    status = voice_status()
    if not status["enabled_by_admin"]:
        raise VoiceUnavailable("Paid media generation is disabled by server administrator.")
    if not status["provider_configured"]:
        raise VoiceUnavailable("OpenAI API key is not configured on the server.")
    if voice not in ALLOWED_VOICES:
        raise ValueError("Unsupported voice selection.")
    if not text.strip() or len(text) > 4000:
        raise ValueError("Voiceover text must contain 1 to 4000 characters.")
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
        response.stream_to_file(str(output))
        if not output.is_file() or output.stat().st_size == 0:
            output.unlink(missing_ok=True)
            raise VoiceGenerationFailed("Voice provider returned an empty audio file.")
        return {
            "audio_id": audio_id,
            "filename": output.name,
            "url": f"/api/audio/{audio_id}",
            "format": "MP3",
            "voice": voice,
            "model": status["model"],
            "size_bytes": output.stat().st_size,
            "notice": "AI-generated voiceover. Review pronunciation and rights before publishing.",
        }
    except (VoiceUnavailable, VoiceGenerationFailed, ValueError):
        raise
    except Exception as exc:
        raise VoiceGenerationFailed(f"Voice generation failed ({type(exc).__name__}). Check API quota and model access.") from None
