import json
import sqlite3

from app import principal_ai_council as council


def _connection():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def _provider_status(missing=(), local=False):
    providers = {
        "openai": {"configured": "chatgpt" not in missing, "model": "gpt-test"},
        "gemini": {"configured": "gemini" not in missing, "model": "gemini-test"},
        "claude": {"configured": "claude" not in missing, "model": "claude-test"},
        "deepseek": {"configured": "deepseek" not in missing, "model": "deepseek-test"},
        "local": {"configured": local, "model": "local-test"},
    }
    return providers


def _fake_vote(vote):
    return json.dumps({
        "vote": vote,
        "rationale": "The decision was checked against the supplied evidence.",
        "evidence": ["Evidence item verified in the test fixture."],
        "risks": ["A test risk."],
    })


def test_council_status_never_confuses_credentials_with_live_health(monkeypatch):
    monkeypatch.setattr(council, "provider_status", lambda: _provider_status())
    monkeypatch.setattr(council, "paid_upgrades_allowed", lambda: True)
    status = council.council_status()
    assert [item["id"] for item in status["principal_ais"]] == [
        "chatgpt", "gemini", "claude", "deepseek"
    ]
    assert status["all_principals_eligible_to_call"] is True
    assert status["council_ready"] is False
    assert status["live_provider_health"] == "NOT_CHECKED"
    assert all(item["status"] == "credentials_configured_not_live_verified" for item in status["principal_ais"])
    assert status["local_fallback"]["counts_as_principal_vote"] is False


def test_majority_requires_three_of_four_and_code_integration_needs_owner(monkeypatch):
    conn = _connection()
    monkeypatch.setattr(council, "provider_status", lambda: _provider_status())
    monkeypatch.setattr(council, "paid_upgrades_allowed", lambda: True)
    votes = {"openai": "APPROVE", "gemini": "APPROVE", "claude": "APPROVE", "deepseek": "REJECT"}
    monkeypatch.setattr(council, "generate_text", lambda prompt, workflow, provider_override=None: {
        "provider": provider_override, "model": "mock-" + provider_override,
        "output": _fake_vote(votes[provider_override]),
    })
    decision = council.run_council_decision(
        conn, "owner", "Integrate approved feature", "CI and audit evidence attached.", "code_integration"
    )
    assert decision["status"] == "pending_owner_approval"
    assert decision["owner_approval_status"] == "pending"
    assert decision["result"]["vote_counts"] == {"APPROVE": 3, "REJECT": 1, "ABSTAIN": 0}
    approved = council.owner_approve_decision(conn, "owner", "owner", decision["id"], True, "Approved after review.")
    assert approved["status"] == "owner_approved"
    assert approved["owner_approval_status"] == "approved"
    assert council.verify_audit_chain(conn, "owner")["valid"] is True


def test_sensitive_decision_requires_unanimous_vote(monkeypatch):
    conn = _connection()
    monkeypatch.setattr(council, "provider_status", lambda: _provider_status())
    monkeypatch.setattr(council, "paid_upgrades_allowed", lambda: True)
    votes = {"openai": "APPROVE", "gemini": "APPROVE", "claude": "APPROVE", "deepseek": "REJECT"}
    monkeypatch.setattr(council, "generate_text", lambda prompt, workflow, provider_override=None: {
        "provider": provider_override, "model": "mock",
        "output": _fake_vote(votes[provider_override]),
    })
    decision = council.run_council_decision(
        conn, "owner", "Change security boundary", "Evidence for a proposed security change.", "security"
    )
    assert decision["status"] == "rejected_unanimity_gate"
    assert decision["owner_approval_status"] == "not_required"


def test_two_to_two_vote_requests_research_and_revote(monkeypatch):
    conn = _connection()
    monkeypatch.setattr(council, "provider_status", lambda: _provider_status())
    monkeypatch.setattr(council, "paid_upgrades_allowed", lambda: True)
    votes = {"openai": "APPROVE", "gemini": "APPROVE", "claude": "REJECT", "deepseek": "REJECT"}
    monkeypatch.setattr(council, "generate_text", lambda prompt, workflow, provider_override=None: {
        "provider": provider_override, "model": "mock",
        "output": _fake_vote(votes[provider_override]),
    })
    decision = council.run_council_decision(
        conn, "owner", "Choose an architecture", "Two alternatives and their evidence.", "major"
    )
    assert decision["status"] == "needs_research_and_revote"


def test_missing_principal_blocks_major_decision_and_local_is_advisory_only(monkeypatch):
    conn = _connection()
    monkeypatch.setattr(council, "provider_status", lambda: _provider_status(missing={"claude"}, local=True))
    monkeypatch.setattr(council, "paid_upgrades_allowed", lambda: True)
    called = []
    def fake_generate(prompt, workflow, provider_override=None):
        called.append(provider_override)
        if provider_override == "local":
            return {"provider": "local", "model": "local-test", "output": "Research gaps and next steps."}
        return {"provider": provider_override, "model": "mock", "output": _fake_vote("APPROVE")}
    monkeypatch.setattr(council, "generate_text", fake_generate)
    decision = council.run_council_decision(
        conn, "owner", "Evaluate a feature", "Feature requirements and tests.", "major"
    )
    assert decision["status"] == "blocked_incomplete_council"
    assert decision["result"]["all_four_valid_votes"] is False
    assert decision["result"]["local_advisory"]["status"] == "advisory_only"
    assert "local" in called
    claude = next(item for item in decision["votes"] if item["principal_id"] == "claude")
    assert claude["status"] == "blocked"
    assert claude["vote"] == ""


def test_paid_policy_prevents_all_cloud_provider_calls(monkeypatch):
    conn = _connection()
    monkeypatch.setattr(council, "provider_status", lambda: _provider_status())
    monkeypatch.setattr(council, "paid_upgrades_allowed", lambda: False)
    def should_not_call(*args, **kwargs):
        raise AssertionError("Paid provider must not be called while policy is locked.")
    monkeypatch.setattr(council, "generate_text", should_not_call)
    decision = council.run_council_decision(
        conn, "owner", "Review paid integration", "No paid call is permitted.", "paid_action"
    )
    assert decision["status"] == "blocked_incomplete_council"
    assert all(item["status"] == "blocked" for item in decision["votes"])


def test_hash_chained_audit_detects_tampering(monkeypatch):
    conn = _connection()
    monkeypatch.setattr(council, "provider_status", lambda: _provider_status())
    monkeypatch.setattr(council, "paid_upgrades_allowed", lambda: False)
    decision = council.run_council_decision(
        conn, "owner", "Check audit", "Audit evidence.", "major"
    )
    assert council.verify_audit_chain(conn, "owner")["valid"] is True
    conn.execute("UPDATE principal_ai_audit SET payload_json='{}' WHERE id=1")
    assert council.verify_audit_chain(conn, "owner")["valid"] is False
