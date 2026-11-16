"""Authenticated, allowlisted job queue for a ChatGPT-to-Termux bridge.

This module never executes shell commands. A separate local Termux worker polls
jobs and maps the small action allowlist to fixed subprocess argument vectors.
"""
from __future__ import annotations

import hmac
import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/termux-bridge", tags=["Termux Bridge"])

ALLOWED_ACTIONS = {
    "git_status",
    "git_pull_ff_only",
    "run_tests",
    "compile_check",
    "health_audit",
    "operational_readiness",
    "live_preflight",
    "offline_video_e2e",
    "full_self_test",
}
MAX_OUTPUT_CHARS = 20000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db_path() -> Path:
    configured = os.getenv("SINTU_BRIDGE_DB_PATH", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    data_dir = Path(os.getenv("SINTU_DATA_DIR", str(Path(__file__).resolve().parent.parent))).expanduser()
    return data_dir.resolve() / "sintu_termux_bridge.sqlite3"


@contextmanager
def _connect():
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bridge_jobs (
            id TEXT PRIMARY KEY,
            action TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            exit_code INTEGER,
            output TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bridge_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    conn.commit()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _authorize(authorization: str | None, *, worker: bool = False) -> None:
    secret_name = "SINTU_BRIDGE_WORKER_TOKEN" if worker else "SINTU_BRIDGE_TOKEN"
    expected = os.getenv(secret_name, "").strip()
    if len(expected) < 32:
        raise HTTPException(status_code=503, detail=f"Termux bridge credential {secret_name} is not configured. Configure a random secret of at least 32 characters.")
    supplied = ""
    if authorization and authorization.startswith("Bearer "):
        supplied = authorization[7:].strip()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid bridge credentials.")


class CreateJobInput(BaseModel):
    action: Literal["git_status", "git_pull_ff_only", "run_tests", "compile_check", "health_audit", "operational_readiness", "live_preflight", "offline_video_e2e", "full_self_test"]
    test_path: str | None = Field(default=None, max_length=160)
    topic: str | None = Field(default=None, max_length=300)


class CompleteJobInput(BaseModel):
    status: Literal["succeeded", "failed"]
    exit_code: int = Field(ge=-1, le=255)
    output: str = Field(default="", max_length=MAX_OUTPUT_CHARS)


@router.get("/status")
def bridge_status(authorization: str | None = Header(default=None)):
    _authorize(authorization)
    with _connect() as conn:
        counts = {row["status"]: row["count"] for row in conn.execute(
            "SELECT status, COUNT(*) AS count FROM bridge_jobs GROUP BY status"
        )}
        row = conn.execute("SELECT value FROM bridge_meta WHERE key='worker_last_seen'").fetchone()
    last_seen = row["value"] if row else None
    worker_online = False
    if last_seen:
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(last_seen)).total_seconds()
            worker_online = 0 <= age <= 30
        except ValueError:
            worker_online = False
    return {
        "enabled": True,
        "worker_online": worker_online,
        "worker_last_seen": last_seen,
        "jobs": {key: counts.get(key, 0) for key in ("queued", "running", "succeeded", "failed")},
        "allowed_actions": sorted(ALLOWED_ACTIONS),
        "arbitrary_shell": False,
    }


@router.post("/jobs", status_code=202)
def create_job(payload: CreateJobInput, authorization: str | None = Header(default=None)):
    _authorize(authorization)
    data = {}
    if payload.action == "run_tests" and payload.test_path:
        candidate = Path(payload.test_path)
        if (candidate.is_absolute() or ".." in candidate.parts
                or len(candidate.parts) != 2 or candidate.parts[0] != "tests"
                or candidate.suffix != ".py"):
            raise HTTPException(status_code=400, detail="test_path must be a single Python file directly inside tests/.")
        data["test_path"] = payload.test_path
    elif payload.test_path:
        raise HTTPException(status_code=400, detail="test_path is only valid for run_tests.")
    if payload.action in {"offline_video_e2e", "full_self_test"}:
        if payload.topic is not None:
            topic = payload.topic.strip()
            if not topic or len(topic) > 300:
                raise HTTPException(status_code=400, detail="topic must contain 1 to 300 characters.")
            data["topic"] = topic
    elif payload.topic is not None:
        raise HTTPException(status_code=400, detail="topic is only valid for offline_video_e2e or full_self_test.")
    job_id = secrets.token_hex(16)
    with _connect() as conn:
        conn.execute(
            "INSERT INTO bridge_jobs(id,action,payload_json,status,created_at) VALUES(?,?,?,?,?)",
            (job_id, payload.action, json.dumps(data), "queued", _now()),
        )
    return {"job_id": job_id, "action": payload.action, "status": "queued"}


@router.get("/jobs/next")
def claim_next_job(authorization: str | None = Header(default=None)):
    _authorize(authorization, worker=True)
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO bridge_meta(key,value) VALUES('worker_last_seen',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (_now(),)
        )
        # Recover jobs abandoned by a crashed worker. The worker command timeout
        # is 30 minutes; a 35-minute lease avoids reclaiming a healthy long run.
        stale_before = (datetime.now(timezone.utc) - timedelta(minutes=35)).isoformat()
        conn.execute(
            "UPDATE bridge_jobs SET status='queued',started_at=NULL "
            "WHERE status='running' AND started_at < ?",
            (stale_before,),
        )
        row = conn.execute(
            "SELECT id,action,payload_json FROM bridge_jobs WHERE status='queued' ORDER BY created_at,id LIMIT 1"
        ).fetchone()
        if not row:
            conn.commit()
            from fastapi import Response
            return Response(status_code=204)
        started = _now()
        changed = conn.execute(
            "UPDATE bridge_jobs SET status='running',started_at=? WHERE id=? AND status='queued'",
            (started, row["id"]),
        ).rowcount
        conn.commit()
    if not changed:
        from fastapi import Response
        return Response(status_code=204)
    return {
        "job_id": row["id"],
        "action": row["action"],
        "payload": json.loads(row["payload_json"]),
        "status": "running",
    }


@router.post("/jobs/{job_id}/complete")
def complete_job(job_id: str, payload: CompleteJobInput, authorization: str | None = Header(default=None)):
    _authorize(authorization, worker=True)
    if len(job_id) != 32 or any(ch not in "0123456789abcdef" for ch in job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID.")
    with _connect() as conn:
        changed = conn.execute(
            "UPDATE bridge_jobs SET status=?,finished_at=?,exit_code=?,output=? "
            "WHERE id=? AND status='running'",
            (payload.status, _now(), payload.exit_code, payload.output[-MAX_OUTPUT_CHARS:], job_id),
        ).rowcount
        if not changed:
            exists = conn.execute("SELECT status FROM bridge_jobs WHERE id=?", (job_id,)).fetchone()
            if not exists:
                raise HTTPException(status_code=404, detail="Bridge job not found.")
            raise HTTPException(status_code=409, detail="Only a running job can be completed.")
    return {"job_id": job_id, "status": payload.status, "exit_code": payload.exit_code}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, authorization: str | None = Header(default=None)):
    _authorize(authorization)
    if len(job_id) != 32 or any(ch not in "0123456789abcdef" for ch in job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID.")
    with _connect() as conn:
        row = conn.execute(
            "SELECT id,action,payload_json,status,created_at,started_at,finished_at,exit_code,output "
            "FROM bridge_jobs WHERE id=?", (job_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Bridge job not found.")
    result = dict(row)
    result["payload"] = json.loads(result.pop("payload_json"))
    return result
