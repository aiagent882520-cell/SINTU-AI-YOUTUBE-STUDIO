import base64
import os

from scripts.validate_deployment import validate_environment


def production_env():
    return {
        "SINTU_AUTH_REQUIRED": "true",
        "SINTU_ADMIN_PASSWORD": "a-unique-strong-password-123",
        "SINTU_SESSION_SECRET": "s" * 64,
        "SINTU_COOKIE_SECURE": "true",
        "SINTU_BIND_ADDRESS": "127.0.0.1",
        "ENABLE_PAID_MEDIA_GENERATION": "false",
        "YOUTUBE_CLIENT_ID": "client-id.apps.googleusercontent.com",
        "YOUTUBE_CLIENT_SECRET": "google-client-secret",
        "YOUTUBE_REDIRECT_URI": "https://studio.example.org/api/admin/youtube/oauth/callback",
        "YOUTUBE_TOKEN_ENCRYPTION_KEY": base64.urlsafe_b64encode(os.urandom(32)).decode(),
    }


def test_production_environment_passes_strict_validation():
    assert validate_environment(production_env(), require_youtube=True) == []


def test_public_deployment_rejects_missing_security_controls():
    env = production_env()
    env.update({
        "SINTU_AUTH_REQUIRED": "false",
        "SINTU_ADMIN_PASSWORD": "short",
        "SINTU_SESSION_SECRET": "short",
        "SINTU_COOKIE_SECURE": "false",
        "SINTU_BIND_ADDRESS": "0.0.0.0",
        "ENABLE_PAID_MEDIA_GENERATION": "true",
    })
    errors = validate_environment(env, require_youtube=True)
    assert any("AUTH_REQUIRED" in item for item in errors)
    assert any("16 characters" in item for item in errors)
    assert any("32 characters" in item for item in errors)
    assert any("COOKIE_SECURE" in item for item in errors)
    assert any("BIND_ADDRESS" in item for item in errors)
    assert any("Paid media" in item for item in errors)


def test_youtube_oauth_requires_complete_credentials_and_https_callback():
    env = production_env()
    env["YOUTUBE_CLIENT_SECRET"] = ""
    errors = validate_environment(env, require_youtube=True)
    assert any("requires client ID" in item for item in errors)

    env = production_env()
    env["YOUTUBE_REDIRECT_URI"] = "http://studio.example.org/api/admin/youtube/oauth/callback"
    errors = validate_environment(env, require_youtube=True)
    assert any("must be HTTPS" in item for item in errors)


def test_youtube_encryption_key_must_be_a_valid_fernet_key():
    env = production_env()
    env["YOUTUBE_TOKEN_ENCRYPTION_KEY"] = "not-a-valid-key"
    errors = validate_environment(env, require_youtube=True)
    assert any("valid Fernet key" in item for item in errors)


def test_youtube_can_remain_unconfigured_before_owner_oauth_setup():
    env = production_env()
    for name in (
        "YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET",
        "YOUTUBE_REDIRECT_URI", "YOUTUBE_TOKEN_ENCRYPTION_KEY",
    ):
        env[name] = ""
    assert validate_environment(env, require_youtube=False) == []


def test_partial_youtube_configuration_is_rejected_even_in_pre_oauth_mode():
    env = production_env()
    env["YOUTUBE_CLIENT_SECRET"] = ""
    errors = validate_environment(env, require_youtube=False)
    assert any("settings are partial" in item for item in errors)
