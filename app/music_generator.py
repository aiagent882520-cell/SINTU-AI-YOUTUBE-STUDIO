"""Optional Stable Audio 3 music generation through Stability AI."""
from pathlib import Path
from .policy import paid_upgrades_allowed
import os
import uuid
import math
import struct
import wave
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("SINTU_DATA_DIR", str(ROOT))).expanduser().resolve()
MUSIC_DIR = DATA_DIR / "generated_music"
ENDPOINT = "https://api.stability.ai/v2beta/audio/stable-audio/text-to-audio"
MODEL = "stable-audio-3"
MAX_AUDIO_BYTES = 30 * 1024 * 1024


class MusicUnavailable(Exception):
    pass


class MusicGenerationFailed(Exception):
    pass


def music_status():
    enabled = os.getenv("ENABLE_PAID_MEDIA_GENERATION", "").lower() == "true" and paid_upgrades_allowed()
    key_set = bool(os.getenv("STABILITY_API_KEY"))
    return {
        "available": True,
        "local_available": True,
        "paid_available": enabled and key_set,
        "local_engine": "SINTU Procedural Composer",
        "provider": "SINTU Procedural Composer / optional Stability AI",
        "model": MODEL,
        "enabled": enabled,
        "api_key_configured": key_set,
        "max_duration_seconds": 360,
        "note": "Free procedural ambient soundtrack is always available. Paid Stable Audio remains locked until revenue and explicit approval.",
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


def _generate_procedural(prompt: str, duration: int) -> dict:
    sample_rate = 22050
    loop_seconds = 8
    frequencies = [110.0, 138.59, 164.81, 220.0]
    lowered = prompt.lower()
    if any(word in lowered for word in ("dark", "mystery", "horror", "suspense")):
        frequencies = [82.41, 98.0, 123.47, 164.81]
    elif any(word in lowered for word in ("happy", "joy", "bright", "celebration")):
        frequencies = [130.81, 164.81, 196.0, 261.63]
    samples = bytearray()
    total = sample_rate * loop_seconds
    for i in range(total):
        t = i / sample_rate
        slow = 0.5 + 0.5 * math.sin(2 * math.pi * 0.08 * t)
        tone = (0.34 * math.sin(2 * math.pi * frequencies[0] * t)
                + 0.22 * math.sin(2 * math.pi * frequencies[1] * t)
                + 0.16 * math.sin(2 * math.pi * frequencies[2] * t)
                + 0.08 * math.sin(2 * math.pi * frequencies[3] * t))
        shimmer = 0.05 * math.sin(2 * math.pi * (frequencies[3] * 2) * t + 0.4 * math.sin(2 * math.pi * 0.12 * t))
        fade = min(1.0, t / 0.7, (loop_seconds - t) / 0.7)
        value = max(-1.0, min(1.0, (tone * (0.55 + slow * 0.25) + shimmer) * fade * 0.65))
        samples.extend(struct.pack("<h", int(value * 32767)))
    loop = bytes(samples)
    AUDIO_DIR = MUSIC_DIR
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    music_id = uuid.uuid4().hex
    output = AUDIO_DIR / f"{music_id}.wav"
    with wave.open(str(output), "wb") as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(sample_rate)
        remaining = duration
        while remaining > 0:
            chunk_seconds = min(loop_seconds, remaining)
            wav.writeframesraw(loop[:chunk_seconds * sample_rate * 2])
            remaining -= chunk_seconds
        wav.writeframes(b"")
    return {"music_id": music_id, "url": f"/api/music/{music_id}", "format": "WAV",
            "size_bytes": output.stat().st_size, "duration_seconds": duration,
            "provider": "SINTU Procedural Composer (local)", "model": "Original ambient synthesis",
            "local": True, "notice": "Original procedurally synthesized ambient audio; not a trained AI music model. Review before publishing."}

def generate_music(prompt: str, duration: int = 30) -> dict:
    prompt = prompt.strip()
    if not prompt or len(prompt) > 2000:
        raise ValueError("Music prompt 1 se 2000 characters ka hona chahiye.")
    if not 5 <= duration <= 360:
        raise ValueError("Music duration 5 se 360 seconds ke beech honi chahiye.")
    status = music_status()
    if os.getenv("MUSIC_PROVIDER", "local").strip().lower() != "stability" or not status["paid_available"]:
        return _generate_procedural(prompt, duration)

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
