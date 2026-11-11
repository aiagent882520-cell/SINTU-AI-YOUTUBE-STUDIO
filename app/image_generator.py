"""Gated OpenAI image generation for scene artwork and thumbnails."""
import base64
import os
import uuid
from io import BytesIO
from pathlib import Path
from .policy import paid_upgrades_allowed

from PIL import Image, UnidentifiedImageError
from .comfyui_client import image_workflow_status, generate_image_bytes, ComfyUIUnavailable

DATA_DIR = Path(os.getenv("SINTU_DATA_DIR", str(Path(__file__).resolve().parent.parent))).expanduser().resolve()
IMAGE_DIR = DATA_DIR / "generated_images"
MAX_IMAGE_BYTES = 15 * 1024 * 1024


class ImageUnavailable(Exception):
    pass


class ImageGenerationFailed(Exception):
    pass


def image_status():
    enabled = os.getenv("ENABLE_PAID_MEDIA_GENERATION", "false").strip().lower() == "true" and paid_upgrades_allowed()
    configured = bool(os.getenv("OPENAI_API_KEY"))
    token_configured = bool(os.getenv("MEDIA_GENERATION_TOKEN"))
    local = image_workflow_status()
    return {
        "available": local["available"] or (enabled and configured and token_configured),
        "local_available": local["available"],
        "local_engine": "ComfyUI" if local["available"] else None,
        "local_workflow_configured": local["workflow_configured"],
        "enabled_by_admin": enabled,
        "provider_configured": configured,
        "access_token_configured": token_configured,
        "provider": "OpenAI",
        "model": os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1"),
        "formats": ["png"],
        "notice": "Paid image generation remains locked until revenue is confirmed and the user explicitly approves upgrades.",
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
    if kind == "thumbnail" and aspect != "landscape":
        raise ValueError("YouTube thumbnails must use landscape aspect ratio.")
    if status["local_available"]:
        width, height = {"portrait": (768, 1152), "landscape": (1152, 768), "square": (1024, 1024)}[aspect]
        try:
            raw = generate_image_bytes(prompt, width, height)
            with Image.open(BytesIO(raw)) as source:
                source.verify()
            with Image.open(BytesIO(raw)) as source:
                source.load(); image = source.convert("RGB")
                IMAGE_DIR.mkdir(parents=True, exist_ok=True)
                image_id = uuid.uuid4().hex; output = IMAGE_DIR / f"{image_id}.jpg"
                image.save(output, format="JPEG", quality=92, optimize=True)
            return {"image_id": image_id, "url": f"/api/images/{image_id}", "kind": kind,
                    "aspect": aspect, "width": image.width, "height": image.height, "format": "JPEG",
                    "size_bytes": output.stat().st_size, "provider": "ComfyUI (local)", "local": True,
                    "notice": "Locally generated image. Review model license and likeness rights before publishing."}
        except ComfyUIUnavailable as exc:
            raise ImageUnavailable(str(exc)) from None
        except (UnidentifiedImageError, OSError):
            raise ImageGenerationFailed("ComfyUI returned invalid image data.") from None
    if not status["enabled_by_admin"]:
        raise ImageUnavailable("Free image generation needs a local ComfyUI API workflow. Paid generation remains locked until revenue and approval.")
    if not status["provider_configured"] or not status["access_token_configured"]:
        raise ImageUnavailable("Optional paid image provider credentials are not configured.")
    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=120.0, max_retries=1)
        response = client.images.generate(
            model=status["model"],
            prompt=prompt,
            size=size,
            quality="medium",
            output_format="png",
        )
        encoded = response.data[0].b64_json
        if not encoded:
            raise ImageGenerationFailed("Image provider returned no image data.")
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > MAX_IMAGE_BYTES:
            raise ImageGenerationFailed("Generated image exceeded the allowed size.")
        with Image.open(BytesIO(raw)) as source:
            source.verify()
        with Image.open(BytesIO(raw)) as source:
            source.load()
            image = source.convert("RGB")
            IMAGE_DIR.mkdir(parents=True, exist_ok=True)
            image_id = uuid.uuid4().hex
            output = IMAGE_DIR / f"{image_id}.jpg"
            image.save(output, format="JPEG", quality=92, optimize=True)
        return {
            "image_id": image_id,
            "url": f"/api/images/{image_id}",
            "kind": kind,
            "aspect": aspect,
            "width": image.width,
            "height": image.height,
            "format": "JPEG",
            "size_bytes": output.stat().st_size,
            "model": status["model"],
            "notice": "AI-generated image. Check facts, likeness rights, and platform thumbnail policies before publishing.",
        }
    except (ImageUnavailable, ImageGenerationFailed, ValueError):
        raise
    except (UnidentifiedImageError, OSError, base64.binascii.Error):
        raise ImageGenerationFailed("Image provider returned invalid image data.") from None
    except Exception as exc:
        raise ImageGenerationFailed(f"Image generation failed ({type(exc).__name__}). Check API quota and model access.") from None
