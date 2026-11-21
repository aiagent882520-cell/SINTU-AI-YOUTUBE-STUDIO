"""Persistent format-aware worker/checker production runtime.

Each specialist and checker is a separate model invocation. The runtime is local-first,
records every result, stops on failed quality gates, and never publishes automatically.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
import time
from pathlib import Path
from typing import Any

from .studio_scope import get_format, production_plan
from .agent_orchestrator import format_team
from .agents import AGENTS
from .management_hierarchy import SENIOR_MANAGER_NAMES, management_hierarchy
from .ai_brain import generate_text, ProviderNotConfigured, ProviderRequestError
from .documentary_research import DOCUMENTARY_FORMAT_IDS, validate_documentary_evidence_for_production, build_research_prompt_context
from .research_evidence_store import get_research_evidence

DATA_DIR = Path(os.getenv("SINTU_DATA_DIR", str(Path(__file__).resolve().parent.parent))).expanduser().resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "production_runtime.sqlite3"
RESEARCH_EVIDENCE_DB_PATH = DATA_DIR / "sintu_studio.db"
# Initial attempt plus at most two checker-guided revisions.
try:
    MAX_REVISION_ATTEMPTS = max(0, min(2, int(os.getenv('SINTU_MAX_REVISION_ATTEMPTS', '2'))))
except ValueError:
    MAX_REVISION_ATTEMPTS = 2
REVIEWERS = [
    "Video Quality Reviewer",
    "Audio Quality Reviewer",
    "Visual Consistency Reviewer",
    "Copyright & Originality Reviewer",
    "Final Approval Reviewer",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_runtime_db() -> None:
    with _connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS production_runs (
            id TEXT PRIMARY KEY, format_id TEXT NOT NULL, topic TEXT NOT NULL,
            status TEXT NOT NULL, current_role TEXT, result_json TEXT,
            error TEXT, owner_username TEXT NOT NULL DEFAULT 'local',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(production_runs)").fetchall()}
        if "owner_username" not in columns:
            conn.execute("ALTER TABLE production_runs ADD COLUMN owner_username TEXT NOT NULL DEFAULT 'local'")
        for column, definition in (
            ("cancel_requested", "INTEGER NOT NULL DEFAULT 0"),
            ("worker_token", "TEXT"),
            ("lease_expires_at", "TEXT"),
            ("attempt_count", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if column not in columns:
                conn.execute(f"ALTER TABLE production_runs ADD COLUMN {column} {definition}")
        conn.execute("""CREATE TABLE IF NOT EXISTS production_run_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            owner_username TEXT NOT NULL,
            from_status TEXT,
            to_status TEXT NOT NULL,
            event_type TEXT NOT NULL,
            details TEXT,
            created_at TEXT NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_production_run_events_owner ON production_run_events(run_id, owner_username, id)")
        conn.execute("""CREATE TABLE IF NOT EXISTS production_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
            sequence INTEGER NOT NULL, role TEXT NOT NULL, step_type TEXT NOT NULL,
            status TEXT NOT NULL, input_text TEXT, output_text TEXT,
            evidence_json TEXT, issues_json TEXT, attempts INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            FOREIGN KEY(run_id) REFERENCES production_runs(id)
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_production_steps_run ON production_steps(run_id, sequence)")


def _selected_format(format_id: str) -> dict[str, Any] | None:
    if format_id == "__agent_catalog__":
        return {
            "id": format_id,
            "name": "Complete 61 Specialists + 5 Senior Agents Validation",
            "aspect_ratio": "16:9",
            "recommended_resolution": "1920x1080",
            "roles": list(AGENTS),
        }
    return get_format(format_id)


def create_run(format_id: str, topic: str, owner_username: str = "local") -> dict[str, Any]:
    selected = _selected_format(format_id)
    if not selected:
        raise ValueError("Unknown video format.")
    topic = (topic or "").strip()
    owner_username = (owner_username or "").strip()
    if not owner_username or len(owner_username) > 120:
        raise ValueError("Production run owner is invalid.")
    if not topic or len(topic) > 5000:
        raise ValueError("Topic must contain 1 to 5000 characters.")
    init_runtime_db()
    run_id = uuid.uuid4().hex
    now = _now()
    with _connect() as conn:
        conn.execute("""INSERT INTO production_runs
            (id,format_id,topic,status,owner_username,created_at,updated_at) VALUES(?,?,?,?,?,?,?)""",
            (run_id, format_id, topic, "queued", owner_username, now, now))
        _event(conn, run_id, owner_username, None, "queued", "run_created", "Production run created.")
    return get_run(run_id, owner_username)



def list_runs(owner_username: str = "local", limit: int = 20) -> list[dict[str, Any]]:
    """Return recent production runs for the authenticated owner, newest first."""
    init_runtime_db()
    safe_limit = max(1, min(int(limit), 100))
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id FROM production_runs WHERE owner_username=? ORDER BY updated_at DESC LIMIT ?",
            (owner_username, safe_limit),
        ).fetchall()
    return [run for row in rows if (run := get_run(row["id"], owner_username)) is not None]



WORKER_LEASE_SECONDS = 900
MODEL_CALL_TIMEOUT_SECONDS = 300


class ProductionRunCancelled(Exception):
    """Raised when a worker loses ownership or its run is cancelled."""


class ProductionRunTimeout(Exception):
    """Raised when a model invocation exceeds the configured runtime budget."""


def _event(conn, run_id: str, owner: str, old_status: str | None,
           new_status: str, event_type: str, details: str | None = None) -> None:
    conn.execute(
        """INSERT INTO production_run_events
           (run_id,owner_username,from_status,to_status,event_type,details,created_at)
           VALUES(?,?,?,?,?,?,?)""",
        (run_id, owner, old_status, new_status, event_type, details, _now()),
    )


def _claim_run(run_id: str, owner_username: str | None = None) -> bool:
    """Atomically claim one queued/paused run and issue a fenced worker lease."""
    init_runtime_db()
    token = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    lease = (now + timedelta(seconds=WORKER_LEASE_SECONDS)).isoformat()
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        query = "SELECT status,owner_username FROM production_runs WHERE id=?"
        row = conn.execute(query, (run_id,)).fetchone()
        if not row or (owner_username is not None and row["owner_username"] != owner_username):
            return False
        if row["status"] not in {"queued", "paused"}:
            return False
        changed = conn.execute(
            """UPDATE production_runs SET status='running',current_role=NULL,error=NULL,
               worker_token=?,lease_expires_at=?,cancel_requested=0,
               attempt_count=attempt_count+1,updated_at=?
               WHERE id=? AND status IN ('queued','paused')""",
            (token, lease, _now(), run_id),
        ).rowcount
        if changed == 1:
            _event(conn, run_id, row["owner_username"], row["status"], "running",
                   "worker_claimed", "Atomic worker claim with fenced lease.")
    return changed == 1


def _worker_token(run_id: str, owner_username: str | None = None) -> str | None:
    with _connect() as conn:
        if owner_username is None:
            row = conn.execute("SELECT worker_token FROM production_runs WHERE id=?", (run_id,)).fetchone()
        else:
            row = conn.execute("SELECT worker_token FROM production_runs WHERE id=? AND owner_username=?",
                               (run_id, owner_username)).fetchone()
    return row["worker_token"] if row else None


def _renew_worker_lease(run_id: str, token: str) -> bool:
    lease = (datetime.now(timezone.utc) + __import__("datetime").timedelta(seconds=WORKER_LEASE_SECONDS)).isoformat()
    with _connect() as conn:
        changed = conn.execute(
            """UPDATE production_runs SET lease_expires_at=?,updated_at=?
               WHERE id=? AND worker_token=? AND cancel_requested=0
               AND status IN ('running','reviewing')""",
            (lease, _now(), run_id, token),
        ).rowcount
    return changed == 1


def _cancellation_requested(run_id: str, owner_username: str | None, token: str) -> bool:
    with _connect() as conn:
        if owner_username is None:
            row = conn.execute("SELECT status,cancel_requested,worker_token,lease_expires_at FROM production_runs WHERE id=?",
                               (run_id,)).fetchone()
        else:
            row = conn.execute("SELECT status,cancel_requested,worker_token,lease_expires_at FROM production_runs WHERE id=? AND owner_username=?",
                               (run_id, owner_username)).fetchone()
    return (not row or row["worker_token"] != token or bool(row["cancel_requested"])
            or row["status"] in {"cancelling", "cancelled"}
            or not row["lease_expires_at"] or row["lease_expires_at"] < _now())


def _finish_cancel(run_id: str, owner_username: str | None, token: str | None = None) -> bool:
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if token is None:
            row = conn.execute("SELECT status,owner_username FROM production_runs WHERE id=?",
                               (run_id,)).fetchone()
        else:
            row = conn.execute("SELECT status,owner_username FROM production_runs WHERE id=? AND worker_token=?",
                               (run_id, token)).fetchone()
        if not row or (owner_username is not None and row["owner_username"] != owner_username):
            return False
        changed = conn.execute(
            """UPDATE production_runs SET status='cancelled',cancel_requested=1,
               current_role=NULL,error='Cancelled by owner.',worker_token=NULL,
               lease_expires_at=NULL,updated_at=?
               WHERE id=? AND status IN ('cancelling','queued','paused')""",
            (_now(), run_id),
        ).rowcount
        if changed:
            _event(conn, run_id, row["owner_username"], row["status"], "cancelled",
                   "cancellation_completed", "Worker stopped at a safe checkpoint; partial outputs were preserved.")
    return changed == 1


def request_cancel(run_id: str, owner_username: str) -> dict[str, Any] | None:
    """Owner-scoped, idempotent cancellation request; running providers stop at safe boundaries."""
    init_runtime_db()
    terminal = False
    target = None
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT status,owner_username,cancel_requested FROM production_runs WHERE id=? AND owner_username=?",
                           (run_id, owner_username)).fetchone()
        if not row:
            return None
        status = row["status"]
        if status in {"completed", "failed", "blocked", "cancelled"}:
            terminal = True
        else:
            if status in {"queued", "paused"}:
                target = "cancelled"
                conn.execute(
                    """UPDATE production_runs SET status='cancelled',cancel_requested=1,
                       current_role=NULL,error='Cancelled by owner.',worker_token=NULL,
                       lease_expires_at=NULL,updated_at=? WHERE id=? AND owner_username=?""",
                    (_now(), run_id, owner_username),
                )
            else:
                target = "cancelling"
                conn.execute(
                    """UPDATE production_runs SET status='cancelling',cancel_requested=1,
                       error='Cancellation requested; waiting for the active worker safe point.',
                       updated_at=? WHERE id=? AND owner_username=? AND status IN ('running','reviewing','cancelling')""",
                    (_now(), run_id, owner_username),
                )
            if not row["cancel_requested"]:
                _event(conn, run_id, owner_username, status, target, "cancel_requested",
                       "Owner requested cancellation; no completed outputs are deleted.")
    if terminal:
        return get_run(run_id, owner_username)
    if target == "cancelled":
        _finish_cancel(run_id, owner_username)
    return get_run(run_id, owner_username)

def list_run_events(run_id: str, owner_username: str) -> list[dict[str, Any]] | None:
    init_runtime_db()
    with _connect() as conn:
        exists = conn.execute("SELECT 1 FROM production_runs WHERE id=? AND owner_username=?",
                              (run_id, owner_username)).fetchone()
        if not exists:
            return None
        rows = conn.execute(
            """SELECT from_status,to_status,event_type,details,created_at
               FROM production_run_events WHERE run_id=? AND owner_username=? ORDER BY id""",
            (run_id, owner_username),
        ).fetchall()
    return [dict(row) for row in rows]


def recover_stale_runs() -> int:
    """Fence expired workers and return their runs to a safe resumable/cancelled state."""
    init_runtime_db()
    now = _now()
    recovered = 0
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            """SELECT id,owner_username,status,cancel_requested FROM production_runs
               WHERE status IN ('running','reviewing') AND lease_expires_at IS NOT NULL
               AND lease_expires_at < ?""", (now,)
        ).fetchall()
        for row in rows:
            target = "cancelled" if row["cancel_requested"] else "paused"
            error = ("Cancellation completed after the worker lease expired."
                     if target == "cancelled" else
                     "Worker lease expired; run paused for safe checkpoint recovery.")
            changed = conn.execute(
                """UPDATE production_runs SET status=?,error=?,worker_token=NULL,
                   lease_expires_at=NULL,current_role=NULL,updated_at=?
                   WHERE id=? AND status IN ('running','reviewing') AND lease_expires_at < ?""",
                (target, error, now, row["id"], now),
            ).rowcount
            if changed:
                _event(conn, row["id"], row["owner_username"], row["status"], target,
                       "stale_worker_recovered", error)
                recovered += 1
    return recovered


def get_run(run_id: str, owner_username: str | None = None) -> dict[str, Any] | None:
    # Polling a run also acts as a bounded watchdog for expired worker leases.
    recover_stale_runs()
    init_runtime_db()
    with _connect() as conn:
        if owner_username is None:
            row = conn.execute("SELECT * FROM production_runs WHERE id=?", (run_id,)).fetchone()
        else:
            row = conn.execute("SELECT * FROM production_runs WHERE id=? AND owner_username=?",
                               (run_id, owner_username)).fetchone()
        if not row:
            return None
        steps = conn.execute("SELECT sequence,role,step_type,status,output_text,evidence_json,issues_json,attempts FROM production_steps WHERE run_id=? ORDER BY sequence", (run_id,)).fetchall()
    result = dict(row)
    result["result"] = json.loads(result.pop("result_json") or "null")
    result["steps"] = []
    for item in steps:
        step = dict(item)
        step["evidence"] = json.loads(step.pop("evidence_json") or "[]")
        step["issues"] = json.loads(step.pop("issues_json") or "[]")
        result["steps"].append(step)
    return result


def _set_run(run_id: str, status: str, current_role: str | None = None,
             error: str | None = None, result: dict | None = None,
             worker_token: str | None = None) -> bool:
    """Persist a state transition with an audit event and optional worker fencing."""
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT status,owner_username,worker_token,lease_expires_at FROM production_runs WHERE id=?",
                           (run_id,)).fetchone()
        if not row or row["status"] == "cancelled":
            return False
        if row["status"] == "cancelling" and status != "cancelled":
            return False
        if worker_token is not None and (
            row["worker_token"] != worker_token or not row["lease_expires_at"]
            or row["lease_expires_at"] < _now()
        ):
            return False
        terminal = status in {"completed", "failed", "blocked", "paused", "cancelled"}
        changed = conn.execute(
            """UPDATE production_runs SET status=?,current_role=?,error=?,
               result_json=COALESCE(?,result_json),worker_token=CASE WHEN ? THEN NULL ELSE worker_token END,
               lease_expires_at=CASE WHEN ? THEN NULL ELSE lease_expires_at END,updated_at=?
               WHERE id=?""",
            (status, current_role, error,
             json.dumps(result, ensure_ascii=False) if result is not None else None,
             int(terminal), int(terminal), _now(), run_id),
        ).rowcount
        if changed and row["status"] != status:
            _event(conn, run_id, row["owner_username"], row["status"], status,
                   "state_transition", error)
    return changed == 1


def _save_step(run_id: str, sequence: int, role: str, step_type: str,
               status: str, input_text: str, output_text: str = "",
               evidence: list | None = None, issues: list | None = None,
               attempts: int = 1, worker_token: str | None = None) -> None:
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if worker_token is not None:
            row = conn.execute(
                "SELECT worker_token,cancel_requested,status,lease_expires_at FROM production_runs WHERE id=?",
                (run_id,),
            ).fetchone()
            if (not row or row["worker_token"] != worker_token or row["cancel_requested"]
                    or row["status"] in {"cancelling","cancelled"} or not row["lease_expires_at"]
                    or row["lease_expires_at"] < _now()):
                raise ProductionRunCancelled("Worker ownership lost or cancellation requested.")
        conn.execute("""INSERT INTO production_steps
            (run_id,sequence,role,step_type,status,input_text,output_text,evidence_json,issues_json,attempts,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (run_id, sequence, role, step_type, status, input_text, output_text,
             json.dumps(evidence or [], ensure_ascii=False), json.dumps(issues or [], ensure_ascii=False),
             attempts, _now(), _now()))


def _approved_builder_output(steps: list[dict], role: str) -> str | None:
    """Return the latest builder output whose independent checker passed."""
    pending_output = None
    approved_output = None
    for step in sorted(steps, key=lambda item: item.get("sequence", 0)):
        if step.get("step_type") == "builder" and step.get("role") == role:
            pending_output = step.get("output_text") or ""
        elif step.get("step_type") == "checker" and step.get("role") == role + " Checker":
            approved_output = pending_output if step.get("status") == "pass" and pending_output else None
            pending_output = None
    return approved_output


def _approved_reviewer_report(steps: list[dict], reviewer: str) -> dict | None:
    """Rebuild a saved reviewer result only when its latest persisted verdict passed."""
    matches = [
        step for step in steps
        if step.get("step_type") == "reviewer" and step.get("role") == reviewer
    ]
    if not matches or matches[-1].get("status") != "pass":
        return None
    raw_output = matches[-1].get("output_text") or ""
    verdict = _review_payload(raw_output)
    if verdict["decision"] != "PASS":
        return None
    return {
        "decision": verdict["decision"],
        "evidence": verdict["evidence"],
        "issues": verdict["issues"],
        "revision_instructions": verdict["revision_instructions"],
        "raw_output": raw_output,
    }


def recover_interrupted_runs() -> int:
    """Recover active jobs after restart without reviving cancelled work."""
    init_runtime_db()
    now = _now()
    recovered = 0
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            "SELECT id,owner_username,status,cancel_requested FROM production_runs WHERE status IN ('running','reviewing','cancelling')"
        ).fetchall()
        for row in rows:
            target = "cancelled" if row["cancel_requested"] or row["status"] == "cancelling" else "paused"
            error = ("Cancellation completed during application restart."
                     if target == "cancelled" else
                     "Application restarted during production. Resume from the last independently approved checkpoint.")
            changed = conn.execute(
                """UPDATE production_runs SET status=?,error=?,worker_token=NULL,
                   lease_expires_at=NULL,current_role=NULL,updated_at=?
                   WHERE id=? AND status IN ('running','reviewing','cancelling')""",
                (target, error, now, row["id"]),
            ).rowcount
            if changed:
                _event(conn, row["id"], row["owner_username"], row["status"], target,
                       "restart_recovery", error)
                recovered += 1
    return recovered


def _checker_payload(text: str) -> dict:
    """Require machine-readable verdicts and evidence; fail closed on ambiguity."""
    candidate = (text or "").strip()
    match = re.search(r"\{[\s\S]*\}", candidate)
    if match:
        try:
            data = json.loads(match.group(0))
            decision = str(data.get("decision", "")).upper()
            evidence = data.get("evidence")
            issues = data.get("issues")
            instructions = data.get("revision_instructions", [])
            valid_lists = (isinstance(evidence, list) and all(isinstance(x, str) for x in evidence)
                           and isinstance(issues, list) and all(isinstance(x, str) for x in issues)
                           and isinstance(instructions, list) and all(isinstance(x, str) for x in instructions))
            if decision in {"PASS", "FAIL"} and valid_lists:
                if decision == "PASS" and (not evidence or issues):
                    return {"decision": "FAIL", "evidence": evidence,
                            "issues": ["PASS requires non-empty evidence and zero reported issues."],
                            "revision_instructions": ["Provide verifiable evidence and resolve all issues before PASS."]}
                return {"decision": decision, "evidence": evidence, "issues": issues,
                        "revision_instructions": instructions}
        except (ValueError, TypeError):
            pass
    return {"decision": "FAIL", "evidence": [],
            "issues": ["Checker did not return valid PASS/FAIL JSON with evidence."],
            "revision_instructions": ["Return the required JSON schema exactly."]}



def _review_payload(text: str) -> dict:
    """Parse a final reviewer verdict; malformed or ambiguous output fails closed."""
    verdict = _checker_payload(text)
    if verdict["decision"] == "FAIL" and any("valid PASS/FAIL JSON" in issue for issue in verdict["issues"]):
        return {"decision": "FAIL", "evidence": [],
                "issues": ["Reviewer did not return valid PASS/FAIL JSON with evidence."],
                "revision_instructions": ["Return JSON with decision, non-empty evidence, empty issues for PASS, and revision_instructions."]}
    return verdict


def execute_run(run_id: str, owner_username: str | None = None) -> None:
    if not _claim_run(run_id, owner_username):
        return
    worker_token = _worker_token(run_id, owner_username)
    if not worker_token:
        return

    def set_run(*args, **kwargs):
        return set_run(*args, worker_token=worker_token, **kwargs)

    def save_step(*args, **kwargs):
        return save_step(*args, worker_token=worker_token, **kwargs)

    def run_generate(prompt, workflow, provider):
        if _cancellation_requested(run_id, owner_username, worker_token):
            raise ProductionRunCancelled("Cancellation requested before model call.")
        if not _renew_worker_lease(run_id, worker_token):
            raise ProductionRunCancelled("Worker lease lost before model call.")
        started = time.monotonic()
        generated = run_generate(prompt, workflow, provider)
        elapsed = __import__("time").monotonic() - started
        if elapsed > MODEL_CALL_TIMEOUT_SECONDS:
            raise ProductionRunTimeout(f"Model call exceeded {MODEL_CALL_TIMEOUT_SECONDS} seconds.")
        if _cancellation_requested(run_id, owner_username, worker_token):
            raise ProductionRunCancelled("Cancellation requested during model call.")
        if not _renew_worker_lease(run_id, worker_token):
            raise ProductionRunCancelled("Worker lease lost after model call.")
        return generated

    run = get_run(run_id, owner_username)
    if not run:
        return
    selected = _selected_format(run["format_id"])
    if not selected:
        set_run(run_id, "failed", error="Video format no longer exists.")
        return
    research_record = None
    research_context_instruction = ""
    if run["format_id"] in DOCUMENTARY_FORMAT_IDS:
        try:
            research_record = get_research_evidence(
                RESEARCH_EVIDENCE_DB_PATH, run_id, run.get("owner_username", "local")
            )
        except (ValueError, sqlite3.Error):
            set_run(run_id, "paused", current_role="Documentary Research Evidence",
                     error="Documentary run paused: research evidence integrity/storage check failed.")
            return
        if not research_record:
            set_run(run_id, "paused", current_role="Documentary Research Evidence",
                     error="Documentary run paused: source-linked research evidence is missing.")
            return
        evidence_validation = validate_documentary_evidence_for_production(research_record["package"])
        if (not evidence_validation["valid"]
                or evidence_validation["sha256"] != research_record["sha256"]
                or str(research_record["package"].get("topic", "")).strip().casefold()
                   != str(run.get("topic", "")).strip().casefold()):
            set_run(run_id, "paused", current_role="Documentary Research Evidence",
                     error="Documentary run paused: evidence topic, structure or integrity did not match this run.")
            return
        research_context_instruction = (
            "DOCUMENTARY RESEARCH EVIDENCE LEDGER (structural traceability only; not independently fact-verified):\n"
            + build_research_prompt_context(research_record["package"])
            + "\nUse this ledger as the factual-claim boundary. Preserve claim IDs and source IDs in relevant "
              "deliverables. Do not invent historical facts, source contents, quotations, dates or citations. "
              "Flag any claim not directly represented in this ledger for human research review. "
              "The checker may validate traceability but cannot claim it fetched or authenticated sources.\n"
        )
    try:
        team = format_team(run["format_id"])
        pairs = [item for item in team if item.get("role_type") == "specialist"]
        owner_pair = next((item for item in pairs if item["name"] == "Owner Agent"), None)
        pairs = [item for item in pairs if item["name"] != "Owner Agent"]
        existing_steps = run.get("steps", [])
        deliverables: dict[str, str] = {}
        management_reports: dict[str, str] = {}
        sequence = max((step.get("sequence", 0) for step in existing_steps), default=0)
        approved_roles = {}
        for pair in pairs:
            saved_output = _approved_builder_output(existing_steps, pair["name"])
            if saved_output is not None:
                approved_roles[pair["name"]] = saved_output
                if pair["name"] in SENIOR_MANAGER_NAMES:
                    management_reports[pair["name"]] = saved_output
                else:
                    deliverables[pair["name"]] = saved_output
        for pair in pairs:
            role = pair["name"]
            if role in approved_roles:
                continue
            checker = role + " Checker"
            set_run(run_id, "running", current_role=role)
            worker_prompt = (
                "You are a specialist builder in SINTU AI YOUTUBE STUDIO.\n"
                "Produce only your assigned deliverable, with concrete production-ready detail.\n"
                "Video policy: Hindi Devanagari >=95%; English <=5%; no subtitles, captions, transcripts, "
                "titles, labels or text overlays in video frames. Only the final SINTU watermark is permitted.\n"
                f"Format: {selected['name']} ({selected['aspect_ratio']}, {selected['recommended_resolution']}).\n"
                f"Topic: {run['topic']}\nRole: {role}\nMission: {pair.get('mission','Perform your specialist task.')}\n"
                + research_context_instruction
                + "Previously approved specialist and management deliverables (actual prior-agent handoffs): "
                  + json.dumps({**deliverables, **management_reports}, ensure_ascii=False) + "\n"
                + (
                    "You are a senior management agent. Review completed specialist deliverables and earlier management reports; identify missing hand-offs, contradictions, risks and release blockers. Do not claim media was rendered or uploaded.\n"
                    "Current production evidence: " + json.dumps({**deliverables, **management_reports}, ensure_ascii=False) + "\n"
                    if role in SENIOR_MANAGER_NAMES else ""
                )
                + (
                    "Include a section headed exactly SCENE PROMPTS, then provide 6 to 12 numbered lines "
                    "(1. prompt, 2. prompt...). Each line must be a standalone, richly detailed, text-free "
                    "visual shot prompt with subject, setting, lighting and camera composition. Do not include "
                    "subtitles, words, labels or logos.\n"
                    if any(term in role.lower() for term in ("ai video generator", "filmmaking director", "storyboard"))
                    else ""
                )
                + "Use free/open-source tools by default. Do not claim external research, rendering or publishing occurred."
            )
            previous_output = ""
            verdict = None
            for attempt in range(MAX_REVISION_ATTEMPTS + 1):
                current_worker_prompt = worker_prompt
                if attempt:
                    current_worker_prompt = (
                        worker_prompt + "\nREVISION REQUIRED (attempt " + str(attempt) + "):\n"
                        "Correct the previous deliverable using the independent checker's exact findings. "
                        "Preserve correct material; do not invent evidence.\n"
                        "Checker issues: " + json.dumps(verdict["issues"], ensure_ascii=False) + "\n"
                        "Revision instructions: " + json.dumps(verdict["revision_instructions"], ensure_ascii=False) + "\n"
                        "Previous deliverable:\n" + previous_output
                    )
                worker = run_generate(current_worker_prompt, "content", "local")
                previous_output = worker["output"]
                sequence += 1
                save_step(run_id, sequence, role, "builder", "completed",
                           current_worker_prompt, worker["output"], attempts=attempt + 1)
                checker_prompt = (
                    "Act as an independent quality checker. Do not rewrite the work. "
                    "Evaluate accuracy, completeness, format fit, Hindi-first policy, clean text-free video frames, "
                    "copyright safety and actionable production detail. Return ONLY JSON with keys: "
                    "decision (PASS or FAIL), evidence (array), issues (array), revision_instructions (array).\n"
                    f"Topic: {run['topic']}\nSpecialist: {role}\n"
                    + research_context_instruction
                    + f"Revision attempt: {attempt + 1} of {MAX_REVISION_ATTEMPTS + 1}\n"
                    + f"Submitted work:\n{worker['output']}"
                )
                checked = run_generate(checker_prompt, "content", "local")
                verdict = _checker_payload(checked["output"])
                sequence += 1
                save_step(run_id, sequence, checker, "checker", verdict["decision"].lower(),
                           checker_prompt, checked["output"], verdict["evidence"], verdict["issues"],
                           attempts=attempt + 1)
                if verdict["decision"] == "PASS":
                    if role in SENIOR_MANAGER_NAMES:
                        management_reports[role] = worker["output"]
                    else:
                        deliverables[role] = worker["output"]
                    break
            if verdict["decision"] != "PASS":
                set_run(run_id, "paused", current_role=checker,
                         error="Independent checker failed after the bounded revision attempt. Run paused for human review.")
                return

        review_results = {}
        for reviewer in REVIEWERS:
            saved_report = _approved_reviewer_report(existing_steps, reviewer)
            if saved_report is not None:
                review_results[reviewer] = saved_report
                continue
            set_run(run_id, "reviewing", current_role=reviewer)
            review_prompt = (
                "You are an independent final video production reviewer. Review the assembled production package "
                "for your discipline. Return ONLY JSON with decision (PASS or FAIL), evidence (array), "
                "issues (array), and revision_instructions (array). PASS only when evidence supports every "
                "critical acceptance criterion. Do not claim a rendered video.\n"
                f"Reviewer: {reviewer}\nTopic: {run['topic']}\n"
                + research_context_instruction
                + f"Package summary: {json.dumps({k:v[:3500] for k,v in {**deliverables, **management_reports}.items()}, ensure_ascii=False)}"
            )
            review = run_generate(review_prompt, "content", "local")
            verdict = _review_payload(review["output"])
            review_results[reviewer] = {
                "decision": verdict["decision"],
                "evidence": verdict["evidence"],
                "issues": verdict["issues"],
                "revision_instructions": verdict["revision_instructions"],
                "raw_output": review["output"],
            }
            sequence += 1
            save_step(run_id, sequence, reviewer, "reviewer", verdict["decision"].lower(),
                       review_prompt, review["output"], verdict["evidence"], verdict["issues"])
            if verdict["decision"] != "PASS":
                set_run(run_id, "paused", current_role=reviewer,
                         error=f"Final reviewer failed: {reviewer}. Production run paused for correction.")
                return
        # Owner Agent runs after all five independent final reviewers so it can
        # evaluate their actual reports. Its checker is separate, and it cannot
        # replace the authenticated human owner's publishing approval.
        if owner_pair:
            owner_prompt = (
                "You are the SINTU Owner Agent. Review the complete production package, "
                "the HR/Manager/GM/HO reports, and every final reviewer report below. "
                "Return a concise release-readiness recommendation with risks, unresolved "
                "items and a clear READY or NOT READY conclusion. Never claim the video "
                "was uploaded. Never treat your recommendation as human owner approval.\n"
                f"Topic: {run['topic']}\n"
                + research_context_instruction
                + "Production deliverables: " + json.dumps(deliverables, ensure_ascii=False) + "\n"
                "Senior management reports: " + json.dumps(management_reports, ensure_ascii=False) + "\n"
                "Final reviewer reports: " + json.dumps(review_results, ensure_ascii=False)
            )
            owner_output = ""
            owner_verdict = None
            for attempt in range(MAX_REVISION_ATTEMPTS + 1):
                current_prompt = owner_prompt
                if attempt:
                    current_prompt += (
                        "\nREVISION REQUIRED: address the independent checker's findings.\n"
                        "Issues: " + json.dumps(owner_verdict["issues"], ensure_ascii=False) + "\n"
                        "Instructions: " + json.dumps(owner_verdict["revision_instructions"], ensure_ascii=False) + "\n"
                        "Previous owner report: " + owner_output
                    )
                owner_worker = run_generate(current_prompt, "content", "local")
                owner_output = owner_worker["output"]
                sequence += 1
                save_step(run_id, sequence, "Owner Agent", "builder", "completed",
                           current_prompt, owner_output, attempts=attempt + 1)
                owner_checker_prompt = (
                    "Act as an independent quality checker for the Owner Agent. Verify that the owner report "
                    "uses the actual management and final reviewer evidence, identifies blockers, "
                    "does not invent a rendered/uploaded state, and does not bypass human approval. "
                    "Return ONLY JSON with decision (PASS or FAIL), evidence (array), issues (array), "
                    "and revision_instructions (array). PASS only if the report gives a clear READY or NOT READY verdict "
                    "and accurately reflects all five final reviewer reports. If READY, there must be no unresolved blockers. "
                    "If NOT READY, cite the real blocker; the runtime will pause for the human owner.\n"
                    "Owner report: " + owner_output + "\n"
                    "Reviewer evidence: " + json.dumps(review_results, ensure_ascii=False)
                )
                owner_checked = run_generate(owner_checker_prompt, "content", "local")
                owner_verdict = _checker_payload(owner_checked["output"])
                sequence += 1
                save_step(run_id, sequence, "Owner Agent Checker", "checker",
                           owner_verdict["decision"].lower(), owner_checker_prompt,
                           owner_checked["output"], owner_verdict["evidence"],
                           owner_verdict["issues"], attempts=attempt + 1)
                if owner_verdict["decision"] == "PASS":
                    management_reports["Owner Agent"] = owner_output
                    if re.search(r"\bNOT\s+READY\b", owner_output, re.IGNORECASE):
                        set_run(run_id, "paused", current_role="Owner Agent",
                                 error="Owner Agent identified release blockers; human review is required before continuing.")
                        return
                    if not re.search(r"\bREADY\b", owner_output, re.IGNORECASE):
                        set_run(run_id, "paused", current_role="Owner Agent",
                                 error="Owner Agent did not provide an explicit READY verdict; human review is required.")
                        return
                    break
            if not owner_verdict or owner_verdict["decision"] != "PASS":
                set_run(run_id, "paused", current_role="Owner Agent Checker",
                         error="Owner Agent report failed its independent checker; human review required.")
                return

        result = {
            "format": selected,
            "deliverables": deliverables,
            "research_evidence": ({
                "sha256": research_record["sha256"],
                "source_count": research_record["validation"]["source_count"],
                "claim_count": research_record["validation"]["claim_count"],
                "status": "STRUCTURAL_TRACEABILITY_VALIDATED_NOT_FACT_VERIFIED",
                "human_fact_check_required": True,
            } if research_record else None),
            "reviewer_reports": review_results,
            "management_reports": management_reports,
            "management_hierarchy": management_hierarchy(),
            "publishing_approval_required": True,
            "video_rendered": False,
            "published": False,
            "note": "Production package and reviewer reports generated. Media rendering and external publishing are separate explicit stages."
        }
        if _cancellation_requested(run_id, owner_username, worker_token):
            raise ProductionRunCancelled("Cancellation requested before completion.")
        set_run(run_id, "completed", result=result)
    except ProductionRunCancelled:
        _finish_cancel(run_id, owner_username, worker_token)
    except ProductionRunTimeout as exc:
        set_run(run_id, "paused", error=str(exc))
    except (ProviderNotConfigured, ProviderRequestError) as exc:
        if _cancellation_requested(run_id, owner_username, worker_token):
            _finish_cancel(run_id, owner_username, worker_token)
        else:
            set_run(run_id, "blocked", error=str(exc))
    except Exception as exc:
        if _cancellation_requested(run_id, owner_username, worker_token):
            _finish_cancel(run_id, owner_username, worker_token)
        else:
            set_run(run_id, "failed", error=f"Production runtime error: {type(exc).__name__}")


def attach_render_result(run_id: str, render_result: dict[str, Any],
                         owner_username: str | None = None) -> dict[str, Any]:
    """Attach a separately rendered MP4 to a completed production package."""
    run = get_run(run_id, owner_username)
    if not run:
        raise ValueError("Production run not found.")
    if run["status"] != "completed" or not isinstance(run.get("result"), dict):
        raise ValueError("Only a completed, quality-approved production package can be rendered.")
    result = dict(run["result"])
    result["render"] = dict(render_result)
    result["video_rendered"] = True
    result["published"] = False
    _set_run(run_id, "completed", current_role=None, result=result)
    return get_run(run_id)
