from io import BytesIO

from PIL import Image

from app import image_generator


def _offline_status():
    # Deliberately omit comfyui_available: absence must never be interpreted
    # as proof that a ComfyUI server is reachable.
    return {"local_available": True, "model": "unused-paid-model"}


def _forbid_comfyui(*args, **kwargs):
    raise AssertionError("Offline fallback must not call the ComfyUI client")


def test_local_scene_generation_uses_short_video_aspect_ratio(tmp_path, monkeypatch):
    monkeypatch.setattr(image_generator, "IMAGE_DIR", tmp_path)
    monkeypatch.setattr(image_generator, "image_status", _offline_status)
    monkeypatch.setattr(image_generator, "generate_image_bytes", _forbid_comfyui)

    result = image_generator.generate_image(
        "A cinematic mountain scene", "scene", "portrait"
    )

    assert result["width"] == 768
    assert result["height"] == 1360
    assert result["provider"] == "SINTU Procedural Art (offline)"
    assert result["local"] is True
    assert "not a generative-AI image" in result["notice"]
    with Image.open(tmp_path / f"{result['image_id']}.jpg") as generated:
        assert generated.size == (768, 1360)


def test_local_landscape_generation_uses_widescreen_aspect_ratio(tmp_path, monkeypatch):
    monkeypatch.setattr(image_generator, "IMAGE_DIR", tmp_path)
    monkeypatch.setattr(image_generator, "image_status", _offline_status)
    monkeypatch.setattr(image_generator, "generate_image_bytes", _forbid_comfyui)

    result = image_generator.generate_image(
        "A cinematic landscape", "scene", "landscape"
    )

    assert result["width"] == 1360
    assert result["height"] == 768
    assert result["provider"] == "SINTU Procedural Art (offline)"
    assert "not a generative-AI image" in result["notice"]


def test_procedural_image_generation_is_deterministic_and_offline():
    from app.procedural_art import generate_procedural_scene_bytes

    prompt = "A quiet forest at sunrise"
    first = generate_procedural_scene_bytes(prompt, 320, 480)
    second = generate_procedural_scene_bytes(prompt, 320, 480)
    different = generate_procedural_scene_bytes("A busy city at night", 320, 480)

    assert first == second
    assert first != different
    with Image.open(BytesIO(first)) as generated:
        assert generated.size == (320, 480)
        assert generated.format == "PNG"
