import pytest
from PIL import Image

from app.video_renderer import _validate_scene_image


def test_scene_image_validation_accepts_supported_image(tmp_path):
    path = tmp_path / "scene.png"
    Image.new("RGB", (64, 64)).save(path)
    _validate_scene_image(path)


def test_scene_image_validation_rejects_small_dimensions(tmp_path):
    path = tmp_path / "tiny.png"
    Image.new("RGB", (32, 32)).save(path)
    with pytest.raises(ValueError, match="dimensions"):
        _validate_scene_image(path)


def test_scene_image_validation_rejects_unsupported_format(tmp_path):
    path = tmp_path / "scene.bmp"
    Image.new("RGB", (64, 64)).save(path)
    with pytest.raises(ValueError, match="PNG, JPEG"):
        _validate_scene_image(path)


def test_scene_image_validation_rejects_corrupt_image(tmp_path):
    path = tmp_path / "scene.png"
    path.write_bytes(b"not an image")
    with pytest.raises(ValueError, match="valid image"):
        _validate_scene_image(path)


def test_scene_image_validation_rejects_oversized_file(tmp_path, monkeypatch):
    path = tmp_path / "large.png"
    path.write_bytes(b"x")
    monkeypatch.setattr("app.video_renderer.MAX_SCENE_IMAGE_BYTES", 0)
    with pytest.raises(ValueError, match="15 MB"):
        _validate_scene_image(path)
