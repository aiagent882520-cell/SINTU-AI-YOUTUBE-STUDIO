"""Owner-scoped durable storage for documentary research evidence packages."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def _connect(db_path: str | Path):
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _ensure_table(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS production_research_evidence (
        run_id TEXT PRIMARY KEY,
        owner_username TEXT NOT NULL,
        package_json TEXT NOT NULL,
        validation_json TEXT NOT NULL,
        package_sha256 TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_research_evidence_owner_updated "
        "ON production_research_evidence(owner_username, updated_at DESC)"
    )


def save_research_evidence(db_path, run_id, owner_username, package, validation):
    """Persist one immutable evidence ledger per production run, without replacing an existing one."""
    owner = str(owner_username or "").strip()
    if not owner or len(owner) > 120:
        raise ValueError("Research evidence owner is invalid.")
    if not isinstance(run_id, str) or not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise ValueError("Research evidence run ID is invalid.")
    if not isinstance(package, dict) or not isinstance(validation, dict) or validation.get("valid") is not True:
        raise ValueError("Only structurally valid documentary evidence can be persisted.")
    canonical = json.dumps(package, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if validation.get("sha256") != digest:
        raise ValueError("Research evidence validation digest does not match the package.")
    now = datetime.now(timezone.utc).isoformat()
    conn = _connect(db_path)
    try:
        _ensure_table(conn)
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """INSERT INTO production_research_evidence
               (run_id, owner_username, package_json, validation_json, package_sha256, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (run_id, owner, canonical, json.dumps(validation, ensure_ascii=False, sort_keys=True), digest, now, now),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_research_evidence(db_path, run_id, owner)


def get_research_evidence(db_path, run_id, owner_username):
    owner = str(owner_username or "").strip()
    if not owner or len(owner) > 120:
        return None
    conn = _connect(db_path)
    try:
        _ensure_table(conn)
        conn.commit()
        row = conn.execute(
            """SELECT package_json, validation_json, package_sha256, created_at, updated_at
               FROM production_research_evidence WHERE run_id=? AND owner_username=?""",
            (run_id, owner),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    package = json.loads(row["package_json"])
    validation = json.loads(row["validation_json"])
    canonical = json.dumps(package, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    actual_digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if actual_digest != row["package_sha256"] or validation.get("sha256") != actual_digest:
        raise ValueError("Persisted documentary research evidence integrity check failed.")
    return {
        "run_id": run_id,
        "package": package,
        "validation": validation,
        "sha256": actual_digest,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
