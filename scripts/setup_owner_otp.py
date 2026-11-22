#!/usr/bin/env python3
"""Enroll or rotate the SINTU Owner's free mobile authenticator TOTP secret."""
from __future__ import annotations

import argparse
import base64
import os
import secrets
import tempfile
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
KEY_NAME = "SINTU_OWNER_TOTP_SECRET"


def read_env_lines(path: Path) -> tuple[list[str], dict[str, str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, value = stripped.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return lines, values


def write_secret(path: Path, lines: list[str], secret: str) -> None:
    replacements = {
        "SINTU_OWNER_OTP_REQUIRED": "SINTU_OWNER_OTP_REQUIRED=true",
        KEY_NAME: f"{KEY_NAME}={secret}",
    }
    updated, found = [], set()
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in replacements:
            if key not in found:
                updated.append(replacements[key])
                found.add(key)
        else:
            updated.append(line)
    for key, value in replacements.items():
        if key not in found:
            updated.append(value)
    fd, temp_name = tempfile.mkstemp(prefix=".sintu-owner-otp-", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\\n".join(updated).rstrip() + "\\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        os.chmod(path, 0o600)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rotate", action="store_true",
                        help="Replace an existing Owner OTP secret; old authenticator codes stop working immediately.")
    args = parser.parse_args()
    if not ENV_PATH.is_file():
        parser.error(f"{ENV_PATH} is missing. Run the SINTU installer first.")
    lines, values = read_env_lines(ENV_PATH)
    if values.get(KEY_NAME) and not args.rotate:
        parser.error("Owner OTP is already enrolled. Use --rotate only when intentionally replacing the authenticator.")
    username = values.get("SINTU_OWNER_USERNAME") or values.get("SINTU_ADMIN_USERNAME") or "admin"
    secret = base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")
    write_secret(ENV_PATH, lines, secret)
    label = quote("SINTU AI YOUTUBE STUDIO:" + username, safe="")
    issuer = quote("SINTU AI YOUTUBE STUDIO", safe="")
    uri = (f"otpauth://totp/{label}?secret={secret}&issuer={issuer}"
           "&algorithm=SHA1&digits=6&period=30")
    print("Owner mobile authenticator enrollment saved in .env (file mode 600).")
    print("Account:", username)
    print("Scan/paste this provisioning URI into a mobile authenticator app:")
    print(uri)
    print("Manual setup key:", secret)
    print("Keep this URI/key private. The Owner must enter the current 6-digit code at login.")\n    print("Restart SINTU after enrollment so the running API loads the new secret: bash scripts/termux_apply_update.sh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
