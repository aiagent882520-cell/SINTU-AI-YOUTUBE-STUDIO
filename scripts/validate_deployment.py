#!/usr/bin/env python3
"""Fail-closed validation for a public SINTU Docker deployment.

This validates configuration only; it never prints secret values or provisions
hosting, DNS, TLS, Google OAuth consent, or a YouTube channel.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from urllib.parse import urlsplit


PLACEHOLDERS = ("CHANGE-THIS", "YOUR-DOMAIN", "example.com", "changeme")


def validate_environment(env: dict[str, str], require_youtube: bool = True) -> list[str]:
    errors: list[str] = []

    def required(name: str) -> str:
        value = (env.get(name) or "").strip()
        if not value or any(marker.lower() in value.lower() for marker in PLACEHOLDERS):
            errors.append(f"{name} must be set to a real, non-placeholder value.")
            return ""
        return value

    if env.get("SINTU_AUTH_REQUIRED", "true").strip().lower() != "true":
        errors.append("SINTU_AUTH_REQUIRED must be true.")
    password = required("SINTU_ADMIN_PASSWORD")
    if password and len(password) < 16:
        errors.append("SINTU_ADMIN_PASSWORD must contain at least 16 characters.")
    secret = required("SINTU_SESSION_SECRET")
    if secret and len(secret) < 32:
        errors.append("SINTU_SESSION_SECRET must contain at least 32 characters.")
    if env.get("SINTU_COOKIE_SECURE", "").strip().lower() != "true":
        errors.append("SINTU_COOKIE_SECURE must be true behind public HTTPS.")
    if env.get("SINTU_BIND_ADDRESS", "127.0.0.1").strip() != "127.0.0.1":
        errors.append("SINTU_BIND_ADDRESS must remain 127.0.0.1 behind the host HTTPS reverse proxy.")
    if env.get("ENABLE_PAID_MEDIA_GENERATION", "false").strip().lower() == "true":
        errors.append("Paid media generation must remain disabled until revenue and owner approval.")

    redirect = (env.get("YOUTUBE_REDIRECT_URI") or "").strip()
    youtube_values = [
        (env.get("YOUTUBE_CLIENT_ID") or "").strip(),
        (env.get("YOUTUBE_CLIENT_SECRET") or "").strip(),
        redirect,
        (env.get("YOUTUBE_TOKEN_ENCRYPTION_KEY") or "").strip(),
    ]
    youtube_configured = all(youtube_values)
    if require_youtube and not youtube_configured:
        errors.append("YouTube OAuth requires client ID, client secret, HTTPS redirect URI, and token encryption key.")
    elif any(youtube_values) and not youtube_configured:
        errors.append("YouTube OAuth settings are partial; configure all four values or leave all blank.")

    if youtube_configured:
        parsed = urlsplit(redirect)
        if parsed.scheme != "https":
            errors.append("YOUTUBE_REDIRECT_URI must be HTTPS.")
        elif (
            not parsed.hostname
            or parsed.path != "/api/admin/youtube/oauth/callback"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.port not in (None, 443)
            or parsed.hostname.lower() in {"localhost", "localhost.localdomain"}
            or "." not in parsed.hostname
        ):
            errors.append(
                "YOUTUBE_REDIRECT_URI must be a public HTTPS URL on the standard port, "
                "without credentials/query/fragment, ending with /api/admin/youtube/oauth/callback."
            )
        key = env.get("YOUTUBE_TOKEN_ENCRYPTION_KEY", "").strip()
        try:
            from cryptography.fernet import Fernet
            Fernet(key.encode("ascii"))
        except (ImportError, ValueError, UnicodeEncodeError):
            errors.append("YOUTUBE_TOKEN_ENCRYPTION_KEY must be a valid Fernet key.")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate SINTU public deployment environment.")
    parser.add_argument("--production", action="store_true", help="Require complete YouTube OAuth configuration.")
    parser.add_argument("--allow-unconfigured-youtube", action="store_true", help="Validate deployment security before Google OAuth is configured.")
    args = parser.parse_args()
    errors = validate_environment(os.environ, require_youtube=args.production and not args.allow_unconfigured_youtube)
    report = {"valid": not errors, "checks": [
        "authentication enabled", "strong admin password", "session secret",
        "secure HTTPS cookie", "loopback-only app bind", "paid media policy",
        "YouTube OAuth completeness and encryption",
    ], "errors": errors}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
