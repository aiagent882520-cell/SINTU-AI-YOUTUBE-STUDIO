from scripts.firewall_safety_audit import audit_config


def safe_env(**overrides):
    values = {
        "SINTU_BIND_ADDRESS": "127.0.0.1",
        "SINTU_ALLOWED_IPS": "",
        "SINTU_RATE_LIMIT_PER_MINUTE": "300",
        "SINTU_BRIDGE_TOKEN": "a" * 64,
        "SINTU_BRIDGE_WORKER_TOKEN": "b" * 64,
        "SINTU_SESSION_SECRET": "c" * 64,
        "SINTU_AUTH_REQUIRED": "true",
        "SINTU_AUTOMATION_ONLY": "true",
    }
    values.update(overrides)
    return values


def test_safe_local_configuration_passes_and_never_changes_phone_firewall():
    result = audit_config(safe_env())
    assert result["ok"] is True
    assert result["device_firewall_modified"] is False
    assert result["phone_network_modified"] is False


def test_public_bind_is_rejected():
    result = audit_config(safe_env(SINTU_BIND_ADDRESS="0.0.0.0"))
    assert result["ok"] is False
    assert any(item["name"] == "loopback_only_binding" and not item["ok"] for item in result["checks"])


def test_bad_allowlist_is_reported_without_changing_network():
    result = audit_config(safe_env(SINTU_ALLOWED_IPS="not-a-cidr"))
    assert result["ok"] is False
    assert result["phone_network_modified"] is False


def test_allowlist_without_loopback_warns_that_dashboard_may_be_blocked():
    result = audit_config(safe_env(SINTU_ALLOWED_IPS="192.0.2.1"))
    check = next(item for item in result["checks"] if item["name"] == "local_access_preserved")
    assert check["ok"] is False
    assert check["severity"] == "warning"


def test_authentication_off_is_rejected():
    result = audit_config(safe_env(SINTU_AUTH_REQUIRED="false"))
    assert result["ok"] is False


def test_rate_limit_outside_safe_range_is_rejected():
    result = audit_config(safe_env(SINTU_RATE_LIMIT_PER_MINUTE="1"))
    assert result["ok"] is False
