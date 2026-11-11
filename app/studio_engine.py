"""Persistent, local-first production runs with worker/checker gates."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .studio_scope import get_format, production_plan

ROOT = Path(__file__).resolve().parent.parent

def _now():
    return datetime.now(timezone.utc).isoformat()

def _db():
    data_dir = Path(os.getenv("SINTU_DATA_DIR", str(ROOT))).expanduser().resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(data_dir / "sintu_studio.db")
    conn.row_factory = sqlite3.Row
    return conn

def ensure_schema():
    with _db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS studio_runs (
          id TEXT PRIMARY KEY, owner TEXT NOT NULL, project_id TEXT NOT NULL,
          format_id TEXT NOT NULL, status TEXT NOT NULL, current_task_id TEXT,
          plan_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_studio_runs_owner ON studio_runs(owner, updated_at DESC);
        CREATE TABLE IF NOT EXISTS studio_run_tasks (
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL, task_order INTEGER NOT NULL,
          stage_id TEXT NOT NULL, stage_name TEXT NOT NULL, specialist TEXT NOT NULL,
          checker TEXT NOT NULL, status TEXT NOT NULL, worker_output TEXT,
          checker_decision TEXT, checker_evidence TEXT, checker_issues TEXT,
          revision_count INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          UNIQUE(run_id, task_order)
        );
        CREATE INDEX IF NOT EXISTS idx_studio_tasks_run ON studio_run_tasks(run_id, task_order);
        CREATE TABLE IF NOT EXISTS studio_assets (
          id TEXT PRIMARY KEY, owner TEXT NOT NULL, project_id TEXT NOT NULL,
          kind TEXT NOT NULL, name TEXT NOT NULL, uri TEXT NOT NULL DEFAULT '',
          metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_studio_assets_project ON studio_assets(owner, project_id, created_at DESC);
        CREATE TABLE IF NOT EXISTS studio_memory (
          id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL, project_id TEXT NOT NULL,
          memory_key TEXT NOT NULL, memory_value TEXT NOT NULL, updated_at TEXT NOT NULL,
          UNIQUE(owner, project_id, memory_key)
        );
        CREATE TABLE IF NOT EXISTS studio_versions (
          id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL, project_id TEXT NOT NULL,
          version_number INTEGER NOT NULL, snapshot_json TEXT NOT NULL, created_at TEXT NOT NULL,
          UNIQUE(owner, project_id, version_number)
        );
        CREATE TABLE IF NOT EXISTS studio_render_queue (
          id TEXT PRIMARY KEY, owner TEXT NOT NULL, project_id TEXT NOT NULL,
          status TEXT NOT NULL, payload_json TEXT NOT NULL, result_json TEXT,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_studio_render_queue ON studio_render_queue(owner, status, created_at);
        """)

def _row(row):
    return dict(row) if row else None

def create_run(owner: str, project_id: str, format_id: str):
    ensure_schema()
    if not get_format(format_id):
        raise KeyError("Unknown video format.")
    plan = production_plan(format_id)
    tasks = []
    for stage in plan["pipeline"]:
        for pair in stage["worker_checker_pairs"]:
            tasks.append({
                "stage_id": stage["stage"], "stage_name": stage["name"],
                "specialist": pair["worker"], "checker": pair["checker"]
            })
    if not tasks:
        raise ValueError("The selected format has no production roles.")
    run_id = uuid.uuid4().hex
    now = _now()
    with _db() as conn:
        conn.execute(
            "INSERT INTO studio_runs(id,owner,project_id,format_id,status,plan_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (run_id, owner, project_id, format_id, "queued", json.dumps(plan, ensure_ascii=False), now, now)
        )
        for index, task in enumerate(tasks):
            conn.execute("""
              INSERT INTO studio_run_tasks(id,run_id,task_order,stage_id,stage_name,specialist,checker,status,created_at,updated_at)
              VALUES(?,?,?,?,?,?,?,?,?,?)
            """, (uuid.uuid4().hex, run_id, index + 1, task["stage_id"], task["stage_name"],
                  task["specialist"], task["checker"], "pending" if index == 0 else "blocked", now, now))
        first = conn.execute("SELECT id FROM studio_run_tasks WHERE run_id=? ORDER BY task_order LIMIT 1", (run_id,)).fetchone()
        conn.execute("UPDATE studio_runs SET current_task_id=? WHERE id=?", (first["id"], run_id))
    return get_run(owner, run_id)

def get_run(owner: str, run_id: str):
    ensure_schema()
    with _db() as conn:
        run = conn.execute("SELECT * FROM studio_runs WHERE id=? AND owner=?", (run_id, owner)).fetchone()
        if not run:
            return None
        tasks = conn.execute("SELECT * FROM studio_run_tasks WHERE run_id=? ORDER BY task_order", (run_id,)).fetchall()
    result = dict(run)
    result["plan"] = json.loads(result.pop("plan_json"))
    result["tasks"] = [dict(task) for task in tasks]
    result["progress"] = {
        "total": len(tasks),
        "approved": sum(1 for task in tasks if task["status"] == "approved"),
        "failed": sum(1 for task in tasks if task["status"] == "needs_revision"),
        "pending": sum(1 for task in tasks if task["status"] in {"pending", "blocked", "waiting_checker"})
    }
    return result

def list_runs(owner: str, limit: int = 50):
    ensure_schema()
    with _db() as conn:
        rows = conn.execute("SELECT id FROM studio_runs WHERE owner=? ORDER BY updated_at DESC LIMIT ?", (owner, limit)).fetchall()
    return [get_run(owner, row["id"]) for row in rows]

def _owned_task(conn, owner, run_id, task_id):
    run = conn.execute("SELECT * FROM studio_runs WHERE id=? AND owner=?", (run_id, owner)).fetchone()
    task = conn.execute("SELECT * FROM studio_run_tasks WHERE id=? AND run_id=?", (task_id, run_id)).fetchone()
    if not run or not task:
        return None, None
    return run, task

def submit_worker_output(owner: str, run_id: str, task_id: str, output: str):
    ensure_schema()
    output = output.strip()
    if not output or len(output) > 50000:
        raise ValueError("Worker output must contain 1–50000 characters.")
    now = _now()
    with _db() as conn:
        run, task = _owned_task(conn, owner, run_id, task_id)
        if not task:
            return None
        if task["status"] not in {"pending", "needs_revision"} or run["current_task_id"] != task_id:
            raise ValueError("This worker task is blocked or is not awaiting a submission.")
        conn.execute("UPDATE studio_run_tasks SET worker_output=?,status='waiting_checker',checker_decision=NULL,checker_evidence=NULL,checker_issues=NULL,updated_at=? WHERE id=?",
                     (output, now, task_id))
        conn.execute("UPDATE studio_runs SET status='in_progress',updated_at=? WHERE id=?", (now, run_id))
    return get_run(owner, run_id)

def submit_checker_result(owner: str, run_id: str, task_id: str, decision: str, evidence: str, issues: str = ""):
    ensure_schema()
    decision = decision.strip().upper()
    evidence, issues = evidence.strip(), issues.strip()
    if decision not in {"PASS", "FAIL"}:
        raise ValueError("Checker decision must be PASS or FAIL.")
    if not evidence or len(evidence) > 12000 or len(issues) > 12000:
        raise ValueError("Checker evidence is required and must be under 12000 characters.")
    if decision == "FAIL" and not issues:
        raise ValueError("A FAIL decision must include revision instructions.")
    now = _now()
    with _db() as conn:
        run, task = _owned_task(conn, owner, run_id, task_id)
        if not task:
            return None
        if task["status"] != "waiting_checker":
            raise ValueError("The independent checker can only review a submitted worker output.")
        next_status = "approved" if decision == "PASS" else "needs_revision"
        conn.execute("""
          UPDATE studio_run_tasks SET status=?,checker_decision=?,checker_evidence=?,checker_issues=?,revision_count=revision_count+?,updated_at=?
          WHERE id=?
        """, (next_status, decision, evidence, issues, 0 if decision == "PASS" else 1, now, task_id))
        if decision == "PASS":
            next_task = conn.execute("SELECT id FROM studio_run_tasks WHERE run_id=? AND task_order>? ORDER BY task_order LIMIT 1",
                                     (run_id, task["task_order"])).fetchone()
            if next_task:
                conn.execute("UPDATE studio_run_tasks SET status='pending',updated_at=? WHERE id=? AND status='blocked'", (now, next_task["id"]))
                conn.execute("UPDATE studio_runs SET current_task_id=?,status='in_progress',updated_at=? WHERE id=?",
                             (next_task["id"], now, run_id))
            else:
                conn.execute("UPDATE studio_runs SET current_task_id=NULL,status='awaiting_human_approval',updated_at=? WHERE id=?", (now, run_id))
        else:
            conn.execute("UPDATE studio_runs SET status='revision_required',updated_at=? WHERE id=?", (now, run_id))
    return get_run(owner, run_id)

def revise_worker_output(owner: str, run_id: str, task_id: str, output: str):
    return submit_worker_output(owner, run_id, task_id, output)

def approve_run(owner: str, run_id: str, approved: bool, note: str = ""):
    ensure_schema()
    now = _now()
    with _db() as conn:
        run = conn.execute("SELECT * FROM studio_runs WHERE id=? AND owner=?", (run_id, owner)).fetchone()
        if not run:
            return None
        if run["status"] != "awaiting_human_approval":
            raise ValueError("Run must pass every independent checker before human approval.")
        status = "completed" if approved else "approval_rejected"
        conn.execute("UPDATE studio_runs SET status=?,updated_at=? WHERE id=?", (status, now, run_id))
    return get_run(owner, run_id)

def add_asset(owner, project_id, kind, name, uri="", metadata=None):
    ensure_schema()
    asset_id, now = uuid.uuid4().hex, _now()
    with _db() as conn:
        conn.execute("INSERT INTO studio_assets(id,owner,project_id,kind,name,uri,metadata_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
                     (asset_id, owner, project_id, kind, name.strip(), uri.strip(), json.dumps(metadata or {}, ensure_ascii=False), now))
    return {"id": asset_id, "owner": owner, "project_id": project_id, "kind": kind, "name": name.strip(),
            "uri": uri.strip(), "metadata": metadata or {}, "created_at": now}

def list_assets(owner, project_id):
    ensure_schema()
    with _db() as conn:
        rows = conn.execute("SELECT * FROM studio_assets WHERE owner=? AND project_id=? ORDER BY created_at DESC", (owner, project_id)).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["metadata"] = json.loads(item.pop("metadata_json"))
        result.append(item)
    return result

def set_memory(owner, project_id, key, value):
    ensure_schema()
    now = _now()
    with _db() as conn:
        conn.execute("""INSERT INTO studio_memory(owner,project_id,memory_key,memory_value,updated_at)
          VALUES(?,?,?,?,?) ON CONFLICT(owner,project_id,memory_key)
          DO UPDATE SET memory_value=excluded.memory_value,updated_at=excluded.updated_at""",
          (owner, project_id, key.strip(), value.strip(), now))
    return {"project_id": project_id, "key": key.strip(), "value": value.strip(), "updated_at": now}

def list_memory(owner, project_id):
    ensure_schema()
    with _db() as conn:
        rows = conn.execute("SELECT memory_key,memory_value,updated_at FROM studio_memory WHERE owner=? AND project_id=? ORDER BY memory_key", (owner, project_id)).fetchall()
    return [{"key": row["memory_key"], "value": row["memory_value"], "updated_at": row["updated_at"]} for row in rows]

def delete_memory(owner, project_id, key):
    ensure_schema()
    with _db() as conn:
        cur = conn.execute("DELETE FROM studio_memory WHERE owner=? AND project_id=? AND memory_key=?", (owner, project_id, key))
    return cur.rowcount > 0

def create_version(owner, project_id, snapshot):
    ensure_schema()
    now = _now()
    encoded = json.dumps(snapshot, ensure_ascii=False)
    with _db() as conn:
        latest = conn.execute("SELECT COALESCE(MAX(version_number),0) AS n FROM studio_versions WHERE owner=? AND project_id=?", (owner, project_id)).fetchone()["n"]
        version = latest + 1
        conn.execute("INSERT INTO studio_versions(owner,project_id,version_number,snapshot_json,created_at) VALUES(?,?,?,?,?)",
                     (owner, project_id, version, encoded, now))
    return {"project_id": project_id, "version": version, "snapshot": snapshot, "created_at": now}

def list_versions(owner, project_id):
    ensure_schema()
    with _db() as conn:
        rows = conn.execute("SELECT version_number,snapshot_json,created_at FROM studio_versions WHERE owner=? AND project_id=? ORDER BY version_number DESC", (owner, project_id)).fetchall()
    return [{"version": row["version_number"], "snapshot": json.loads(row["snapshot_json"]), "created_at": row["created_at"]} for row in rows]

def enqueue_render(owner, project_id, payload):
    ensure_schema()
    item_id, now = uuid.uuid4().hex, _now()
    with _db() as conn:
        conn.execute("INSERT INTO studio_render_queue(id,owner,project_id,status,payload_json,created_at,updated_at) VALUES(?,?,?,'queued',?,?,?)",
                     (item_id, owner, project_id, json.dumps(payload, ensure_ascii=False), now, now))
    return {"id": item_id, "owner": owner, "project_id": project_id, "status": "queued", "payload": payload, "created_at": now}

def list_render_queue(owner, project_id=None):
    ensure_schema()
    with _db() as conn:
        if project_id:
            rows = conn.execute("SELECT * FROM studio_render_queue WHERE owner=? AND project_id=? ORDER BY created_at DESC", (owner, project_id)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM studio_render_queue WHERE owner=? ORDER BY created_at DESC LIMIT 100", (owner,)).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json"))
        item["result"] = json.loads(item.pop("result_json")) if item["result_json"] else None
        result.append(item)
    return result


def delete_asset(owner, asset_id):
    ensure_schema()
    with _db() as conn:
        cur = conn.execute("DELETE FROM studio_assets WHERE owner=? AND id=?", (owner, asset_id))
    return cur.rowcount > 0

def update_render_item(owner, item_id, status, result=None):
    ensure_schema()
    if status not in {"running", "completed", "failed"}:
        raise ValueError("Render status must be running, completed, or failed.")
    now = _now()
    with _db() as conn:
        row = conn.execute("SELECT status FROM studio_render_queue WHERE id=? AND owner=?", (item_id, owner)).fetchone()
        if not row:
            return None
        allowed = {"queued":{"running"}, "running":{"completed","failed"}}
        if status not in allowed.get(row["status"], set()):
            raise ValueError("Invalid render queue status transition.")
        conn.execute("UPDATE studio_render_queue SET status=?,result_json=?,updated_at=? WHERE id=? AND owner=?",
                     (status, json.dumps(result, ensure_ascii=False) if result is not None else None, now, item_id, owner))
    return next((item for item in list_render_queue(owner) if item["id"] == item_id), None)
