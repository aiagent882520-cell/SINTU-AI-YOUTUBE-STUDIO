"""Local-only ComfyUI API workflow runner for free image generation."""
import json
import os
import secrets
import time
import urllib.parse
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

class ComfyUIUnavailable(Exception):
    pass

def _base_url():
    url = os.getenv("COMFYUI_BASE_URL", "http://127.0.0.1:8188").rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1", "host.docker.internal"}:
        raise ComfyUIUnavailable("ComfyUI must use localhost or the Docker host bridge.")
    return url

def image_workflow_status():
    path = Path(os.getenv("COMFYUI_IMAGE_WORKFLOW_PATH", "")).expanduser()
    try:
        base = _base_url()
    except ComfyUIUnavailable:
        return {"available": False, "reason": "ComfyUI URL must be localhost."}
    return {"available": bool(str(path) and path.is_file()), "base_url": base,
            "workflow_configured": bool(str(path) and path.is_file()),
            "workflow_path": str(path) if path.is_file() else None}

def _replace_placeholders(value, prompt, negative, width, height, seed):
    if isinstance(value, dict):
        return {key: _replace_placeholders(item, prompt, negative, width, height, seed) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_placeholders(item, prompt, negative, width, height, seed) for item in value]
    if value == "__SINTU_PROMPT__":
        return prompt
    if value == "__SINTU_NEGATIVE__":
        return negative
    if value == "__SINTU_WIDTH__":
        return width
    if value == "__SINTU_HEIGHT__":
        return height
    if value == "__SINTU_SEED__":
        return seed
    return value

def _request(url, data=None, timeout=30):
    request = urllib.request.Request(url, data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()

def generate_image_bytes(prompt, width, height, timeout_seconds=240):
    status = image_workflow_status()
    if not status["available"]:
        raise ComfyUIUnavailable("Free ComfyUI image workflow is not configured. Set COMFYUI_IMAGE_WORKFLOW_PATH to an API-format workflow JSON.")
    workflow_path = Path(os.environ["COMFYUI_IMAGE_WORKFLOW_PATH"]).expanduser()
    try:
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ComfyUIUnavailable("ComfyUI workflow JSON could not be read.") from None
    if not isinstance(workflow, dict) or not workflow:
        raise ComfyUIUnavailable("ComfyUI workflow must be a non-empty API-format node dictionary.")
    workflow = _replace_placeholders(workflow, prompt,
        "text, watermark, low quality, distorted, malformed, extra limbs",
        width, height, secrets.randbelow(2**31 - 1))
    base = status["base_url"]
    try:
        submitted = json.loads(_request(base + "/prompt", json.dumps({"prompt": workflow, "client_id": secrets.token_hex(12)}).encode(), 30))
        prompt_id = submitted.get("prompt_id")
        if not prompt_id:
            raise ComfyUIUnavailable("ComfyUI did not return a prompt_id. Check workflow node connections.")
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            time.sleep(1)
            history = json.loads(_request(base + "/history/" + urllib.parse.quote(prompt_id), timeout=20))
            item = history.get(prompt_id, {})
            outputs = item.get("outputs", {})
            for node in outputs.values():
                images = node.get("images", []) if isinstance(node, dict) else []
                if images:
                    image_info = images[0]
                    query = urllib.parse.urlencode({
                        "filename": image_info.get("filename", ""),
                        "subfolder": image_info.get("subfolder", ""),
                        "type": image_info.get("type", "output")
                    })
                    return _request(base + "/view?" + query, timeout=30)
        raise ComfyUIUnavailable("ComfyUI image generation timed out.")
    except ComfyUIUnavailable:
        raise
    except Exception as exc:
        raise ComfyUIUnavailable("ComfyUI local request failed (" + type(exc).__name__ + ").") from None


def video_workflow_status():
    path = Path(os.getenv("COMFYUI_VIDEO_WORKFLOW_PATH", "")).expanduser()
    try:
        base = _base_url()
    except ComfyUIUnavailable:
        return {"available": False, "reason": "ComfyUI URL must be localhost."}
    return {"available": bool(path.is_file()), "base_url": base,
            "workflow_configured": bool(path.is_file()),
            "workflow_path": str(path) if path.is_file() else None}

def generate_video_bytes(prompt, width, height, frames, fps=24, timeout_seconds=600):
    status = video_workflow_status()
    if not status["available"]:
        raise ComfyUIUnavailable("Free ComfyUI video workflow is not configured. Set COMFYUI_VIDEO_WORKFLOW_PATH to an API-format workflow JSON.")
    workflow_path = Path(os.environ["COMFYUI_VIDEO_WORKFLOW_PATH"]).expanduser()
    try:
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ComfyUIUnavailable("ComfyUI video workflow JSON could not be read.") from None
    if not isinstance(workflow, dict) or not workflow:
        raise ComfyUIUnavailable("ComfyUI video workflow must be a non-empty API-format node dictionary.")
    workflow = _replace_placeholders(workflow, prompt,
        "text, watermark, low quality, distorted, malformed",
        width, height, secrets.randbelow(2**31 - 1))
    def replace_video_fields(value):
        if isinstance(value, dict):
            return {key: replace_video_fields(item) for key, item in value.items()}
        if isinstance(value, list):
            return [replace_video_fields(item) for item in value]
        if value == "__SINTU_FRAMES__":
            return frames
        if value == "__SINTU_FPS__":
            return fps
        return value
    workflow = replace_video_fields(workflow)
    base = status["base_url"]
    try:
        submitted = json.loads(_request(base + "/prompt", json.dumps({"prompt": workflow, "client_id": secrets.token_hex(12)}).encode(), 30))
        prompt_id = submitted.get("prompt_id")
        if not prompt_id:
            raise ComfyUIUnavailable("ComfyUI did not return a prompt_id.")
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            time.sleep(2)
            history = json.loads(_request(base + "/history/" + urllib.parse.quote(prompt_id), timeout=20))
            outputs = history.get(prompt_id, {}).get("outputs", {})
            for node in outputs.values():
                if not isinstance(node, dict):
                    continue
                candidates = node.get("videos", []) + node.get("gifs", [])
                for item in candidates:
                    filename = str(item.get("filename", ""))
                    if not filename.lower().endswith((".mp4", ".webm", ".gif")):
                        continue
                    query = urllib.parse.urlencode({"filename": filename,
                        "subfolder": item.get("subfolder", ""), "type": item.get("type", "output")})
                    return _request(base + "/view?" + query, timeout=90)
        raise ComfyUIUnavailable("ComfyUI video generation timed out.")
    except ComfyUIUnavailable:
        raise
    except Exception as exc:
        raise ComfyUIUnavailable("ComfyUI local video request failed (" + type(exc).__name__ + ").") from None
