import pytest

from app.format_rendering import all_format_render_profiles, format_render_profile


def test_all_sixty_formats_have_a_render_profile_and_explicit_capability():
    result = all_format_render_profiles()
    assert result["format_count"] == 60
    assert len(result["profiles"]) == 60
    for profile in result["profiles"]:
        assert profile["format_id"]
        assert profile["default_resolution"] in {
            "1080x1920", "1080x1080", "1920x1080", "1920x960"
        }
        assert profile["output"] == "MP4 / H.264"
        assert profile["brand_watermark"] == "SINTU AI YOUTUBE STUDIO"
        assert profile["burned_in_text"] is False
        assert isinstance(profile["generic_export_available"], bool)
        assert profile["native_generation_ready"] is (profile["format_id"] in {"2d-cartoon", "story-animation"})


def test_specialized_immersive_and_virtual_production_formats_are_not_overclaimed():
    for format_id in ("360-video", "vr-video", "ar-video", "virtual-production"):
        profile = format_render_profile(format_id)
        assert profile["generic_export_available"] is False
        assert profile["limitations"]


def test_360_profile_exposes_projection_conversion_without_claiming_platform_readiness():
    profile = format_render_profile("360-video")
    assert profile["default_resolution"] == "1920x960"
    assert profile["engine"].startswith("FFmpeg v360")
    assert profile["required_source"] == "Approved scene images or generated MP4 clips"
    assert profile["immersive_export"]["projection_conversion_available"] is True
    assert profile["immersive_export"]["output_profiles"] == ["1920x960", "3840x1920"]
    assert profile["immersive_export"]["spherical_metadata_embedded"] is False
    assert profile["immersive_export"]["platform_ready"] is False
    assert profile["immersive_export"]["generates_original_360_scenes"] is False


def test_short_vertical_formats_default_to_vertical_export():
    assert format_render_profile("youtube-shorts")["default_resolution"] == "1080x1920"
    assert format_render_profile("instagram-reels")["default_resolution"] == "1080x1920"


def test_unknown_format_has_no_render_profile():
    with pytest.raises(KeyError):
        format_render_profile("not-a-real-format")



def test_2d_animation_formats_generate_from_scene_prompts_without_source_media():
    for format_id in ("2d-cartoon", "story-animation"):
        profile = format_render_profile(format_id)
        assert profile["generic_export_available"] is True
        assert profile["native_generation_ready"] is True
        assert "no input images required" in profile["required_source"]
        assert "SINTU Procedural 2D Animation" in profile["engine"]
