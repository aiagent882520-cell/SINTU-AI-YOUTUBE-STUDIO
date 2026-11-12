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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .studio_scope import get_format, production_plan
from .agent_orchestrator import format_team
from .ai_brain import generate_text, ProviderNotConfigured, ProviderRequestError

DATA_DIR = Path(os.getenv("SINTU_DATA_DIR", str(Path(__file__).resolve().parent.parent))).expanduser().resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "production_runtime.sqlite3"
MAX_REVISION_ATTEMPTS = 1
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
            error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS production_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
            sequence INTEGER NOT NULL, role TEXT NOT NULL, step_type TEXT NOT NULL,
            status TEXT NOT NULL, input_text TEXT, output_text TEXT,
            evidence_json TEXT, issues_json TEXT, attempts INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            FOREIGN KEY(run_id) REFERENCES production_runs(id)
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_production_steps_run ON production_steps(run_id, sequence)")


def create_run(format_id: str, topic: str) -> dict[str, Any]:
    selected = get_format(format_id)
    if not selected:
        raise ValueError("Unknown video format.")
    topic = (topic or "").strip()
    if not topic or len(topic) > 5000:
        raise ValueError("Topic must contain 1 to 5000 characters.")
    init_runtime_db()
    run_id = uuid.uuid4().hex
    now = _now()
    with _connect() as conn:
        conn.execute("""INSERT INTO production_runs
            (id,format_id,topic,status,created_at,updated_at) VALUES(?,?,?,?,?,?)""",
            (run_id, format_id, topic, "queued", now, now))
    return get_run(run_id)


def get_run(run_id: str) -> dict[str, Any] | None:
    init_runtime_db()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM production_runs WHERE id=?", (run_id,)).fetchone()
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
             error: str | None = None, result: dict | None = None) -> None:
    with _connect() as conn:
        conn.execute("""UPDATE production_runs SET status=?,current_role=?,error=?,
            result_json=?,updated_at=? WHERE id=?""",
            (status, current_role, error, json.dumps(result, ensure_ascii=False) if result is not None else None, _now(), run_id))


def _save_step(run_id: str, sequence: int, role: str, step_type: str,
               status: str, input_text: str, output_text: str = "",
               evidence: list | None = None, issues: list | None = None,
               attempts: int = 1) -> None:
    with _connect() as conn:
        conn.execute("""INSERT INTO production_steps
            (run_id,sequence,role,step_type,status,input_text,output_text,evidence_json,issues_json,attempts,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (run_id, sequence, role, step_type, status, input_text, output_text,
             json.dumps(evidence or [], ensure_ascii=False), json.dumps(issues or [], ensure_ascii=False),
             attempts, _now(), _now()))


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


def execute_run(run_id: str) -> None:
    run = get_run(run_id)
    if not run:
        return
    if run["status"] not in {"queued", "paused"}:
        return
    selected = get_format(run["format_id"])
    if not selected:
        _set_run(run_id, "failed", error="Video format no longer exists.")
        return
    _set_run(run_id, "running")
    try:
        team = format_team(run["format_id"])
        pairs = [item for item in team if item.get("role_type") == "specialist"]
        deliverables: dict[str, str] = {}
        sequence = 0
        for pair in pairs:
            role = pair["name"]
            checker = role + " Checker"
            _set_run(run_id, "running", current_role=role)
            worker_prompt = (
                "You are a specialist builder in SINTU AI YOUTUBE STUDIO.\n"
                "Produce only your assigned deliverable, with concrete production-ready detail.\n"
                "Video policy: Hindi Devanagari >=95%; English <=5%; no subtitles, captions, transcripts, "
                "titles, labels or text overlays in video frames. Only the final SINTU watermark is permitted.\n"
                f"Format: {selected['name']} ({selected['aspect_ratio']}, {selected['recommended_resolution']}).\n"
                f"Topic: {run['topic']}\nRole: {role}\nMission: {pair.get('mission','Perform your specialist task.')}\n"
                "Use free/open-source tools by default. Do not claim external research, rendering or publishing occurred."
            )
            previous_output = ""
            verdict = None
            for attempt in range(MAX_REVISION_ATTEMPTS + 1):
                current_worker_prompt = worker_prompt
                if attempt:
                    current_worker_prompt = (
                        worker_prompt + "\\nREVISION REQUIRED (attempt " + str(attempt) + "):\\n"
                        "Correct the previous deliverable using the independent checker's exact findings. "
                        "Preserve correct material; do not invent evidence.\\n"
                        "Checker issues: " + json.dumps(verdict["issues"], ensure_ascii=False) + "\\n"
                        "Revision instructions: " + json.dumps(verdict["revision_instructions"], ensure_ascii=False) + "\\n"
                        "Previous deliverable:\\n" + previous_output
                    )
                worker = generate_text(current_worker_prompt, "content", "local")
                previous_output = worker["output"]
                sequence += 1
                _save_step(run_id, sequence, role, "builder", "completed",
                           current_worker_prompt, worker["output"], attempts=attempt + 1)
                checker_prompt = (
                    "Act as an independent quality checker. Do not rewrite the work. "
                    "Evaluate accuracy, completeness, format fit, Hindi-first policy, clean text-free video frames, "
                    "copyright safety and actionable production detail. Return ONLY JSON with keys: "
                    "decision (PASS or FAIL), evidence (array), issues (array), revision_instructions (array).\\n"
                    f"Topic: {run['topic']}\\nSpecialist: {role}\\n"
                    f"Revision attempt: {attempt + 1} of {MAX_REVISION_ATTEMPTS + 1}\\n"
                    f"Submitted work:\\n{worker['output']}"
                )
                checked = generate_text(checker_prompt, "content", "local")
                verdict = _checker_payload(checked["output"])
                sequence += 1
                _save_step(run_id, sequence, checker, "checker", verdict["decision"].lower(),
                           checker_prompt, checked["output"], verdict["evidence"], verdict["issues"],
                           attempts=attempt + 1)
                if verdict["decision"] == "PASS":
                    deliverables[role] = worker["output"]
                    break
            if verdict["decision"] != "PASS":
                _set_run(run_id, "paused", current_role=checker,
                         error="Independent checker failed after the bounded revision attempt. Run paused for human review.")
                return

        review_results = {}
        for reviewer in REVIEWERS:
            _set_run(run_id, "reviewing", current_role=reviewer)
            review_prompt = (
                "You are an independent final video production reviewer. Review the assembled production package "
                "for your discipline. Return ONLY JSON with decision (PASS or FAIL), evidence (array), "
                "issues (array), and revision_instructions (array). PASS only when evidence supports every "
                "critical acceptance criterion. Do not claim a rendered video.\n"
                f"Reviewer: {reviewer}\nTopic: {run['topic']}\n"
                f"Package summary: {json.dumps({k:v[:3500] for k,v in deliverables.items()}, ensure_ascii=False)}"
            )
            review = generate_text(review_prompt, "content", "local")
            verdict = _review_payload(review["output"])
            review_results[reviewer] = {
                "decision": verdict["decision"],
                "evidence": verdict["evidence"],
                "issues": verdict["issues"],
                "revision_instructions": verdict["revision_instructions"],
                "raw_output": review["output"],
            }
            sequence += 1
            _save_step(run_id, sequence, reviewer, "reviewer", verdict["decision"].lower(),
                       review_prompt, review["output"], verdict["evidence"], verdict["issues"])
            if verdict["decision"] != "PASS":
                _set_run(run_id, "paused", current_role=reviewer,
                         error=f"Final reviewer failed: {reviewer}. Production run paused for correction.")
                return
        result = {
            "format": selected,
            "deliverables": deliverables,
            "reviewer_reports": review_results,
            "publishing_approval_required": True,
            "video_rendered": False,
            "published": False,
            "note": "Production package and reviewer reports generated. Media rendering and external publishing are separate explicit stages."
        }
        _set_run(run_id, "completed", result=result)
    except (ProviderNotConfigured, ProviderRequestError) as exc:
        _set_run(run_id, "blocked", error=str(exc))
    except Exception as exc:
        _set_run(run_id, "failed", error=f"Production runtime error: {type(exc).__name__}")


def attach_render_result(run_id: str, render_result: dict[str, Any]) -> dict[str, Any]:
    """Attach a separately rendered MP4 to a completed production package."""
    run = get_run(run_id)
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
