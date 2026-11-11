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

def _load_api_workflow(env_name, required_placeholders=None):
    configured = os.getenv(env_name, "").strip()
    if not configured:
        return None, False, "API workflow file path is not configured."
    path = Path(configured).expanduser()
    if not path.is_file():
        return None, False, "Configured API workflow file was not found."
    try:
        workflow = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, False, "API workflow JSON could not be read."
    if not isinstance(workflow, dict) or not workflow:
        return None, False, "API workflow must be a non-empty ComfyUI API node dictionary."
    for node_id, node in workflow.items():
        if not isinstance(node, dict) or not isinstance(node.get("class_type"), str) or not isinstance(node.get("inputs"), dict):
            return None, False, "API workflow node " + str(node_id) + " must contain class_type and inputs."
    required = required_placeholders or ("__SINTU_PROMPT__",)
    serialized = json.dumps(workflow)
    missing = [placeholder for placeholder in required if placeholder not in serialized]
    if missing:
        return None, False, "API workflow is missing required placeholders: " + ", ".join(missing)
    return workflow, True, None



def _missing_model_files(workflow, object_info):
    """Check configured model-name inputs against ComfyUI's advertised choices."""
    model_input_tokens = ("model", "checkpoint", "ckpt", "vae", "lora", "control_net", "upscale")
    missing = []
    for node_id, node in workflow.items():
        node_type = node.get("class_type")
        info = object_info.get(node_type, {})
        input_info = info.get("input", {}) if isinstance(info, dict) else {}
        for section in ("required", "optional"):
            definitions = input_info.get(section, {}) if isinstance(input_info, dict) else {}
            for input_name, value in node.get("inputs", {}).items():
                if not any(token in input_name.lower() for token in model_input_tokens):
                    continue
                definition = definitions.get(input_name) if isinstance(definitions, dict) else None
                if not isinstance(definition, list) or len(definition) < 2 or not isinstance(definition[1], dict):
                    continue
                choices = definition[1].get("options")
                if isinstance(choices, list) and isinstance(value, str) and not value.startswith("__SINTU_") and value not in choices:
                    missing.append({"node_id": str(node_id), "node_type": node_type,
                                    "input": input_name, "configured": value})
    return missing


def _engine_status(env_name):
    required = ("__SINTU_PROMPT__", "__SINTU_WIDTH__", "__SINTU_HEIGHT__")
    if env_name == "COMFYUI_VIDEO_WORKFLOW_PATH":
        required += ("__SINTU_FRAMES__", "__SINTU_FPS__")
    workflow, configured, reason = _load_api_workflow(env_name, required)
    try:
        base = _base_url()
    except ComfyUIUnavailable:
        return {"available": False, "server_reachable": False, "workflow_configured": configured,
                "workflow_valid": configured, "nodes_verified": False, "missing_nodes": [],
                "workflow_node_types": [], "reason": "ComfyUI URL must use localhost or the Docker host bridge."}
    if not configured:
        return {"available": False, "server_reachable": False, "workflow_configured": False,
                "workflow_valid": False, "nodes_verified": False, "missing_nodes": [],
                "workflow_node_types": [], "base_url": base, "reason": reason}
    try:
        response = json.loads(_request(base + "/system_stats", timeout=2))
        reachable = isinstance(response, dict)
    except Exception:
        reachable = False
    node_types = sorted({node["class_type"] for node in workflow.values()})
    nodes_verified = False
    missing_nodes = []
    missing_models = []
    if reachable:
        try:
            object_info = json.loads(_request(base + "/object_info", timeout=10))
            if isinstance(object_info, dict):
                nodes_verified = True
                missing_nodes = [node_type for node_type in node_types if node_type not in object_info]
                if not missing_nodes:
                    missing_models = _missing_model_files(workflow, object_info)
        except Exception:
            nodes_verified = False
    if not reachable:
        reason = "ComfyUI server did not respond at the configured local URL."
    elif not nodes_verified:
        reason = "ComfyUI is online, but its installed node types could not be verified."
    elif missing_nodes:
        reason = "ComfyUI is missing required workflow nodes: " + ", ".join(missing_nodes)
    elif missing_models:
        reason = "ComfyUI does not list configured model files: " + ", ".join(item["configured"] for item in missing_models)
    else:
        reason = None
    available = bool(configured and reachable and nodes_verified and not missing_nodes and not missing_models)
    return {"available": available, "server_reachable": reachable,
            "workflow_configured": configured, "workflow_valid": configured,
            "nodes_verified": nodes_verified, "missing_nodes": missing_nodes,
            "missing_models": missing_models,
            "workflow_node_types": node_types, "base_url": base, "reason": reason}

def image_workflow_status():
    return _engine_status("COMFYUI_IMAGE_WORKFLOW_PATH")


def video_workflow_status():
    return _engine_status("COMFYUI_VIDEO_WORKFLOW_PATH")

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
    workflow, valid, reason = _load_api_workflow("COMFYUI_IMAGE_WORKFLOW_PATH")
    if not valid:
        raise ComfyUIUnavailable(reason or "ComfyUI image workflow is invalid.")
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




def _video_output_items(history_entry):
    """Return supported video files from ComfyUI history output nodes."""
    outputs = history_entry.get("outputs", {}) if isinstance(history_entry, dict) else {}
    found = []
    if not isinstance(outputs, dict):
        return found
    for node in outputs.values():
        if not isinstance(node, dict):
            continue
        for field in ("videos", "gifs"):
            items = node.get(field, [])
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                filename = item.get("filename")
                if isinstance(filename, str) and filename.lower().endswith((".mp4", ".webm", ".gif")):
                    found.append(item)
    return found


def _video_history_error(history_entry):
    """Extract a concise execution failure from ComfyUI history/status."""
    if not isinstance(history_entry, dict):
        return None
    status = history_entry.get("status", {})
    if not isinstance(status, dict):
        return None
    messages = status.get("messages", [])
    for message in messages if isinstance(messages, list) else []:
        if not isinstance(message, (list, tuple)) or len(message) < 2:
            continue
        detail = message[1]
        if isinstance(detail, dict) and detail.get("exception_message"):
            return str(detail["exception_message"])[:300]
    return None


def generate_video_bytes(prompt, width, height, frames, fps=24, timeout_seconds=600):
    status = video_workflow_status()
    if not status["available"]:
        raise ComfyUIUnavailable("Free ComfyUI video workflow is not configured. Set COMFYUI_VIDEO_WORKFLOW_PATH to an API-format workflow JSON.")
    workflow, valid, reason = _load_api_workflow("COMFYUI_VIDEO_WORKFLOW_PATH", ("__SINTU_PROMPT__", "__SINTU_WIDTH__", "__SINTU_HEIGHT__", "__SINTU_FRAMES__", "__SINTU_FPS__"))
    if not valid:
        raise ComfyUIUnavailable(reason or "ComfyUI video workflow is invalid.")
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
            history_item = history.get(prompt_id, {})
            failure = _video_history_error(history_item)
            if failure:
                raise ComfyUIUnavailable("ComfyUI video workflow execution failed: " + failure)
            candidates = _video_output_items(history_item)
            # The studio currently stores and serves generated clips as MP4.
            mp4_items = [item for item in candidates if item["filename"].lower().endswith(".mp4")]
            if mp4_items:
                item = mp4_items[0]
                query = urllib.parse.urlencode({"filename": item["filename"],
                    "subfolder": item.get("subfolder", ""), "type": item.get("type", "output")})
                return _request(base + "/view?" + query, timeout=90)
        raise ComfyUIUnavailable("ComfyUI video generation timed out.")
    except ComfyUIUnavailable:
        raise
    except Exception as exc:
        raise ComfyUIUnavailable("ComfyUI local video request failed (" + type(exc).__name__ + ").") from None
