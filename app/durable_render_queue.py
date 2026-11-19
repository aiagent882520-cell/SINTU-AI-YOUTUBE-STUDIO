"""Durable SQLite leases for SINTU render jobs.

Claims are serialized with BEGIN IMMEDIATE. Lease tokens fence stale workers:
a worker whose lease expired/reassigned cannot heartbeat or publish a result.
"""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _db_path() -> Path:
    return Path(os.getenv("SINTU_DATA_DIR", str(ROOT))).expanduser().resolve() / "sintu_studio.db"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(value: datetime | None = None) -> str:
    return (value or _now()).isoformat(timespec="microseconds")


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def ensure_schema() -> None:
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS studio_render_queue (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, project_id TEXT NOT NULL,
                status TEXT NOT NULL, payload_json TEXT NOT NULL, result_json TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )
        """)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(studio_render_queue)")}
        migrations = {
            "lease_owner": "TEXT",
            "lease_token": "TEXT",
            "lease_expires_at": "TEXT",
            "heartbeat_at": "TEXT",
            "available_at": "TEXT",
            "attempts": "INTEGER NOT NULL DEFAULT 0",
            "max_attempts": "INTEGER NOT NULL DEFAULT 4",
            "last_error": "TEXT",
        }
        for name, declaration in migrations.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE studio_render_queue ADD COLUMN {name} {declaration}")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_render_queue_claim ON studio_render_queue(status, available_at, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_render_queue_lease ON studio_render_queue(status, lease_expires_at)")


def _decode(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    item = dict(row)
    item["payload"] = json.loads(item.pop("payload_json"))
    encoded = item.pop("result_json", None)
    item["result"] = json.loads(encoded) if encoded else None
    return item


def enqueue(owner: str, project_id: str, payload: dict, *, max_attempts: int = 4) -> dict:
    ensure_schema()
    if not owner or not project_id or not isinstance(payload, dict):
        raise ValueError("owner, project_id and object payload are required")
    if not 1 <= int(max_attempts) <= 20:
        raise ValueError("max_attempts must be between 1 and 20")
    import uuid
    item_id, now = uuid.uuid4().hex, _stamp()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO studio_render_queue
               (id,owner,project_id,status,payload_json,created_at,updated_at,
                available_at,max_attempts,attempts)
               VALUES(?,?,?,'queued',?,?,?,?,?,0)""",
            (item_id, owner, project_id, json.dumps(payload, ensure_ascii=False), now, now, now, max_attempts),
        )
        row = conn.execute("SELECT * FROM studio_render_queue WHERE id=?", (item_id,)).fetchone()
    return _decode(row)


def recover_expired_leases(*, now: datetime | None = None) -> dict:
    """Requeue expired work or dead-letter jobs whose retry budget is exhausted."""
    ensure_schema()
    current = _stamp(now)
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        dead = conn.execute(
            """UPDATE studio_render_queue
               SET status='dead_letter',last_error=COALESCE(last_error,'Worker lease expired; retry budget exhausted.'),
                   lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,heartbeat_at=NULL,updated_at=?
               WHERE status='running' AND lease_expires_at IS NOT NULL AND lease_expires_at<=?
                 AND attempts>=max_attempts""", (current, current)
        ).rowcount
        queued = conn.execute(
            """UPDATE studio_render_queue
               SET status='queued',available_at=?,last_error=COALESCE(last_error,'Worker lease expired; job recovered.'),
                   lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,heartbeat_at=NULL,updated_at=?
               WHERE status='running' AND lease_expires_at IS NOT NULL AND lease_expires_at<=?
                 AND attempts<max_attempts""", (current, current, current)
        ).rowcount
    return {"requeued": queued, "dead_lettered": dead}


def claim_next(worker_id: str, *, lease_seconds: int = 900, owner: str | None = None) -> dict | None:
    ensure_schema()
    if not worker_id or len(worker_id) > 200 or not 15 <= int(lease_seconds) <= 86400:
        raise ValueError("worker_id or lease_seconds is invalid")
    now = _now()
    now_s, expiry = _stamp(now), _stamp(now + timedelta(seconds=lease_seconds))
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        # Reclaim expired leases inside the same write transaction as claiming.
        conn.execute(
            """UPDATE studio_render_queue SET status=CASE WHEN attempts>=max_attempts THEN 'dead_letter' ELSE 'queued' END,
               available_at=?,last_error=COALESCE(last_error,'Worker lease expired; job recovered.'),
               lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,heartbeat_at=NULL,updated_at=?
               WHERE status='running' AND lease_expires_at IS NOT NULL AND lease_expires_at<=?""",
            (now_s, now_s, now_s),
        )
        sql = "SELECT id FROM studio_render_queue WHERE status='queued' AND COALESCE(available_at,created_at)<=?"
        args: list = [now_s]
        if owner is not None:
            sql += " AND owner=?"
            args.append(owner)
        sql += " ORDER BY created_at,id LIMIT 1"
        selected = conn.execute(sql, args).fetchone()
        if selected is None:
            return None
        token = secrets.token_urlsafe(32)
        changed = conn.execute(
            """UPDATE studio_render_queue SET status='running',lease_owner=?,lease_token=?,
               lease_expires_at=?,heartbeat_at=?,attempts=attempts+1,updated_at=?
               WHERE id=? AND status='queued'""",
            (worker_id, token, expiry, now_s, now_s, selected["id"]),
        )
        if changed.rowcount != 1:
            return None
        row = conn.execute("SELECT * FROM studio_render_queue WHERE id=?", (selected["id"],)).fetchone()
    item = _decode(row)
    item["lease_token"] = token
    return item


def claim_item(owner: str, item_id: str, worker_id: str, *, lease_seconds: int = 1800) -> dict | None:
    ensure_schema()
    if not 15 <= int(lease_seconds) <= 86400:
        raise ValueError("lease_seconds is invalid")
    now = _now()
    now_s, expiry = _stamp(now), _stamp(now + timedelta(seconds=lease_seconds))
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """UPDATE studio_render_queue SET status=CASE WHEN attempts>=max_attempts THEN 'dead_letter' ELSE 'queued' END,
               available_at=?,lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,heartbeat_at=NULL,updated_at=?
               WHERE status='running' AND lease_expires_at IS NOT NULL AND lease_expires_at<=?""",
            (now_s, now_s, now_s),
        )
        token = secrets.token_urlsafe(32)
        changed = conn.execute(
            """UPDATE studio_render_queue SET status='running',lease_owner=?,lease_token=?,
               lease_expires_at=?,heartbeat_at=?,attempts=attempts+1,updated_at=?
               WHERE id=? AND owner=? AND status='queued' AND COALESCE(available_at,created_at)<=?""",
            (worker_id, token, expiry, now_s, now_s, item_id, owner, now_s),
        )
        if changed.rowcount != 1:
            return None
        row = conn.execute("SELECT * FROM studio_render_queue WHERE id=?", (item_id,)).fetchone()
    item = _decode(row)
    item["lease_token"] = token
    return item


def heartbeat(item_id: str, lease_token: str, *, lease_seconds: int = 1800) -> bool:
    ensure_schema()
    now = _now()
    with _connect() as conn:
        changed = conn.execute(
            """UPDATE studio_render_queue SET heartbeat_at=?,lease_expires_at=?,updated_at=?
               WHERE id=? AND status='running' AND lease_token=? AND lease_expires_at>?""",
            (_stamp(now), _stamp(now + timedelta(seconds=lease_seconds)), _stamp(now), item_id, lease_token, _stamp(now)),
        )
    return changed.rowcount == 1


def complete(item_id: str, lease_token: str, result: dict) -> bool:
    ensure_schema()
    now = _stamp()
    with _connect() as conn:
        changed = conn.execute(
            """UPDATE studio_render_queue SET status='completed',result_json=?,last_error=NULL,
               lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,heartbeat_at=NULL,updated_at=?
               WHERE id=? AND status='running' AND lease_token=? AND lease_expires_at>?""",
            (json.dumps(result, ensure_ascii=False), now, item_id, lease_token, now),
        )
    return changed.rowcount == 1


def fail(item_id: str, lease_token: str, error: str, *, retry_base_seconds: int = 15) -> str | None:
    ensure_schema()
    now_dt, now = _now(), _stamp()
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT attempts,max_attempts FROM studio_render_queue WHERE id=? AND status='running' AND lease_token=? AND lease_expires_at>?",
            (item_id, lease_token, now),
        ).fetchone()
        if row is None:
            return None
        retry = row["attempts"] < row["max_attempts"]
        delay = min(3600, max(1, retry_base_seconds) * (2 ** max(0, row["attempts"] - 1)))
        status = "queued" if retry else "dead_letter"
        available = _stamp(now_dt + timedelta(seconds=delay)) if retry else now
        conn.execute(
            """UPDATE studio_render_queue SET status=?,available_at=?,last_error=?,
               lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,heartbeat_at=NULL,updated_at=?
               WHERE id=? AND lease_token=?""",
            (status, available, str(error)[:2000], now, item_id, lease_token),
        )
    return status


def get_item(owner: str, item_id: str) -> dict | None:
    ensure_schema()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM studio_render_queue WHERE id=? AND owner=?", (item_id, owner)).fetchone()
    return _decode(row)
