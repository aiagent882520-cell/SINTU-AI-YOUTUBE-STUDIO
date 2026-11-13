from io import BytesIO
from PIL import Image

from app import image_generator, procedural_art


def test_procedural_scene_is_valid_png_with_requested_dimensions():
    raw = procedural_art.generate_procedural_scene_bytes("mysterious ancient fort at night", 320, 512)
    with Image.open(BytesIO(raw)) as image:
        assert image.format == "PNG"
        assert image.size == (320, 512)


def test_procedural_scene_is_deterministic_for_same_prompt():
    first = procedural_art.generate_procedural_scene_bytes("dark forest mystery", 256, 384)
    second = procedural_art.generate_procedural_scene_bytes("dark forest mystery", 256, 384)
    assert first == second


def test_procedural_scene_rejects_bad_input():
    for prompt, width, height in (("", 512, 512), ("x" * 3001, 512, 512), ("valid", 128, 512)):
        try:
            procedural_art.generate_procedural_scene_bytes(prompt, width, height)
            assert False, "Expected ValueError"
        except ValueError:
            pass


def test_image_generator_uses_offline_fallback_when_comfyui_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(image_generator, "IMAGE_DIR", tmp_path)
    monkeypatch.setattr(image_generator, "image_workflow_status", lambda: {
        "available": False, "workflow_configured": False, "server_reachable": False,
        "workflow_valid": False, "nodes_verified": False, "missing_nodes": [],
        "missing_models": [], "reason": "ComfyUI offline",
    })
    result = image_generator.generate_image("mysterious ancient temple", "scene", "portrait")
    assert result["provider"] == "SINTU Procedural Art (offline)"
    assert result["local"] is True
    assert result["width"] == 768
    assert result["height"] == 1360
    assert result["size_bytes"] > 0
    assert (tmp_path / (result["image_id"] + ".jpg")).is_file()


def test_image_status_exposes_fallback_without_claiming_comfyui(monkeypatch):
    monkeypatch.setattr(image_generator, "image_workflow_status", lambda: {
        "available": False, "workflow_configured": False, "server_reachable": False,
        "workflow_valid": False, "nodes_verified": False, "missing_nodes": [],
        "missing_models": [], "reason": "ComfyUI offline",
    })
    status = image_generator.image_status()
    assert status["local_available"] is True
    assert status["procedural_fallback_available"] is True
    assert status["comfyui_available"] is False
    assert "not generative AI" in status["notice"]
