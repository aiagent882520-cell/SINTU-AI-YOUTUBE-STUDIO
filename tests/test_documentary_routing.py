import pytest
from pathlib import Path

from app.documentary_routing import uses_procedural_2d


@pytest.mark.parametrize("format_id", [
    "2d-cartoon", "story-animation", "documentary", "nature-documentary",
    "investigative-documentary", "science-documentary", "biography",
    "mystery-documentary", "travel-documentary", "crime-documentary",
])
def test_documentary_and_animation_formats_use_local_procedural_2d(format_id):
    assert uses_procedural_2d(format_id) is True


@pytest.mark.parametrize("format_id", ["explainer", "podcast", "product-review", "news"])
def test_non_documentary_formats_do_not_force_procedural_2d(format_id):
    assert uses_procedural_2d(format_id) is False


def test_factory_one_click_request_enables_subtitle_burn_in_by_default():
    factory_js = Path(__file__).resolve().parents[1] / "app" / "static" / "factory.js"
    source = factory_js.read_text(encoding="utf-8")
    assert 'JSON.stringify({burn_subtitles:true,sound_effects_enabled:true,quality:"high",fps:30})' in source
