"""Honest per-format export capabilities and default FFmpeg render profiles.

This maps the 60 catalog formats to the existing generic MP4 assembly backend.
It does not claim that every format has a native AI generation engine.
"""
from copy import deepcopy
from .studio_scope import video_formats

_SPECIALIZED_ONLY = {
    "360-video": "360-degree projection and metadata pipeline is not implemented.",
    "vr-video": "VR-specific projection, stereo layout and headset validation are not implemented.",
    "ar-video": "AR scene tracking and platform packaging are not implemented.",
    "virtual-production": "Live virtual-production capture and tracking integration are not implemented.",
}

def _resolution_for(item: dict) -> str:
    ratio = item["aspect_ratio"]
    if ratio == "9:16":
        return "1080x1920"
    if ratio == "1:1":
        return "1080x1080"
    if ratio == "2:1 / 360" or ratio in {"VR", "AR", "Platform-dependent"}:
        return "1920x1080"
    if ratio == "9:16 or 16:9":
        return "1080x1920" if item["preset"] in {"short", "ad", "avatar"} else "1920x1080"
    if ratio == "16:9 or 9:16":
        return "1920x1080" if item["preset"] not in {"short", "ad", "avatar"} else "1080x1920"
    return "1920x1080"

def format_render_profile(format_id: str) -> dict:
    item = next((entry for entry in video_formats() if entry["id"] == format_id), None)
    if item is None:
        raise KeyError(format_id)
    blocked_reason = _SPECIALIZED_ONLY.get(format_id)
    profile = {
        "format_id": item["id"],
        "name": item["name"],
        "preset": item["preset"],
        "aspect_ratio": item["aspect_ratio"],
        "default_resolution": _resolution_for(item),
        "fps_options": [24, 30, 60],
        "output": "MP4 / H.264",
        "brand_watermark": "SINTU AI YOUTUBE STUDIO",
        "burned_in_text": False,
        "generic_export_available": blocked_reason is None,
        "native_generation_ready": False,
        "required_source": "Approved scene images or generated MP4 clips",
        "engine": "FFmpeg storyboard/clip assembly",
        "limitations": [blocked_reason] if blocked_reason else [
            "This profile assembles supplied media; it does not generate original scenes by itself.",
            "Native format-specific generation and quality validation are not implied."
        ],
    }
    if item["preset"] in {"3d", "film", "immersive", "hybrid"}:
        profile["optional_native_engine"] = "Blender"
        profile["native_engine_status"] = "Install Blender and configure a validated scene workflow."
    return profile

def all_format_render_profiles() -> dict:
    profiles = [format_render_profile(item["id"]) for item in video_formats()]
    return {
        "format_count": len(profiles),
        "generic_export_ready_count": sum(p["generic_export_available"] for p in profiles),
        "specialized_pipeline_blocked_count": sum(not p["generic_export_available"] for p in profiles),
        "profiles": profiles,
        "policy": "Catalog inclusion is not proof of native generation or end-to-end production testing."
    }
