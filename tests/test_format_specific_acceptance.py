"""Per-format contract acceptance; profile checks are not proof of native generation."""
import pytest

from app.format_rendering import format_render_profile
from app.studio_scope import video_formats

FORMAT_ROWS = {row["id"]: row for row in video_formats()}
FORMAT_IDS = tuple(FORMAT_ROWS)
SPECIALIZED_BLOCKED = {"360-video", "vr-video", "ar-video", "virtual-production"}
PROCEDURAL_NATIVE = {"2d-cartoon", "story-animation"}


@pytest.mark.parametrize("format_id", FORMAT_IDS, ids=FORMAT_IDS)
def test_each_catalog_format_has_an_individually_validated_render_contract(format_id):
    source = FORMAT_ROWS[format_id]
    profile = format_render_profile(format_id)

    assert profile["format_id"] == format_id
    assert profile["name"] == source["name"]
    assert profile["preset"] == source["preset"]
    assert profile["aspect_ratio"] == source["aspect_ratio"]
    assert profile["default_resolution"] in {"1080x1920", "1080x1080", "1920x1080"}
    assert profile["fps_options"] == [24, 30, 60]
    assert profile["output"] == "MP4 / H.264"
    assert profile["brand_watermark"] == "SINTU AI YOUTUBE STUDIO"
    assert profile["burned_in_text"] is False
    assert isinstance(profile["generic_export_available"], bool)
    assert profile["limitations"], "Every format must state what this profile does not prove."

    # These fields describe generic assembly capabilities, not native creative engines.
    assert profile["generic_export_available"] is (format_id not in SPECIALIZED_BLOCKED)
    assert profile["native_generation_ready"] is (format_id in PROCEDURAL_NATIVE)
    if format_id in PROCEDURAL_NATIVE:
        assert "no input images required" in profile["required_source"]
        assert "SINTU Procedural 2D Animation" in profile["engine"]
    else:
        assert profile["required_source"] == "Approved scene images or generated MP4 clips"

    if format_id in SPECIALIZED_BLOCKED:
        assert profile["limitations"][0]
    elif format_id in PROCEDURAL_NATIVE:
        assert "Local vector cartoon character animation" in profile["limitations"][0]
    else:
        assert "This profile assembles supplied media" in profile["limitations"][0]


def test_catalog_format_ids_are_unique_and_exactly_sixty():
    assert len(FORMAT_IDS) == 60
    assert len(set(FORMAT_IDS)) == 60


def test_unknown_format_is_rejected_without_fallback_profile():
    with pytest.raises(KeyError):
        format_render_profile("unknown-format-must-not-fall-back")
