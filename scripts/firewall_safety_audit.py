#!/usr/bin/env python3
"""Read-only SINTU firewall and Android-safe network configuration audit.

This tool never changes Android firewall/VPN/DNS settings or installs packet
filters. It only checks SINTU's own application-layer security configuration.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
except ImportError:
    pass


def audit_config(env: dict[str, str] | None = None) -> dict:
    values = os.environ if env is None else env
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str, severity: str = "error") -> None:
        checks.append({"name": name, "ok": bool(ok), "severity": severity, "detail": detail})

    bind = values.get("SINTU_BIND_ADDRESS", "127.0.0.1").strip()
    try:
        bind_ip = ipaddress.ip_address(bind)
        loopback = bind_ip.is_loopback
    except ValueError:
        loopback = bind.lower() == "localhost"
    add(
        "loopback_only_binding",
        loopback,
        "SINTU listens only on this phone (loopback)." if loopback
        else "Unsafe bind address. Keep SINTU_BIND_ADDRESS=127.0.0.1; do not expose the API to Wi-Fi/mobile networks.",
    )

    rules = values.get("SINTU_ALLOWED_IPS", "").strip()
    if rules:
        try:
            networks = [ipaddress.ip_network(item.strip(), strict=False)
                        for item in rules.split(",") if item.strip()]
            valid = bool(networks)
            local_allowed = any(ipaddress.ip_address("127.0.0.1") in net for net in networks)
            add("ip_allowlist_syntax", valid, "IP/CIDR allowlist parsed." if valid else "Allowlist is empty or invalid.")
            add(
                "local_access_preserved",
                local_allowed,
                "Loopback access is permitted." if local_allowed
                else "WARNING: allowlist may block the local SINTU dashboard. Add 127.0.0.1/32 and ::1/128 or clear SINTU_ALLOWED_IPS.",
                "warning",
            )
        except ValueError:
            add("ip_allowlist_syntax", False, "Invalid SINTU_ALLOWED_IPS; correct it or leave it blank for local-only use.")
    else:
        add("ip_allowlist_syntax", True, "Optional IP allowlist is disabled; loopback-only binding still protects the phone.")

    try:
        limit = int(values.get("SINTU_RATE_LIMIT_PER_MINUTE", "300"))
        valid_limit = 30 <= limit <= 3000
    except (TypeError, ValueError):
        limit, valid_limit = 0, False
    add(
        "api_rate_limit",
        valid_limit,
        f"API limit is {limit} requests/minute." if valid_limit
        else "Set SINTU_RATE_LIMIT_PER_MINUTE to an integer from 30 to 3000 to avoid accidental lockouts or ineffective throttling.",
    )

    for name in ("SINTU_BRIDGE_TOKEN", "SINTU_BRIDGE_WORKER_TOKEN", "SINTU_SESSION_SECRET"):
        secret = values.get(name, "")
        ok = len(secret) >= 32 and not secret.startswith("CHANGE-THIS")
        add(name.lower(), ok, f"{name} is configured with sufficient length." if ok
            else f"{name} is missing or weak. Use a unique random secret of at least 32 characters.", "warning")

    auth = values.get("SINTU_AUTH_REQUIRED", "true").strip().lower()
    add(
        "admin_authentication",
        auth in {"1", "true", "yes", "on"},
        "Admin authentication is enabled." if auth in {"1", "true", "yes", "on"}
        else "Admin authentication is disabled; enable SINTU_AUTH_REQUIRED=true.",
    )

    automation_only = values.get("SINTU_AUTOMATION_ONLY", "true").strip().lower()
    add(
        "production_safety_gate",
        automation_only in {"1", "true", "yes", "on"},
        "Production remains paused while automation safety work is active." if automation_only in {"1", "true", "yes", "on"}
        else "Production safety gate is disabled; verify readiness before enabling production.",
        "warning",
    )

    errors = sum(not item["ok"] and item["severity"] == "error" for item in checks)
    warnings = sum(not item["ok"] and item["severity"] == "warning" for item in checks)
    return {
        "ok": errors == 0,
        "mode": "application-layer-only",
        "device_firewall_modified": False,
        "phone_network_modified": False,
        "checks": checks,
        "summary": {"passed": sum(item["ok"] for item in checks), "errors": errors, "warnings": warnings},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = audit_config()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("SINTU ADVANCED FIREWALL SAFETY AUDIT")
        for item in report["checks"]:
            marker = "PASS" if item["ok"] else item["severity"].upper()
            print(f"[{marker}] {item['name']}: {item['detail']}")
        print("Summary:", json.dumps(report["summary"]))
        print("No Android firewall, VPN, DNS or phone-wide network settings were changed.")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
