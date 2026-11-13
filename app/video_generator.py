"""Optional Gemini Omni Flash text/image-to-video generation."""
from pathlib import Path
import base64
import json
import os
import re
import math
import subprocess
import tempfile
import urllib.error
import urllib.request
import uuid
import time

from .image_generator import IMAGE_DIR
from .comfyui_client import video_workflow_status, generate_video_bytes, ComfyUIUnavailable
from .policy import paid_upgrades_allowed

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("SINTU_DATA_DIR", str(ROOT))).expanduser().resolve()
AI_VIDEO_DIR = DATA_DIR / "generated_ai_videos"
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"
MODEL = "gemini-omni-1.1-flash"
MAX_VIDEO_BYTES = 100 * 1024 * 1024


class VideoUnavailable(Exception):
    pass


class VideoGenerationFailed(Exception):
    pass


def video_status():
    enabled = os.getenv("ENABLE_PAID_MEDIA_GENERATION", "").lower() == "true" and paid_upgrades_allowed()
    key_set = bool(os.getenv("GEMINI_API_KEY"))
    local = video_workflow_status()
    return {
        "available": local["available"] or (enabled and key_set),
        "local_available": local["available"],
        "local_engine": "ComfyUI" if local["available"] else None,
        "local_workflow_configured": local["workflow_configured"],
        "local_diagnostics": {key: local.get(key) for key in ("server_reachable", "workflow_valid", "nodes_verified", "missing_nodes", "missing_models", "reason")},
        "paid_available": enabled and key_set,
        "provider": "Google Gemini API",
        "model": MODEL,
        "enabled": enabled,
        "api_key_configured": key_set,
        "modes": ["text-to-video", "image-to-video"],
        "aspect_ratios": ["9:16", "16:9"],
        "resolutions": ["360p", "720p", "1080p", "4k"],
        "max_clip_seconds": 10,
        "note": "Paid video generation remains locked until revenue is confirmed and the user explicitly approves upgrades.",
    }


def _store_video_atomically(video_bytes: bytes) -> tuple[str, Path]:
    """Persist a validated MP4 without exposing a partially-written output."""
    AI_VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    video_id = uuid.uuid4().hex
    output = AI_VIDEO_DIR / f"{video_id}.mp4"
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".sintu-video-", suffix=".tmp",
            dir=AI_VIDEO_DIR, delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(video_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    except OSError:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise VideoGenerationFailed("Generated video disk par safely save nahi ho saka.") from None
    return video_id, output


def _validate_video(raw: bytes) -> bytes:
    """Reject corrupt, empty, audio-only or implausibly large MP4s before storing them."""
    if len(raw) < 16 or len(raw) > MAX_VIDEO_BYTES or raw[4:8] != b"ftyp":
        raise VideoGenerationFailed("Generated video invalid hai ya 100 MB size limit se badi hai.")
    try:
        # Use a temporary seekable file: ordinary MP4 metadata (moov atom) may
        # live at the end, which cannot be reliably inspected from a non-seekable pipe.
        with tempfile.TemporaryDirectory(prefix="sintu-video-check-") as temp_dir:
            candidate = Path(temp_dir) / "candidate.mp4"
            candidate.write_bytes(raw)
            probe = subprocess.run(
                [
                    "ffprobe", "-v", "error", "-select_streams", "v:0",
                    "-show_entries", "stream=codec_type,codec_name,width,height:format=format_name,duration",
                    "-of", "json", str(candidate),
                ],
                capture_output=True, check=False, timeout=30,
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VideoGenerationFailed(
            "Video verification ke liye FFprobe available nahi hai ya timeout hua. FFmpeg/FFprobe install karein."
        ) from None
    if probe.returncode != 0:
        raise VideoGenerationFailed("Generated MP4 corrupt hai: FFprobe decode/inspect nahi kar saka.")
    try:
        metadata = json.loads(probe.stdout.decode("utf-8"))
        streams = metadata.get("streams", [])
        fmt = metadata.get("format", {})
        video = next((item for item in streams if item.get("codec_type") == "video"), None)
        duration = float(fmt.get("duration", 0))
        width, height = int(video.get("width", 0)), int(video.get("height", 0))
        format_names = str(fmt.get("format_name", "")).lower().split(",")
    except (AttributeError, TypeError, ValueError, StopIteration, json.JSONDecodeError):
        raise VideoGenerationFailed("Generated MP4 mein valid video stream metadata nahi mila.") from None
    if not any(name in {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"} for name in format_names):
        raise VideoGenerationFailed("Generated file MP4-compatible container nahi hai.")
    if not video or not video.get("codec_name") or width < 16 or height < 16 or width > 7680 or height > 4320:
        raise VideoGenerationFailed("Generated MP4 mein valid supported-size video stream nahi hai.")
    if not math.isfinite(duration) or duration <= 0 or duration > 600:
        raise VideoGenerationFailed("Generated MP4 ki duration invalid hai.")
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
    deadline = time.monotonic() + 600
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise VideoGenerationFailed("Gemini video file processing timeout (10 minutes).")
        status_request = urllib.request.Request(status_url, headers={"x-goog-api-key": api_key})
        try:
            with urllib.request.urlopen(status_request, timeout=min(30, remaining)) as response:
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
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(5, remaining))

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
                   style: str = "cinematic", reference_image_id: str | None = None, duration_seconds: int = 8) -> dict:
    status = video_status()
    prompt = prompt.strip()
    if not prompt or len(prompt) > 3000:
        raise ValueError("Video prompt 1 se 3000 characters ka hona chahiye.")
    if aspect_ratio not in {"9:16", "16:9"}:
        raise ValueError("Aspect ratio 9:16 ya 16:9 hona chahiye.")
    if resolution not in {"360p", "720p", "1080p", "4k"}:
        raise ValueError("Resolution 360p, 720p, 1080p ya 4k hona chahiye.")
    if not isinstance(duration_seconds, int) or isinstance(duration_seconds, bool) or not 3 <= duration_seconds <= 10:
        raise ValueError("Clip duration 3 se 10 seconds ke beech honi chahiye.")
    styles = {
        "cinematic": "Photorealistic cinematic live-action style.",
        "2d-animation": "Polished 2D animated film style, expressive illustrated characters, smooth hand-drawn motion.",
        "3d-animation": "High-quality 3D animated film style, dimensional characters, realistic materials, cinematic lighting.",
        "documentary": "Realistic documentary footage style, natural camera movement and authentic environmental detail.",
        "anime": "High-quality anime animation style, expressive character motion and detailed illustrated backgrounds.",
        "motion-graphics": "Professional animated motion-graphics style, clean geometric shapes, dynamic transitions and clear visual hierarchy without typography or words.",
    }
    if style not in styles:
        raise ValueError("Unsupported video style.")
    full_prompt = f"{styles[style]} {prompt}. Target duration: approximately {duration_seconds} seconds. Create one coherent short clip with intentional subject movement, camera movement, lighting and a clear visual composition. No visible text: no text, no letters, no words, no subtitles, no captions, no logos, no watermarks. The final SINTU AI YOUTUBE STUDIO logo is added later by the renderer."
    if status["local_available"]:
        if reference_image_id:
            raise VideoUnavailable("Current free ComfyUI workflow supports text-to-video. Remove the reference image or configure an image-to-video workflow connector later.")
        short_side = {"360p": 360, "720p": 720, "1080p": 1080, "4k": 2160}[resolution]
        width, height = (short_side, round(short_side * 16 / 9)) if aspect_ratio == "9:16" else (round(short_side * 16 / 9), short_side)
        try:
            video_bytes = _validate_video(generate_video_bytes(full_prompt, width, height, duration_seconds * 24, 24))
        except ComfyUIUnavailable as exc:
            raise VideoUnavailable(str(exc)) from None
        video_id, output = _store_video_atomically(video_bytes)
        return {"video_id": video_id, "url": f"/api/ai-videos/{video_id}", "filename": output.name,
                "format": "MP4", "size_bytes": output.stat().st_size, "duration_seconds": duration_seconds,
                "aspect_ratio": aspect_ratio, "resolution": resolution, "style": style,
                "provider": "ComfyUI (local)", "model": "Configured ComfyUI workflow", "requested_duration_seconds": duration_seconds, "local": True,
                "notice": "Generated locally by your configured ComfyUI video workflow. Review quality and model license."}
    if not status["paid_available"]:
        raise VideoUnavailable("Free video generation needs a local ComfyUI video workflow. Paid generation remains locked until revenue and approval.")
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
    task = "image_to_video" if reference_image_id else "text_to_video"
    request_body = json.dumps({
        "model": MODEL,
        "input": user_input if reference_image_id else full_prompt,
        "generation_config": {"video_config": {"task": task}},
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
    try:
        video_bytes = _extract_video(payload)
    except VideoGenerationFailed:
        file_id = _extract_video_file_id(payload)
        if not file_id:
            raise
        video_bytes = _download_video_file(file_id, os.environ["GEMINI_API_KEY"])
    video_id, output = _store_video_atomically(video_bytes)
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
        "requested_duration_seconds": duration_seconds,
        "style": style,
        "task": task,
        "reference_image_used": bool(reference_image_id),
        "interaction_id": payload.get("id"),
        "notice": "Short AI-generated video clip. 1080p/4K may be upscaled output; check provider terms and pricing before commercial use.",
    }
