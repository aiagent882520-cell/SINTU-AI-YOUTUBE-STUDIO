"""Safe, capability-aware planning for the end-to-end SINTU production factory.

This module deliberately separates planning from execution. Catalogue presence is not a
health check; local engines must be probed before a stage can run. Publishing and paid
services always require explicit Owner authorization.
"""
from __future__ import annotations

from typing import Any

from .provider_registry import list_providers

PIPELINE_VERSION = "1.0"

_STAGE_DEFINITIONS = (
    ("intake", "Brief and format validation", "planning", (), "automatic"),
    ("research", "Topic and source research", "research", ("web_research", "research"), "automatic"),
    ("strategy", "Audience, angle and content strategy", "strategy", ("planning", "text"), "automatic"),
    ("writing", "Script, storyboard and metadata", "writing", ("script", "text"), "automatic"),
    ("visuals", "Thumbnail, images and visual assets", "visuals", ("image",), "automatic"),
    ("audio", "Hindi voice, music and sound design", "audio", ("text_to_speech", "audio"), "automatic"),
    ("assembly", "Video edit, captions and render", "assembly", ("video", "transcode"), "automatic"),
    ("quality", "Independent visual, audio and policy checks", "quality", ("quality_check", "analysis"), "automatic"),
    ("owner_review", "Owner review of final deliverables", "approval", (), "owner_required"),
    ("publishing", "YouTube and social publishing", "publishing", (), "owner_required"),
    ("analytics", "Performance and earnings analysis", "analytics", ("business_analytics",), "automatic"),
)

# Only capabilities supplied by a provider that is already part of this repository's
# runtime may be selected automatically. Optional engines and catalogue-only vendors
# require a separate installation/license/health verification.
_RUNTIME_STATUSES = frozenset({
    "integrated",
    "adapter_available_credentials_optional",
    "integrated_test_dependency",
})


def _provider_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("id")): row for row in rows if isinstance(row, dict) and row.get("id")}


def _candidate_providers(capability: str, rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    matches = []
    for row in rows:
        if capability not in row.get("capabilities", []):
            continue
        status = str(row.get("status", "unknown"))
        matches.append({
            "id": str(row["id"]),
            "name": str(row.get("name", row["id"])),
            "status": status,
            "pricing": str(row.get("pricing", "unknown")),
            "selection": "runtime_supported" if status in _RUNTIME_STATUSES else "verify_before_use",
        })
    return matches


def build_pipeline_plan(
    topic: str,
    format_id: str,
    *,
    providers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a transparent, non-executing production plan."""
    clean_topic = (topic or "").strip()
    clean_format = (format_id or "").strip()
    if not clean_topic or len(clean_topic) > 5000:
        raise ValueError("Topic must contain 1 to 5000 characters.")
    if not clean_format or len(clean_format) > 80:
        raise ValueError("Format ID must contain 1 to 80 characters.")

    rows = providers if providers is not None else list_providers()
    stages = []
    for index, (stage_id, name, department, capabilities, approval) in enumerate(_STAGE_DEFINITIONS, 1):
        candidates = []
        for capability in capabilities:
            candidates.extend(_candidate_providers(capability, rows))
        runtime = [item for item in candidates if item["selection"] == "runtime_supported"]
        verified_required = [item for item in candidates if item["selection"] != "runtime_supported"]
        if approval == "owner_required":
            readiness = "owner_approval_required"
        elif runtime:
            readiness = "runtime_health_check_required"
        elif verified_required:
            readiness = "installation_or_credentials_required"
        elif capabilities:
            readiness = "provider_unavailable"
        else:
            readiness = "ready_without_external_provider"
        stages.append({
            "sequence": index,
            "id": stage_id,
            "name": name,
            "department": department,
            "required_capabilities": list(capabilities),
            "provider_candidates": candidates,
            "readiness": readiness,
            "approval": approval,
            "auto_execute": approval == "automatic",
        })

    return {
        "pipeline_version": PIPELINE_VERSION,
        "topic": clean_topic,
        "format_id": clean_format,
        "execution_started": False,
        "execution_allowed": False,
        "free_first": True,
        "paid_auto_activation": False,
        "publishing_enabled": False,
        "owner_approval_required_for": ["owner_review", "publishing", "paid_provider_activation", "external_data_sharing"],
        "stages": stages,
        "notice": (
            "This is a plan, not a live health check or execution. Provider catalogue entries "
            "do not prove installation, credentials, licensing, capacity or availability."
        ),
    }


def validate_execution_policy(
    *,
    action: str,
    owner_approved: bool = False,
    paid_provider: bool = False,
    paid_upgrades_allowed: bool = False,
) -> None:
    """Fail closed for publishing, paid-provider use, and external side effects."""
    normalized = (action or "").strip().lower()
    if not normalized:
        raise ValueError("Action is required.")
    if paid_provider and not (paid_upgrades_allowed and owner_approved):
        raise PermissionError("Paid provider activation requires earned-revenue policy and explicit Owner approval.")
    if normalized in {"publish", "upload", "schedule", "share_externally", "delete_source"} and not owner_approved:
        raise PermissionError(f"{normalized} requires explicit Owner approval.")
