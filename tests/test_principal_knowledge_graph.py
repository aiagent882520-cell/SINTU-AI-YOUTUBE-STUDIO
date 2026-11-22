import sqlite3

import pytest

from app import principal_knowledge_graph as graph


def connection():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    graph.ensure_schema(conn)
    return conn


def test_private_and_shared_nodes_start_unverified_and_are_owner_scoped():
    conn = connection()
    private = graph.create_node(conn, "owner", "chatgpt", "private", "Plan", "Private notes")
    shared = graph.create_node(conn, "owner", "gemini", "shared", "Finding", "Needs source", source_refs=["https://example.test"])
    assert private["scope"] == "private" and private["status"] == "unverified"
    assert shared["scope"] == "shared" and shared["status"] == "unverified"
    assert graph.list_nodes(conn, "another-owner") == []
    assert graph.get_node(conn, "another-owner", private["id"]) is None


def test_only_explicit_owner_verification_marks_shared_knowledge_verified():
    conn = connection()
    node = graph.create_node(conn, "owner", "claude", "shared", "Claim", "A factual claim")
    with pytest.raises(ValueError):
        graph.verify_node(conn, "owner", "owner", node["id"], True, "")
    verified = graph.verify_node(conn, "owner", "owner", node["id"], True, "Cross-checked against two independent sources.")
    assert verified["status"] == "verified"
    assert verified["verified_by"] == "owner"
    disputed = graph.verify_node(conn, "owner", "owner", node["id"], False, "Sources conflict.")
    assert disputed["status"] == "disputed"
    assert disputed["verified_at"] is None


def test_graph_edges_require_both_owner_scoped_nodes():
    conn = connection()
    a = graph.create_node(conn, "owner", "chatgpt", "private", "A", "First")
    b = graph.create_node(conn, "owner", "deepseek", "shared", "B", "Second")
    edge = graph.link_nodes(conn, "owner", a["id"], b["id"], "supports")
    assert edge["relation"] == "supports"
    assert len(graph.list_edges(conn, "owner", a["id"])) == 1
    with pytest.raises(ValueError):
        graph.link_nodes(conn, "another-owner", a["id"], b["id"], "supports")


@pytest.mark.parametrize("principal", ["unknown", "", "openai"])
def test_unknown_principal_is_rejected(principal):
    with pytest.raises(ValueError):
        graph.create_node(connection(), "owner", principal, "private", "X", "Y")


def test_limits_and_invalid_status_filters_fail_closed():
    conn = connection()
    with pytest.raises(ValueError):
        graph.create_node(conn, "owner", "chatgpt", "private", " ", "content")
    with pytest.raises(ValueError):
        graph.list_nodes(conn, "owner", status="approved")


def test_knowledge_changes_are_recorded_in_owner_scoped_hash_chain():
    conn = connection()
    node = graph.create_node(conn, "owner", "chatgpt", "shared", "Claim", "Evidence pending")
    graph.verify_node(conn, "owner", "owner", node["id"], True, "Checked source A and B.")
    other = graph.create_node(conn, "owner", "gemini", "private", "Context", "Private context")
    graph.link_nodes(conn, "owner", node["id"], other["id"], "context_for")

    events = graph.list_audit_events(conn, "owner")
    assert [event["event_type"] for event in events] == [
        "knowledge.linked", "knowledge.created", "knowledge.verified", "knowledge.created"
    ]
    assert graph.verify_audit_chain(conn, "owner") == {
        "valid": True, "checked_events": 4, "invalid_sequence": None
    }
    assert graph.list_audit_events(conn, "someone-else") == []


def test_audit_chain_detects_tampering_and_database_blocks_update_delete():
    conn = connection()
    node = graph.create_node(conn, "owner", "deepseek", "shared", "Claim", "Pending")
    event = graph.list_audit_events(conn, "owner")[0]
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE principal_knowledge_audit SET actor='forged' WHERE id=?", (event["id"],))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM principal_knowledge_audit WHERE id=?", (event["id"],))
    conn.execute("DROP TRIGGER principal_knowledge_audit_no_update")
    conn.execute("UPDATE principal_knowledge_audit SET actor='forged' WHERE id=?", (event["id"],))
    result = graph.verify_audit_chain(conn, "owner")
    assert result["valid"] is False
    assert result["invalid_sequence"] == event["sequence"]


def test_disputed_decision_is_audited_with_previous_status():
    conn = connection()
    node = graph.create_node(conn, "owner", "claude", "shared", "Claim", "Conflicting sources")
    graph.verify_node(conn, "owner", "owner", node["id"], False, "Sources disagree.")
    events = graph.list_audit_events(conn, "owner")
    assert events[0]["event_type"] == "knowledge.disputed"
    assert events[0]["details"]["previous_status"] == "unverified"
    assert events[0]["details"]["status"] == "disputed"
    assert graph.verify_audit_chain(conn, "owner")["valid"] is True
