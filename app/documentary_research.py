"""Fail-closed structural validation for documentary research evidence packages.

This module does not browse, authenticate sources, or judge whether a source
actually supports a claim. It validates traceability and reports uncertainty;
a structurally valid package is never a factual-accuracy certificate.
"""
from __future__ import annotations

import ipaddress
import re
from datetime import date, datetime
from urllib.parse import urlsplit


CLAIM_TYPES = {"factual", "interpretive", "production_note"}
CLAIM_STATUSES = {"corroborated", "single_source", "disputed", "unverified"}
SOURCE_TYPES = {"primary", "academic", "government", "reputable_news", "reference", "other"}
MAX_CLAIMS = 500
MAX_SOURCES = 500
MAX_TEXT = 5000
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")


def _text(value, *, maximum=MAX_TEXT):
    return isinstance(value, str) and bool(value.strip()) and len(value.strip()) <= maximum


def _date(value, *, timestamp=False):
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if timestamp else date.fromisoformat(value)
    except ValueError:
        return False
    if timestamp:
        return parsed.tzinfo is not None and parsed.utcoffset() is not None
    return True


def _public_http_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        return False
    try:
        parsed = urlsplit(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False
        if parsed.username is not None or parsed.password is not None:
            return False
        host = parsed.hostname.rstrip(".").lower()
        if not host or any(char.isspace() for char in host):
            return False
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            return False
        if host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost"):
            return False
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and (
            address.is_private or address.is_loopback or address.is_link_local
            or address.is_reserved or address.is_unspecified or address.is_multicast
        ):
            return False
        return True
    except (TypeError, ValueError):
        return False


def validate_research_package(package):
    """Return structural errors/warnings; never assert factual truth or source independence."""
    errors = []
    warnings = []
    if not isinstance(package, dict):
        return {"valid": False, "errors": ["package: expected an object"], "warnings": [],
                "claim_count": 0, "source_count": 0,
                "acceptance_boundary": "Structural validation only; no live research or semantic fact verification."}

    if type(package.get("schema_version")) is not int or package.get("schema_version") != 1:
        errors.append("schema_version: expected integer 1")
    if not _text(package.get("topic"), maximum=1000):
        errors.append("topic: required non-empty string (max 1000 characters)")
    if not _date(package.get("researched_at"), timestamp=True):
        errors.append("researched_at: expected ISO-8601 timestamp with timezone")

    sources = package.get("sources")
    claims = package.get("claims")
    if not isinstance(sources, list) or not 1 <= len(sources) <= MAX_SOURCES:
        errors.append(f"sources: expected 1–{MAX_SOURCES} source objects")
        sources = []
    if not isinstance(claims, list) or not 1 <= len(claims) <= MAX_CLAIMS:
        errors.append(f"claims: expected 1–{MAX_CLAIMS} claim objects")
        claims = []

    source_ids = set()
    source_publishers = {}
    for index, source in enumerate(sources):
        prefix = f"sources[{index}]"
        if not isinstance(source, dict):
            errors.append(f"{prefix}: expected an object")
            continue
        source_id = source.get("id")
        if not isinstance(source_id, str) or not _ID.fullmatch(source_id):
            errors.append(f"{prefix}.id: invalid identifier")
        elif source_id in source_ids:
            errors.append(f"{prefix}.id: duplicate identifier {source_id}")
        else:
            source_ids.add(source_id)
            source_publishers[source_id] = str(source.get("publisher", "")).strip().casefold()
        if not _text(source.get("title"), maximum=500):
            errors.append(f"{prefix}.title: required non-empty title")
        if not _text(source.get("publisher"), maximum=300):
            errors.append(f"{prefix}.publisher: required publisher/issuing body")
        if not _public_http_url(source.get("url")):
            errors.append(f"{prefix}.url: expected a public HTTP(S) URL without credentials or private IP")
        if not _date(source.get("accessed_at")):
            errors.append(f"{prefix}.accessed_at: expected ISO date (YYYY-MM-DD)")
        published = source.get("published_at")
        if published not in (None, "") and not _date(published):
            errors.append(f"{prefix}.published_at: expected ISO date or null")
        source_type = source.get("source_type")
        if not isinstance(source_type, str) or source_type not in SOURCE_TYPES:
            errors.append(f"{prefix}.source_type: unsupported source classification")
        excerpt = source.get("evidence_excerpt")
        if excerpt not in (None, "") and not _text(excerpt, maximum=2000):
            errors.append(f"{prefix}.evidence_excerpt: must be 1–2000 characters when supplied")

    claim_ids = set()
    for index, claim in enumerate(claims):
        prefix = f"claims[{index}]"
        if not isinstance(claim, dict):
            errors.append(f"{prefix}: expected an object")
            continue
        claim_id = claim.get("id")
        if not isinstance(claim_id, str) or not _ID.fullmatch(claim_id):
            errors.append(f"{prefix}.id: invalid identifier")
        elif claim_id in claim_ids:
            errors.append(f"{prefix}.id: duplicate identifier {claim_id}")
        else:
            claim_ids.add(claim_id)
        if not _text(claim.get("text")):
            errors.append(f"{prefix}.text: required non-empty claim")
        kind = claim.get("claim_type")
        status = claim.get("status")
        if not isinstance(kind, str) or kind not in CLAIM_TYPES:
            errors.append(f"{prefix}.claim_type: unsupported claim type")
        if not isinstance(status, str) or status not in CLAIM_STATUSES:
            errors.append(f"{prefix}.status: unsupported evidence status")
        refs = claim.get("source_ids")
        if not isinstance(refs, list) or any(not isinstance(item, str) for item in refs):
            errors.append(f"{prefix}.source_ids: expected an array of source IDs")
            refs = []
        if len(refs) != len(set(refs)):
            errors.append(f"{prefix}.source_ids: duplicate source reference")
        missing = [item for item in refs if item not in source_ids]
        if missing:
            errors.append(f"{prefix}.source_ids: unknown source IDs {missing}")
        if refs and not _text(claim.get("evidence_notes"), maximum=2000):
            errors.append(f"{prefix}.evidence_notes: explain how the cited source relates to the claim")
        if kind == "factual" and status in CLAIM_STATUSES:
            if status in {"corroborated", "single_source", "disputed"} and not refs:
                errors.append(f"{prefix}: factual claim marked {status} must cite at least one source")
            if status == "corroborated" and not missing:
                publishers = {source_publishers.get(item, "") for item in refs}
                publishers.discard("")
                if len(publishers) < 2:
                    errors.append(f"{prefix}: corroborated factual claim needs sources from at least two named publishers")
                warnings.append(f"{prefix}: publisher count is not proof of source independence or claim support")
            if status == "single_source":
                warnings.append(f"{prefix}: factual claim has only one cited source")
            if status == "disputed":
                warnings.append(f"{prefix}: disputed factual claim must be presented with its disagreement")
            if status == "unverified":
                warnings.append(f"{prefix}: unverified factual claim must not be narrated as established fact")
        elif isinstance(kind, str) and kind in CLAIM_TYPES and status in {"corroborated", "single_source"} and not refs:
            errors.append(f"{prefix}: sourced status requires at least one source")

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "claim_count": len(claims),
        "source_count": len(sources),
        "acceptance_boundary": (
            "Structural traceability only. This validator does not browse, verify source authenticity, "
            "evaluate source quality, establish source independence, or determine whether evidence proves a claim."
        ),
    }
