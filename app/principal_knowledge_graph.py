"""Owner-governed, provenance-aware knowledge graphs for SINTU Principal AIs.

Private nodes are scoped to one Principal. Shared nodes are readable by the Council
but remain unverified until an Owner explicitly verifies them. This module stores
knowledge only; it never executes instructions or changes project configuration.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import secrets

PRINCIPAL_IDS = {"chatgpt", "gemini", "claude", "deepseek"}
SCOPES = {"private", "shared"}
STATUSES = {"unverified", "verified", "disputed", "superseded"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_schema(conn) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS principal_knowledge_nodes (
        id TEXT PRIMARY KEY,
        owner_username TEXT NOT NULL,
        scope TEXT NOT NULL CHECK(scope IN ('private','shared')),
        principal_id TEXT NOT NULL,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT 'general',
        status TEXT NOT NULL DEFAULT 'unverified'
            CHECK(status IN ('unverified','verified','disputed','superseded')),
        source_refs_json TEXT NOT NULL DEFAULT '[]',
        verification_note TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        verified_at TEXT,
        verified_by TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_principal_knowledge_owner_scope
        ON principal_knowledge_nodes(owner_username, scope, status, updated_at DESC);
    CREATE TABLE IF NOT EXISTS principal_knowledge_edges (
        id TEXT PRIMARY KEY,
        owner_username TEXT NOT NULL,
        from_node_id TEXT NOT NULL,
        to_node_id TEXT NOT NULL,
        relation TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(owner_username, from_node_id, to_node_id, relation)
    );
    CREATE INDEX IF NOT EXISTS idx_principal_knowledge_edges_owner
        ON principal_knowledge_edges(owner_username, from_node_id, to_node_id);
    """)


def create_node(conn, owner: str, principal_id: str, scope: str, title: str,
                content: str, category: str = "general", source_refs=None) -> dict:
    if principal_id not in PRINCIPAL_IDS:
        raise ValueError("Unknown Principal AI.")
    if scope not in SCOPES:
        raise ValueError("Knowledge scope must be private or shared.")
    title, content, category = str(title).strip(), str(content).strip(), str(category).strip()
    if not title or len(title) > 180 or not content or len(content) > 12000:
        raise ValueError("Knowledge title/content is empty or exceeds its size limit.")
    refs = source_refs if source_refs is not None else []
    if not isinstance(refs, list) or len(refs) > 30 or any(not isinstance(x, str) or len(x) > 1000 for x in refs):
        raise ValueError("Source references must be a list of at most 30 strings.")
    now, node_id = _now(), secrets.token_urlsafe(18)
    conn.execute("""INSERT INTO principal_knowledge_nodes
        (id,owner_username,scope,principal_id,title,content,category,status,
         source_refs_json,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,'unverified',?,?,?)""",
        (node_id, owner, scope, principal_id, title, content, category[:80],
         json.dumps(refs, ensure_ascii=False), now, now))
    return get_node(conn, owner, node_id)


def get_node(conn, owner: str, node_id: str):
    row = conn.execute(
        "SELECT * FROM principal_knowledge_nodes WHERE owner_username=? AND id=?",
        (owner, node_id)).fetchone()
    return _serialize(row) if row else None


def _serialize(row):
    item = dict(row)
    item["source_refs"] = json.loads(item.pop("source_refs_json"))
    return item


def list_nodes(conn, owner: str, scope: str | None = None,
               principal_id: str | None = None, status: str | None = None,
               limit: int = 100) -> list[dict]:
    if scope is not None and scope not in SCOPES:
        raise ValueError("Invalid knowledge scope.")
    if principal_id is not None and principal_id not in PRINCIPAL_IDS:
        raise ValueError("Unknown Principal AI.")
    if status is not None and status not in STATUSES:
        raise ValueError("Invalid knowledge status.")
    clauses, params = ["owner_username=?"], [owner]
    for column, value in (("scope", scope), ("principal_id", principal_id), ("status", status)):
        if value is not None:
            clauses.append(column + "=?")
            params.append(value)
    params.append(max(1, min(int(limit), 200)))
    rows = conn.execute(
        "SELECT * FROM principal_knowledge_nodes WHERE " + " AND ".join(clauses)
        + " ORDER BY updated_at DESC LIMIT ?", params).fetchall()
    return [_serialize(row) for row in rows]


def verify_node(conn, owner: str, actor: str, node_id: str,
                approved: bool, note: str = ""):
    row = conn.execute(
        "SELECT * FROM principal_knowledge_nodes WHERE owner_username=? AND id=?",
        (owner, node_id)).fetchone()
    if not row:
        return None
    if not approved:
        conn.execute("""UPDATE principal_knowledge_nodes SET status='disputed',
            verification_note=?, updated_at=?, verified_at=NULL, verified_by=NULL
            WHERE owner_username=? AND id=?""",
            (str(note)[:2000], _now(), owner, node_id))
    else:
        if not str(note).strip():
            raise ValueError("Owner verification requires a non-empty evidence/review note.")
        conn.execute("""UPDATE principal_knowledge_nodes SET status='verified',
            verification_note=?, updated_at=?, verified_at=?, verified_by=?
            WHERE owner_username=? AND id=?""",
            (str(note)[:2000], _now(), _now(), actor, owner, node_id))
    return get_node(conn, owner, node_id)


def link_nodes(conn, owner: str, from_id: str, to_id: str, relation: str) -> dict:
    relation = str(relation).strip()
    if not relation or len(relation) > 80 or from_id == to_id:
        raise ValueError("Invalid knowledge relationship.")
    left, right = get_node(conn, owner, from_id), get_node(conn, owner, to_id)
    if not left or not right:
        raise ValueError("Both knowledge nodes must exist under this Owner.")
    edge_id = secrets.token_urlsafe(18)
    conn.execute("""INSERT OR IGNORE INTO principal_knowledge_edges
        (id,owner_username,from_node_id,to_node_id,relation,created_at)
        VALUES(?,?,?,?,?,?)""", (edge_id, owner, from_id, to_id, relation, _now()))
    row = conn.execute("""SELECT * FROM principal_knowledge_edges
        WHERE owner_username=? AND from_node_id=? AND to_node_id=? AND relation=?""",
        (owner, from_id, to_id, relation)).fetchone()
    return dict(row)


def list_edges(conn, owner: str, node_id: str | None = None) -> list[dict]:
    if node_id:
        rows = conn.execute("""SELECT * FROM principal_knowledge_edges
            WHERE owner_username=? AND (from_node_id=? OR to_node_id=?)
            ORDER BY created_at DESC""", (owner, node_id, node_id)).fetchall()
    else:
        rows = conn.execute("""SELECT * FROM principal_knowledge_edges
            WHERE owner_username=? ORDER BY created_at DESC LIMIT 500""", (owner,)).fetchall()
    return [dict(row) for row in rows]
