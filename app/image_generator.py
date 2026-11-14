"""Local ComfyUI plus offline procedural art, with explicitly gated paid image generation."""
import base64
import os
import uuid
from io import BytesIO
from pathlib import Path
from .policy import paid_upgrades_allowed
from PIL import Image, UnidentifiedImageError
from .comfyui_client import image_workflow_status, generate_image_bytes, ComfyUIUnavailable
from .procedural_art import generate_procedural_scene_bytes

DATA_DIR = Path(os.getenv("SINTU_DATA_DIR", str(Path(__file__).resolve().parent.parent))).expanduser().resolve()
IMAGE_DIR = DATA_DIR / "generated_images"
MAX_IMAGE_BYTES = 15 * 1024 * 1024


class ImageUnavailable(Exception):
    pass


class ImageGenerationFailed(Exception):
    pass


def _save_generated_image(raw: bytes):
    """Validate image bytes before decoding and storing a normalized JPEG."""
    if not isinstance(raw, (bytes, bytearray)) or not raw:
        raise ImageGenerationFailed("Image provider returned no image data.")
    if len(raw) > MAX_IMAGE_BYTES:
        raise ImageGenerationFailed("Generated image exceeded the allowed size.")
    try:
        with Image.open(BytesIO(raw)) as source:
            if source.format not in {"PNG", "JPEG", "WEBP"}:
                raise ImageGenerationFailed("Generated image format is not supported.")
            width, height = source.size
            if (width < 64 or height < 64 or width > 4096 or height > 4096
                    or width * height > 16_777_216):
                raise ImageGenerationFailed("Generated image dimensions are outside the safe limits.")
            source.verify()
        with Image.open(BytesIO(raw)) as source:
            source.load()
            image = source.convert("RGB")
    except ImageGenerationFailed:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ImageGenerationFailed("Image provider returned invalid or unsafe image data.") from None

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    image_id = uuid.uuid4().hex
    output = IMAGE_DIR / f"{image_id}.jpg"
    try:
        image.save(output, format="JPEG", quality=92, optimize=True)
    except OSError:
        output.unlink(missing_ok=True)
        raise ImageGenerationFailed("Generated image could not be stored safely.") from None
    return image_id, image, output


def image_status():
    enabled = os.getenv("ENABLE_PAID_MEDIA_GENERATION", "false").strip().lower() == "true" and paid_upgrades_allowed()
    configured = bool(os.getenv("OPENAI_API_KEY"))
    token_configured = bool(os.getenv("MEDIA_GENERATION_TOKEN"))
    comfy = image_workflow_status()
    local_available = True  # The offline procedural renderer is always available.
    engine = "ComfyUI" if comfy["available"] else "SINTU Procedural Art (offline fallback)"
    return {
        "available": local_available or (enabled and configured and token_configured),
        "local_available": local_available,
        "local_engine": engine,
        "comfyui_available": comfy["available"],
        "procedural_fallback_available": True,
        "local_workflow_configured": comfy["workflow_configured"],
        "local_diagnostics": {key: comfy.get(key) for key in ("server_reachable", "workflow_valid", "nodes_verified", "missing_nodes", "missing_models", "reason")},
        "enabled_by_admin": enabled,
        "provider_configured": configured,
        "access_token_configured": token_configured,
        "provider": "ComfyUI local AI / SINTU Procedural Art offline / optional OpenAI",
        "model": os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1"),
        "formats": ["jpeg"],
        "notice": "Without ComfyUI, SINTU creates original procedural illustrations locally; this fallback is not generative AI. Paid image generation remains locked until revenue and explicit approval.",
    }


def generate_image(prompt: str, kind: str = "scene", aspect: str = "portrait") -> dict:
    status = image_status()
    if kind not in {"scene", "thumbnail"}:
        raise ValueError("Image kind must be scene or thumbnail.")
    if aspect not in {"portrait", "landscape", "square"}:
        raise ValueError("Unsupported image aspect ratio.")
    prompt = prompt.strip()
    if not prompt or len(prompt) > 3000:
        raise ValueError("Image prompt must contain 1 to 3000 characters.")
    size = {"portrait": "1024x1536", "landscape": "1536x1024", "square": "1024x1024"}[aspect]
    clean_prompt = prompt
    if kind == "scene":
        clean_prompt += " Clean text-free video frame: no text, no letters, no words, no subtitles, no captions, no logo, no watermark. The final SINTU AI YOUTUBE STUDIO watermark is added by the renderer."
    if kind == "thumbnail" and aspect != "landscape":
        raise ValueError("YouTube thumbnails must use landscape aspect ratio.")
    width, height = {"portrait": (768, 1360), "landscape": (1360, 768), "square": (1024, 1024)}[aspect]
    if status.get("comfyui_available", status.get("local_available", False)):
        try:
            raw = generate_image_bytes(clean_prompt, width, height)
            provider = "ComfyUI (local AI)"
            notice = "Locally generated AI image. Review model license and likeness rights before publishing."
        except ComfyUIUnavailable as exc:
            raise ImageUnavailable(str(exc)) from None
    elif status["local_available"]:
        try:
            raw = generate_procedural_scene_bytes(clean_prompt, width, height)
            provider = "SINTU Procedural Art (offline)"
            notice = "Original procedural illustration; not a generative-AI image. No network, account, model download or paid API required."
        except (ValueError, OSError) as exc:
            raise ImageGenerationFailed(str(exc)) from None
    else:
        if not status["enabled_by_admin"]:
            raise ImageUnavailable("Free image generation is unavailable and paid generation remains locked.")
        if not status["provider_configured"] or not status["access_token_configured"]:
            raise ImageUnavailable("Optional paid image provider credentials are not configured.")
        try:
            from openai import OpenAI
            client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=120.0, max_retries=1)
            response = client.images.generate(model=status["model"], prompt=clean_prompt,
                size=size, quality="medium", output_format="png")
            encoded = response.data[0].b64_json
            if not encoded:
                raise ImageGenerationFailed("Image provider returned no image data.")
            raw = base64.b64decode(encoded, validate=True)
            provider = status["model"]
            notice = "AI-generated image. Check facts, likeness rights, and platform thumbnail policies before publishing."
        except (ImageUnavailable, ImageGenerationFailed, ValueError):
            raise
        except (UnidentifiedImageError, OSError, base64.binascii.Error):
            raise ImageGenerationFailed("Image provider returned invalid image data.") from None
        except Exception as exc:
            raise ImageGenerationFailed(f"Image generation failed ({type(exc).__name__}). Check API quota and model access.") from None

    image_id, image, output = _save_generated_image(raw)
    return {"image_id": image_id, "url": f"/api/images/{image_id}", "kind": kind,
            "aspect": aspect, "width": image.width, "height": image.height,
            "format": "JPEG", "size_bytes": output.stat().st_size,
            "provider": provider, "local": provider != status.get("model"), "notice": notice}
