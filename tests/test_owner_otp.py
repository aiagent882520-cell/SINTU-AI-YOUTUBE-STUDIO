from __future__ import annotations

import base64
import stat

from app import main
from scripts import setup_owner_otp


def test_totp_matches_rfc6238_sha1_vector_and_accepts_adjacent_window():
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    assert main._totp_code(secret, 59) == "287082"
    code = main._totp_code(secret, 59)
    assert main._verify_owner_otp(secret, code, 89) is True
    assert main._verify_owner_otp(secret, "000000", 59) is False
    assert main._verify_owner_otp(secret, "not-a-code", 59) is False


def test_owner_otp_secret_write_is_atomic_and_private(tmp_path):
    env = tmp_path / ".env"
    env.write_text("SINTU_ADMIN_USERNAME=owner\nOTHER=value\n", encoding="utf-8")
    lines, values = setup_owner_otp.read_env_lines(env)
    secret = base64.b32encode(b"01234567890123456789").decode("ascii").rstrip("=")
    setup_owner_otp.write_secret(env, lines, secret)
    updated, parsed = setup_owner_otp.read_env_lines(env)
    assert parsed["SINTU_ADMIN_USERNAME"] == "owner"
    assert parsed["OTHER"] == "value"
    assert parsed["SINTU_OWNER_TOTP_SECRET"] == secret
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert sum(line.startswith("SINTU_OWNER_TOTP_SECRET=") for line in updated) == 1


def test_owner_otp_rotation_replaces_existing_secret_line_without_duplicates(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "SINTU_OWNER_TOTP_SECRET=OLDSECRET\n# keep this comment\nSINTU_ADMIN_USERNAME=owner\n",
        encoding="utf-8",
    )
    lines, _ = setup_owner_otp.read_env_lines(env)
    setup_owner_otp.write_secret(env, lines, "NEWSECRET")
    text = env.read_text(encoding="utf-8")
    assert "SINTU_OWNER_TOTP_SECRET=OLDSECRET" not in text
    assert "SINTU_OWNER_TOTP_SECRET=NEWSECRET" in text
    assert "# keep this comment" in text
    assert text.count("SINTU_OWNER_TOTP_SECRET=") == 1
