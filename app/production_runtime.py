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
from .agents import AGENTS
from .management_hierarchy import SENIOR_MANAGER_NAMES, management_hierarchy
from .ai_brain import generate_text, ProviderNotConfigured, ProviderRequestError

DATA_DIR = Path(os.getenv("SINTU_DATA_DIR", str(Path(__file__).resolve().parent.parent))).expanduser().resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "production_runtime.sqlite3"
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



def get_run(run_id: str, owner_username: str | None = None) -> dict[str, Any] | None:
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
    """Move in-flight runs to resumable paused state after an application restart."""
    init_runtime_db()
    now = _now()
    with _connect() as conn:
        cursor = conn.execute(
            """UPDATE production_runs
               SET status='paused', error=?, updated_at=?
               WHERE status IN ('running', 'reviewing')""",
            ("Application restarted during production. Resume from the last independently approved checkpoint.", now),
        )
    return int(cursor.rowcount)


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
    run = get_run(run_id, owner_username)
    if not run:
        return
    if run["status"] not in {"queued", "paused"}:
        return
    selected = _selected_format(run["format_id"])
    if not selected:
        _set_run(run_id, "failed", error="Video format no longer exists.")
        return
    _set_run(run_id, "running")
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
            _set_run(run_id, "running", current_role=role)
            worker_prompt = (
                "You are a specialist builder in SINTU AI YOUTUBE STUDIO.\n"
                "Produce only your assigned deliverable, with concrete production-ready detail.\n"
                "Video policy: Hindi Devanagari >=95%; English <=5%; no subtitles, captions, transcripts, "
                "titles, labels or text overlays in video frames. Only the final SINTU watermark is permitted.\n"
                f"Format: {selected['name']} ({selected['aspect_ratio']}, {selected['recommended_resolution']}).\n"
                f"Topic: {run['topic']}\nRole: {role}\nMission: {pair.get('mission','Perform your specialist task.')}\n"
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
                worker = generate_text(current_worker_prompt, "content", "local")
                previous_output = worker["output"]
                sequence += 1
                _save_step(run_id, sequence, role, "builder", "completed",
                           current_worker_prompt, worker["output"], attempts=attempt + 1)
                checker_prompt = (
                    "Act as an independent quality checker. Do not rewrite the work. "
                    "Evaluate accuracy, completeness, format fit, Hindi-first policy, clean text-free video frames, "
                    "copyright safety and actionable production detail. Return ONLY JSON with keys: "
                    "decision (PASS or FAIL), evidence (array), issues (array), revision_instructions (array).\n"
                    f"Topic: {run['topic']}\nSpecialist: {role}\n"
                    f"Revision attempt: {attempt + 1} of {MAX_REVISION_ATTEMPTS + 1}\n"
                    f"Submitted work:\n{worker['output']}"
                )
                checked = generate_text(checker_prompt, "content", "local")
                verdict = _checker_payload(checked["output"])
                sequence += 1
                _save_step(run_id, sequence, checker, "checker", verdict["decision"].lower(),
                           checker_prompt, checked["output"], verdict["evidence"], verdict["issues"],
                           attempts=attempt + 1)
                if verdict["decision"] == "PASS":
                    if role in SENIOR_MANAGER_NAMES:
                        management_reports[role] = worker["output"]
                    else:
                        deliverables[role] = worker["output"]
                    break
            if verdict["decision"] != "PASS":
                _set_run(run_id, "paused", current_role=checker,
                         error="Independent checker failed after the bounded revision attempt. Run paused for human review.")
                return

        review_results = {}
        for reviewer in REVIEWERS:
            saved_report = _approved_reviewer_report(existing_steps, reviewer)
            if saved_report is not None:
                review_results[reviewer] = saved_report
                continue
            _set_run(run_id, "reviewing", current_role=reviewer)
            review_prompt = (
                "You are an independent final video production reviewer. Review the assembled production package "
                "for your discipline. Return ONLY JSON with decision (PASS or FAIL), evidence (array), "
                "issues (array), and revision_instructions (array). PASS only when evidence supports every "
                "critical acceptance criterion. Do not claim a rendered video.\n"
                f"Reviewer: {reviewer}\nTopic: {run['topic']}\n"
                f"Package summary: {json.dumps({k:v[:3500] for k,v in {**deliverables, **management_reports}.items()}, ensure_ascii=False)}"
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
                "Production deliverables: " + json.dumps(deliverables, ensure_ascii=False) + "\n"
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
                owner_worker = generate_text(current_prompt, "content", "local")
                owner_output = owner_worker["output"]
                sequence += 1
                _save_step(run_id, sequence, "Owner Agent", "builder", "completed",
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
                owner_checked = generate_text(owner_checker_prompt, "content", "local")
                owner_verdict = _checker_payload(owner_checked["output"])
                sequence += 1
                _save_step(run_id, sequence, "Owner Agent Checker", "checker",
                           owner_verdict["decision"].lower(), owner_checker_prompt,
                           owner_checked["output"], owner_verdict["evidence"],
                           owner_verdict["issues"], attempts=attempt + 1)
                if owner_verdict["decision"] == "PASS":
                    management_reports["Owner Agent"] = owner_output
                    if re.search(r"\bNOT\s+READY\b", owner_output, re.IGNORECASE):
                        _set_run(run_id, "paused", current_role="Owner Agent",
                                 error="Owner Agent identified release blockers; human review is required before continuing.")
                        return
                    if not re.search(r"\bREADY\b", owner_output, re.IGNORECASE):
                        _set_run(run_id, "paused", current_role="Owner Agent",
                                 error="Owner Agent did not provide an explicit READY verdict; human review is required.")
                        return
                    break
            if not owner_verdict or owner_verdict["decision"] != "PASS":
                _set_run(run_id, "paused", current_role="Owner Agent Checker",
                         error="Owner Agent report failed its independent checker; human review required.")
                return

        result = {
            "format": selected,
            "deliverables": deliverables,
            "reviewer_reports": review_results,
            "management_reports": management_reports,
            "management_hierarchy": management_hierarchy(),
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
