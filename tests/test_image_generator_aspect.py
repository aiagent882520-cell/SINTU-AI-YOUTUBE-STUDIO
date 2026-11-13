from app import image_generator


def test_local_scene_generation_uses_short_video_aspect_ratio(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(image_generator, "IMAGE_DIR", tmp_path)
    monkeypatch.setattr(image_generator, "image_status", lambda: {"local_available": True})
    def fake_generate(prompt, width, height):
        captured.update(width=width, height=height)
        from PIL import Image
        import io
        output = io.BytesIO()
        Image.new("RGB", (width, height), "navy").save(output, format="PNG")
        return output.getvalue()
    monkeypatch.setattr(image_generator, "generate_image_bytes", fake_generate)
    result = image_generator.generate_image("A cinematic mountain scene", "scene", "portrait")
    assert captured == {"width": 768, "height": 1360}
    assert result["width"] == 768
    assert result["height"] == 1360


def test_local_landscape_generation_uses_widescreen_aspect_ratio(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(image_generator, "IMAGE_DIR", tmp_path)
    monkeypatch.setattr(image_generator, "image_status", lambda: {"local_available": True})
    def fake_generate(prompt, width, height):
        captured.update(width=width, height=height)
        from PIL import Image
        import io
        output = io.BytesIO()
        Image.new("RGB", (width, height), "navy").save(output, format="PNG")
        return output.getvalue()
    monkeypatch.setattr(image_generator, "generate_image_bytes", fake_generate)
    result = image_generator.generate_image("A cinematic landscape", "scene", "landscape")
    assert captured == {"width": 1360, "height": 768}
    assert result["width"] == 1360
    assert result["height"] == 768
