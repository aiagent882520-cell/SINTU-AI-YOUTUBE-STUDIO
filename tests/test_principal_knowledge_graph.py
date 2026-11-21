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
