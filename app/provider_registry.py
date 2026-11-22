"""Capability-oriented provider catalogue for the SINTU production factory.

Catalogue entries describe candidates and current local adapters. A catalogue entry is
not proof that a third-party service is installed, licensed, authenticated or live.
"""
from __future__ import annotations

from typing import Any

# Stable IDs are API-safe. Keep status honest: only local adapters already present in
# the repository are marked integrated; external products remain planned candidates.
_PROVIDER_ROWS = [
    ("local_ollama", "Ollama", "text", "free_local", "integrated", ["text", "planning", "script", "analysis"]),
    ("local_openai_compatible", "llama.cpp / LocalAI / LM Studio", "text", "free_local", "integrated", ["text", "planning", "script", "analysis"]),
    ("openai_api", "OpenAI API", "text", "paid_optional", "adapter_available_credentials_optional", ["text", "reasoning", "vision", "audio"]),
    ("gemini_api", "Google Gemini API", "multimodal", "free_tier_or_paid", "adapter_available_credentials_optional", ["text", "image", "video", "audio", "research"]),
    ("anthropic_api", "Anthropic Claude API", "text", "paid_optional", "adapter_available_credentials_optional", ["text", "reasoning", "analysis"]),
    ("deepseek_api", "DeepSeek API", "text", "paid_optional", "adapter_available_credentials_optional", ["text", "reasoning", "coding"]),
    ("comfyui", "ComfyUI", "image_video", "free_local", "optional_local_engine", ["image", "image_to_image", "video_workflows"]),
    ("blender", "Blender", "3d_video", "free_open_source", "optional_local_engine", ["3d", "animation", "render"]),
    ("ffmpeg", "FFmpeg", "media", "free_open_source", "optional_local_engine", ["video", "audio", "transcode", "quality_check"]),
    ("piper", "Piper TTS", "audio", "free_open_source", "optional_local_engine", ["text_to_speech"]),
    ("whisper", "Whisper", "audio", "free_open_source", "planned", ["speech_to_text", "transcription"]),
    ("kdenlive", "Kdenlive", "video", "free_open_source", "planned_desktop_tool", ["video_editing"]),
    ("krita", "Krita", "image", "free_open_source", "planned_desktop_tool", ["image", "painting", "animation"]),
    ("gimp", "GIMP", "image", "free_open_source", "planned_desktop_tool", ["image_editing", "thumbnail"]),
    ("inkscape", "Inkscape", "design", "free_open_source", "planned_desktop_tool", ["vector", "logo", "diagram"]),
    ("audacity", "Audacity", "audio", "free_open_source", "planned_desktop_tool", ["audio_editing"]),
    ("n8n", "n8n", "automation", "free_self_hosted_or_paid_cloud", "planned", ["workflow_automation"]),
    ("dify", "Dify", "agents", "free_self_hosted_or_paid_cloud", "planned", ["agent_workflows"]),
    ("playwright", "Playwright", "testing", "free_open_source", "integrated_test_dependency", ["browser_testing"]),
    ("pytest", "pytest", "testing", "free_open_source", "integrated_test_dependency", ["python_testing"]),
    ("semgrep", "Semgrep", "security", "free_tier_or_paid", "planned", ["static_analysis"]),
    ("trivy", "Trivy", "security", "free_open_source", "planned", ["container_and_dependency_scan"]),
    ("gitleaks", "Gitleaks", "security", "free_open_source", "planned", ["secret_scan"]),
    ("canva", "Canva", "design", "free_tier_or_paid", "external_optional", ["thumbnail", "social_graphics", "presentation"]),
    ("photoshop", "Adobe Photoshop", "image", "paid_optional", "external_optional", ["image_editing", "thumbnail"]),
    ("midjourney", "Midjourney", "image", "paid_optional", "external_optional", ["image_generation"]),
    ("ideogram", "Ideogram", "image", "free_tier_or_paid", "external_optional", ["image_generation", "text_in_image"]),
    ("runway", "Runway", "video", "free_tier_or_paid", "external_optional", ["video_generation", "video_editing"]),
    ("kling", "Kling AI", "video", "free_tier_or_paid", "external_optional", ["video_generation"]),
    ("elevenlabs", "ElevenLabs", "audio", "free_tier_or_paid", "external_optional", ["text_to_speech", "voice"]),
    ("artlist", "Artlist", "audio", "paid_optional", "external_optional", ["licensed_music", "sound_effects"]),
    ("perplexity", "Perplexity", "research", "free_tier_or_paid", "external_optional", ["web_research"]),
    ("vidiq", "vidIQ", "youtube", "free_tier_or_paid", "external_optional", ["youtube_seo", "channel_research"]),
    ("tubebuddy", "TubeBuddy", "youtube", "free_tier_or_paid", "external_optional", ["youtube_seo"]),
    ("semrush", "Semrush", "research_marketing", "paid_optional", "external_optional", ["seo", "competitor_research"]),
    ("ahrefs", "Ahrefs", "research_marketing", "paid_optional", "external_optional", ["seo", "backlinks"]),
    ("metabase", "Metabase", "analytics", "free_open_source", "planned", ["business_analytics"]),
    ("libreoffice", "LibreOffice", "documents", "free_open_source", "planned_desktop_tool", ["pdf", "documents", "spreadsheets", "presentations"]),
]

def list_providers(*, include_external: bool = True) -> list[dict[str, Any]]:
    """Return sanitized provider metadata; never returns credentials or secret values."""
    rows = []
    for provider_id, name, category, pricing, status, capabilities in _PROVIDER_ROWS:
        if not include_external and status == "external_optional":
            continue
        rows.append({
            "id": provider_id,
            "name": name,
            "category": category,
            "pricing": pricing,
            "status": status,
            "capabilities": list(capabilities),
            "credential_values_exposed": False,
        })
    return rows

def provider_summary() -> dict[str, Any]:
    rows = list_providers()
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return {
        "total": len(rows),
        "integrated_or_runtime_supported": sum(
            row["status"] in {"integrated", "adapter_available_credentials_optional", "optional_local_engine", "integrated_test_dependency"}
            for row in rows
        ),
        "planned_or_external": sum(
            row["status"] in {"planned", "planned_desktop_tool", "external_optional"}
            for row in rows
        ),
        "status_counts": counts,
        "free_first": True,
        "paid_auto_activation": False,
        "note": "Catalogue presence is not proof of installation, credentials, license clearance or live health.",
    }
