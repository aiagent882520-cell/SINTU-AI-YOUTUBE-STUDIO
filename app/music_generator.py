"""Optional Stable Audio 3 music generation through Stability AI."""
from pathlib import Path
import os
import uuid
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parent.parent
MUSIC_DIR = ROOT / "generated_music"
ENDPOINT = "https://api.stability.ai/v2beta/audio/stable-audio/text-to-audio"
MODEL = "stable-audio-3"
MAX_AUDIO_BYTES = 30 * 1024 * 1024


class MusicUnavailable(Exception):
    pass


class MusicGenerationFailed(Exception):
    pass


def music_status():
    enabled = os.getenv("ENABLE_PAID_MEDIA_GENERATION", "").lower() == "true"
    key_set = bool(os.getenv("STABILITY_API_KEY"))
    return {
        "available": enabled and key_set,
        "provider": "Stability AI Stable Audio 3.0",
        "model": MODEL,
        "enabled": enabled,
        "api_key_configured": key_set,
        "max_duration_seconds": 360,
        "note": "Paid generation is off unless ENABLE_PAID_MEDIA_GENERATION=true and STABILITY_API_KEY are configured.",
    }


def _multipart(fields: dict[str, str], boundary: str) -> bytes:
    chunks = []
    for name, value in fields.items():
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
            value.encode("utf-8"),
            b"\r\n",
        ])
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks)


def generate_music(prompt: str, duration: int = 30) -> dict:
    status = music_status()
    if not status["available"]:
        raise MusicUnavailable("AI music generation disabled hai. Server admin ko paid generation enable karke STABILITY_API_KEY secure secret mein set karna hoga.")
    prompt = prompt.strip()
    if not prompt or len(prompt) > 2000:
        raise ValueError("Music prompt 1 se 2000 characters ka hona chahiye.")
    if not 5 <= duration <= 360:
        raise ValueError("Music duration 5 se 360 seconds ke beech honi chahiye.")

    boundary = "----SINTUStableAudio" + uuid.uuid4().hex
    body = _multipart({
        "model": MODEL,
        "prompt": prompt,
        "duration": str(duration),
        "none": "",
    }, boundary)
    request = urllib.request.Request(
        ENDPOINT,
        data=body,
        headers={
            "Authorization": "Bearer " + os.environ["STABILITY_API_KEY"],
            "Content-Type": "multipart/form-data; boundary=" + boundary,
            "Accept": "audio/mpeg",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            audio = response.read(MAX_AUDIO_BYTES + 1)
            content_type = response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        detail = exc.read(1200).decode("utf-8", "replace")
        raise MusicGenerationFailed(f"Stability AI request failed ({exc.code}): {detail[:500]}") from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise MusicGenerationFailed(f"Stability AI connection failed: {str(exc)[:300]}") from None

    if len(audio) < 128 or len(audio) > MAX_AUDIO_BYTES:
        raise MusicGenerationFailed("Provider ne invalid ya 30 MB se badi audio file return ki.")
    if not (audio.startswith(b"ID3") or (len(audio) > 1 and audio[0] == 0xFF and audio[1] & 0xE0 == 0xE0)):
        raise MusicGenerationFailed("Provider response valid MP3 audio nahi hai.")
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    music_id = uuid.uuid4().hex
    output = MUSIC_DIR / f"{music_id}.mp3"
    output.write_bytes(audio)
    return {
        "music_id": music_id,
        "url": f"/api/music/{music_id}",
        "format": "MP3",
        "size_bytes": len(audio),
        "duration_seconds": duration,
        "provider": "Stability AI",
        "model": MODEL,
        "content_type": content_type,
        "notice": "AI-generated audio. Review provider terms and licensing before commercial publication.",
    }
