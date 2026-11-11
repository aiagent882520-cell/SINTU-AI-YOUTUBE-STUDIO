from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]


def test_sintu_brand_assets_are_installed_in_app():
    logo = ROOT / "app" / "static" / "brand-logo.svg"
    icon = ROOT / "app" / "static" / "icon.svg"
    dashboard = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
    login = (ROOT / "app" / "static" / "login.html").read_text(encoding="utf-8")

    assert logo.is_file()
    assert icon.is_file()
    assert "SINTU AI YOUTUBE STUDIO" in logo.read_text(encoding="utf-8")
    assert "SINTU AI YOUTUBE STUDIO" in dashboard
    assert "/static/brand-logo.svg" in dashboard
    assert "/static/brand-logo.svg" in login


def test_video_watermark_uses_sintu_play_mark_and_wordmark():
    from app.video_renderer import _make_watermark_image

    watermark = _make_watermark_image(width=320, height=76)
    assert watermark.mode == "RGBA"
    assert watermark.size == (320, 76)
    pixels = watermark.load()
    # Red play tile and blue/cyan brand outline must both be present.
    red_pixels = blue_pixels = 0
    for y in range(watermark.height):
        for x in range(watermark.width):
            r, g, b, a = pixels[x, y]
            if a > 180 and r > 150 and g < 100 and b < 120:
                red_pixels += 1
            if a > 180 and b > 150 and (g > 100 or r < 100):
                blue_pixels += 1
    assert red_pixels > 20
    assert blue_pixels > 20
