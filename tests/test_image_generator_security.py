import io

import pytest
from PIL import Image

from app import image_generator


def png_bytes(size=(128, 128)):
    buffer = io.BytesIO()
    Image.new("RGB", size, "navy").save(buffer, format="PNG")
    return buffer.getvalue()


def test_save_generated_image_normalizes_valid_png(tmp_path, monkeypatch):
    monkeypatch.setattr(image_generator, "IMAGE_DIR", tmp_path)
    image_id, image, output = image_generator._save_generated_image(png_bytes())
    assert len(image_id) == 32
    assert image.size == (128, 128)
    assert output.is_file()
    with Image.open(output) as saved:
        assert saved.format == "JPEG"
        assert saved.size == (128, 128)


def test_save_generated_image_rejects_oversized_payload():
    with pytest.raises(image_generator.ImageGenerationFailed, match="allowed size"):
        image_generator._save_generated_image(b"x" * (image_generator.MAX_IMAGE_BYTES + 1))


def test_save_generated_image_rejects_invalid_payload():
    with pytest.raises(image_generator.ImageGenerationFailed, match="invalid or unsafe"):
        image_generator._save_generated_image(b"not an image")


@pytest.mark.parametrize("size", [(32, 32), (4097, 128), (4096, 4097)])
def test_save_generated_image_rejects_unsafe_dimensions(size):
    with pytest.raises(image_generator.ImageGenerationFailed, match="dimensions"):
        image_generator._save_generated_image(png_bytes(size))
