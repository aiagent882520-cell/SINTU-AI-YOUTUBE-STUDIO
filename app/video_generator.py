"""Optional Gemini Omni Flash text/image-to-video generation."""
from pathlib import Path
import base64
import json
import os
import re
import urllib.error
import urllib.request
import uuid
import time

from .image_generator import IMAGE_DIR

ROOT = Path(__file__).resolve().parent.parent
AI_VIDEO_DIR = ROOT / "generated_ai_videos"
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"
MODEL = "gemini-omni-1.1-flash"
MAX_VIDEO_BYTES = 100 * 1024 * 1024


class VideoUnavailable(Exception):
    pass


class VideoGenerationFailed(Exception):
    pass


def video_status():
    enabled = os.getenv("ENABLE_PAID_MEDIA_GENERATION", "").lower() == "true"
    key_set = bool(os.getenv("GEMINI_API_KEY"))
    return {
        "available": enabled and key_set,
        "provider": "Google Gemini API",
        "model": MODEL,
        "enabled": enabled,
        "api_key_configured": key_set,
        "modes": ["text-to-video", "image-to-video"],
        "aspect_ratios": ["9:16", "16:9"],
        "resolutions": ["360p", "720p", "1080p", "4k"],
        "max_clip_seconds": 10,
        "note": "Paid video generation is off unless ENABLE_PAID_MEDIA_GENERATION=true and GEMINI_API_KEY are configured. Provider pricing and regional availability apply.",
    }


def _validate_video(raw: bytes) -> bytes:
    if len(raw) < 16 or len(raw) > MAX_VIDEO_BYTES or raw[4:8] != b"ftyp":
        raise VideoGenerationFailed("Generated video invalid hai ya 100 MB size limit se badi hai.")
    return raw


def _extract_video(payload: dict) -> bytes:
    direct = payload.get("output_video")
    if isinstance(direct, dict) and isinstance(direct.get("data"), str):
        encoded = direct["data"]
    else:
        encoded = None
        for step in payload.get("steps", []):
            if not isinstance(step, dict):
                continue
            for item in step.get("content", []):
                if isinstance(item, dict) and item.get("type") == "video" and isinstance(item.get("data"), str):
                    encoded = item["data"]
                    break
            if encoded:
                break
    if not encoded:
        raise VideoGenerationFailed("Gemini response mein inline MP4 data nahi mila.")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception:
        raise VideoGenerationFailed("Gemini ne invalid video data return kiya.") from None
    return _validate_video(raw)


def _extract_video_file_id(payload: dict) -> str | None:
    direct = payload.get("output_video")
    uri = direct.get("uri") if isinstance(direct, dict) else None
    if not uri:
        for step in payload.get("steps", []):
            if not isinstance(step, dict):
                continue
            for item in step.get("content", []):
                if isinstance(item, dict) and item.get("type") == "video" and item.get("uri"):
                    uri = item["uri"]
                    break
            if uri:
                break
    if not isinstance(uri, str):
        return None
    match = re.fullmatch(r"https://generativelanguage\.googleapis\.com/v1beta/files/([A-Za-z0-9_-]+):download(?:\?alt=media)?", uri)
    return match.group(1) if match else None


def _download_video_file(file_id: str, api_key: str) -> bytes:
    status_url = f"https://generativelanguage.googleapis.com/v1beta/files/{file_id}"
    for _ in range(120):
        status_request = urllib.request.Request(status_url, headers={"x-goog-api-key": api_key})
        try:
            with urllib.request.urlopen(status_request, timeout=30) as response:
                file_info = json.loads(response.read(64 * 1024).decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read(1000).decode("utf-8", "replace")
            raise VideoGenerationFailed(f"Gemini video file status failed ({exc.code}): {detail[:400]}") from None
        except (urllib.error.URLError, TimeoutError) as exc:
            raise VideoGenerationFailed(f"Gemini video status connection failed: {str(exc)[:250]}") from None
        state = file_info.get("state")
        if state == "ACTIVE":
            break
        if state == "FAILED":
            raise VideoGenerationFailed("Gemini video file processing failed.")
        time.sleep(5)
    else:
        raise VideoGenerationFailed("Gemini video file processing timeout (10 minutes).")

    download_url = f"https://generativelanguage.googleapis.com/v1beta/files/{file_id}:download?alt=media"
    download_request = urllib.request.Request(download_url, headers={"x-goog-api-key": api_key})
    try:
        with urllib.request.urlopen(download_request, timeout=120) as response:
            raw = response.read(MAX_VIDEO_BYTES + 1)
    except urllib.error.HTTPError as exc:
        detail = exc.read(1000).decode("utf-8", "replace")
        raise VideoGenerationFailed(f"Gemini video download failed ({exc.code}): {detail[:400]}") from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise VideoGenerationFailed(f"Gemini video download connection failed: {str(exc)[:250]}") from None
    return _validate_video(raw)


def generate_video(prompt: str, aspect_ratio: str = "9:16", resolution: str = "720p",
                   style: str = "cinematic", reference_image_id: str | None = None) -> dict:
    status = video_status()
    if not status["available"]:
        raise VideoUnavailable("AI video generation disabled hai. Server admin ko paid media enable karke GEMINI_API_KEY secure secret mein set karna hoga.")
    prompt = prompt.strip()
    if not prompt or len(prompt) > 3000:
        raise ValueError("Video prompt 1 se 3000 characters ka hona chahiye.")
    if aspect_ratio not in {"9:16", "16:9"}:
        raise ValueError("Aspect ratio 9:16 ya 16:9 hona chahiye.")
    if resolution not in {"360p", "720p", "1080p", "4k"}:
        raise ValueError("Resolution 360p, 720p, 1080p ya 4k hona chahiye.")
    styles = {
        "cinematic": "Photorealistic cinematic live-action style.",
        "2d-animation": "Polished 2D animated film style, expressive illustrated characters, smooth hand-drawn motion.",
        "3d-animation": "High-quality 3D animated film style, dimensional characters, realistic materials, cinematic lighting.",
        "documentary": "Realistic documentary footage style, natural camera movement and authentic environmental detail.",
        "anime": "High-quality anime animation style, expressive character motion and detailed illustrated backgrounds.",
        "motion-graphics": "Professional animated motion-graphics style, clean shapes, dynamic transitions and readable visual hierarchy; avoid rendering text unless requested.",
    }
    if style not in styles:
        raise ValueError("Unsupported video style.")
    full_prompt = f"{styles[style]} {prompt}. Create one coherent short clip with intentional subject movement, camera movement, lighting and a clear visual composition. Do not add captions, logos or watermarks."
    user_input = [{"type": "text", "text": full_prompt}]
    if reference_image_id:
        if not re.fullmatch(r"[a-f0-9]{32}", reference_image_id):
            raise ValueError("Invalid reference image ID.")
        image_path = IMAGE_DIR / f"{reference_image_id}.jpg"
        if not image_path.is_file():
            raise FileNotFoundError("Reference image not found.")
        image_bytes = image_path.read_bytes()
        if len(image_bytes) > 20 * 1024 * 1024:
            raise ValueError("Reference image 20 MB se chhoti honi chahiye.")
        user_input.insert(0, {
            "type": "image",
            "data": base64.b64encode(image_bytes).decode("ascii"),
            "mime_type": "image/jpeg",
        })
    request_body = json.dumps({
        "model": MODEL,
        "input": user_input if reference_image_id else full_prompt,
        "response_format": {
            "type": "video",
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "delivery": "uri",
        },
    }).encode("utf-8")
    request = urllib.request.Request(
        ENDPOINT,
        data=request_body,
        headers={
            "x-goog-api-key": os.environ["GEMINI_API_KEY"],
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=360) as response:
            raw_response = response.read(MAX_VIDEO_BYTES * 2)
    except urllib.error.HTTPError as exc:
        detail = exc.read(1500).decode("utf-8", "replace")
        raise VideoGenerationFailed(f"Gemini video request failed ({exc.code}): {detail[:600]}") from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise VideoGenerationFailed(f"Gemini video connection failed: {str(exc)[:300]}") from None
    try:
        payload = json.loads(raw_response.decode("utf-8"))
    except Exception:
        raise VideoGenerationFailed("Gemini ne valid JSON response nahi diya.") from None
    if payload.get("status") in {"failed", "cancelled"}:
        raise VideoGenerationFailed("Gemini video generation status: " + str(payload.get("status")))
    video_bytes = _extract_video(payload)
    AI_VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    video_id = uuid.uuid4().hex
    output = AI_VIDEO_DIR / f"{video_id}.mp4"
    output.write_bytes(video_bytes)
    return {
        "video_id": video_id,
        "url": f"/api/ai-videos/{video_id}",
        "filename": output.name,
        "format": "MP4",
        "size_bytes": len(video_bytes),
        "provider": "Google Gemini API",
        "model": MODEL,
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
        "style": style,
        "reference_image_used": bool(reference_image_id),
        "interaction_id": payload.get("id"),
        "notice": "Short AI-generated video clip. 1080p/4K may be upscaled output; check provider terms and pricing before commercial use.",
    }
