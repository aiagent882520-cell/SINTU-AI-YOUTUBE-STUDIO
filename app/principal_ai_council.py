"""Four-provider Principal AI Council with fail-closed voting and auditable decisions.

This module records decisions only. It never merges code, deploys, publishes, or spends
money on its own. Provider calls remain subject to ai_brain's paid-upgrade policy.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import re
import secrets

from .ai_brain import (
    ProviderNotConfigured,
    ProviderRequestError,
    generate_text,
    paid_upgrades_allowed,
    provider_status,
)

PRINCIPALS = (
    {"id": "chatgpt", "name": "ChatGPT", "provider": "openai", "role": "Master Principal AI"},
    {"id": "gemini", "name": "Gemini", "provider": "gemini", "role": "Principal AI"},
    {"id": "claude", "name": "Claude", "provider": "claude", "role": "Principal AI"},
    {"id": "deepseek", "name": "DeepSeek", "provider": "deepseek", "role": "Principal AI"},
)
PRINCIPAL_IDS = tuple(item["id"] for item in PRINCIPALS)
DECISION_TYPES = {
    "major", "security", "architecture", "production_release",
    "paid_action", "public_publish", "external_data_sharing", "code_integration",
}
UNANIMOUS_TYPES = {"security", "architecture", "production_release"}
OWNER_APPROVAL_TYPES = {
    "major", "security", "architecture", "production_release", "paid_action",
    "public_publish", "external_data_sharing", "code_integration",
}
GENESIS_HASH = "0" * 64


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_schema(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS principal_ai_decisions (
            id TEXT PRIMARY KEY,
            owner_username TEXT NOT NULL,
            title TEXT NOT NULL,
            decision_type TEXT NOT NULL,
            context_text TEXT NOT NULL,
            status TEXT NOT NULL,
            owner_approval_status TEXT NOT NULL DEFAULT 'not_required',
            owner_approval_note TEXT NOT NULL DEFAULT '',
            result_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_principal_ai_decisions_owner
            ON principal_ai_decisions(owner_username, created_at DESC);
        CREATE TABLE IF NOT EXISTS principal_ai_votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            decision_id TEXT NOT NULL,
            principal_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            vote TEXT NOT NULL DEFAULT '',
            rationale TEXT NOT NULL DEFAULT '',
            evidence_json TEXT NOT NULL DEFAULT '[]',
            risks_json TEXT NOT NULL DEFAULT '[]',
            raw_response TEXT NOT NULL DEFAULT '',
            error_code TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(decision_id, principal_id)
        );
        CREATE INDEX IF NOT EXISTS idx_principal_ai_votes_decision
            ON principal_ai_votes(decision_id, principal_id);
        CREATE TABLE IF NOT EXISTS principal_ai_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_username TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            action TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            previous_hash TEXT NOT NULL,
            event_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_principal_ai_audit_owner
            ON principal_ai_audit(owner_username, id);
        """
    )


def council_status() -> dict:
    statuses = provider_status()
    paid_allowed = paid_upgrades_allowed()
    principals = []
    for principal in PRINCIPALS:
        provider = principal["provider"]
        info = statuses.get(provider, {})
        configured = bool(info.get("configured"))
        if not configured:
            state = "blocked_missing_credentials"
        elif not paid_allowed:
            state = "blocked_paid_policy"
        else:
            state = "credentials_configured_not_live_verified"
        principals.append({
            **principal,
            "model": info.get("model", ""),
            "api_key_configured": configured,
            "eligible_to_call": configured and paid_allowed,
            "status": state,
        })
    local = statuses.get("local", {})
    return {
        "master_director": "chatgpt",
        "principal_ais": principals,
        "council_ready": False,
        "all_principals_eligible_to_call": all(item["eligible_to_call"] for item in principals),
        "readiness": "credentials_ready_live_health_unverified" if all(item["eligible_to_call"] for item in principals) else "blocked_or_incomplete",
        "paid_upgrades_allowed": paid_allowed,
        "local_fallback": {
            "configured": bool(local.get("configured")),
            "model": local.get("model", ""),
            "role": "advisory_fallback_only",
            "counts_as_principal_vote": False,
        },
        "decision_rules": {
            "majority_approval_votes": 3,
            "tie_status": "needs_research_and_revote",
            "unanimous_types": sorted(UNANIMOUS_TYPES),
            "owner_approval_types": sorted(OWNER_APPROVAL_TYPES),
            "incomplete_council": "block_major_decision",
        },
        "live_provider_health": "NOT_CHECKED",
        "note": "Configured credentials are not proof of a live provider connection. Paid provider calls remain locked until revenue and explicit Owner approval.",
    }


def _audit(conn, owner: str, actor: str, action: str, entity_id: str, payload: dict) -> None:
    previous = conn.execute(
        "SELECT event_hash FROM principal_ai_audit WHERE owner_username=? ORDER BY id DESC LIMIT 1",
        (owner,),
    ).fetchone()
    previous_hash = previous["event_hash"] if previous else GENESIS_HASH
    created_at = _now()
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    event = {
        "owner_username": owner,
        "actor_id": actor,
        "action": action,
        "entity_id": entity_id,
        "payload_json": payload_json,
        "previous_hash": previous_hash,
        "created_at": created_at,
    }
    event_hash = hashlib.sha256(
        json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    conn.execute(
        """INSERT INTO principal_ai_audit
        (owner_username,actor_id,action,entity_id,payload_json,previous_hash,event_hash,created_at)
        VALUES(?,?,?,?,?,?,?,?)""",
        (owner, actor, action, entity_id, payload_json, previous_hash, event_hash, created_at),
    )


def verify_audit_chain(conn, owner: str) -> dict:
    rows = conn.execute(
        "SELECT * FROM principal_ai_audit WHERE owner_username=? ORDER BY id",
        (owner,),
    ).fetchall()
    previous_hash = GENESIS_HASH
    for row in rows:
        event = {
            "owner_username": row["owner_username"],
            "actor_id": row["actor_id"],
            "action": row["action"],
            "entity_id": row["entity_id"],
            "payload_json": row["payload_json"],
            "previous_hash": previous_hash,
            "created_at": row["created_at"],
        }
        expected = hashlib.sha256(
            json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if row["previous_hash"] != previous_hash or row["event_hash"] != expected:
            return {"valid": False, "events_checked": len(rows), "failed_event_id": row["id"]}
        previous_hash = row["event_hash"]
    return {"valid": True, "events_checked": len(rows), "failed_event_id": None}


def _parse_vote(output: str) -> dict:
    if not isinstance(output, str) or not output.strip():
        raise ValueError("empty_model_output")
    start = output.find("{")
    if start < 0:
        raise ValueError("missing_json_object")
    payload, _ = json.JSONDecoder().raw_decode(output[start:])
    vote = str(payload.get("vote", "")).strip().upper()
    if vote not in {"APPROVE", "REJECT", "ABSTAIN"}:
        raise ValueError("invalid_vote")
    rationale = str(payload.get("rationale", "")).strip()[:4000]
    evidence = payload.get("evidence", [])
    risks = payload.get("risks", [])
    if not isinstance(evidence, list) or not isinstance(risks, list):
        raise ValueError("invalid_evidence_shape")
    evidence = [str(item).strip()[:2000] for item in evidence if str(item).strip()][:12]
    risks = [str(item).strip()[:2000] for item in risks if str(item).strip()][:12]
    if not rationale or not evidence:
        raise ValueError("rationale_and_evidence_required")
    return {"vote": vote, "rationale": rationale, "evidence": evidence, "risks": risks}


def _decision_outcome(decision_type: str, vote_records: list[dict]) -> tuple[str, str]:
    complete = {item["principal_id"] for item in vote_records if item["status"] == "valid"}
    if complete != set(PRINCIPAL_IDS):
        return "blocked_incomplete_council", "not_required"
    votes = [item["vote"] for item in vote_records]
    approvals = votes.count("APPROVE")
    rejections = votes.count("REJECT")
    if decision_type in UNANIMOUS_TYPES:
        if approvals == 4:
            return "pending_owner_approval", "pending"
        if rejections:
            return "rejected_unanimity_gate", "not_required"
        return "needs_research_and_revote", "not_required"
    if approvals >= 3:
        if decision_type in OWNER_APPROVAL_TYPES:
            return "pending_owner_approval", "pending"
        return "approved_by_majority", "not_required"
    if rejections >= 3:
        return "rejected_by_majority", "not_required"
    return "needs_research_and_revote", "not_required"


def _call_principal(principal: dict, prompt: str) -> dict:
    try:
        result = generate_text(prompt, "research", provider_override=principal["provider"])
        parsed = _parse_vote(result.get("output", ""))
        return {
            "principal_id": principal["id"], "provider": principal["provider"],
            "model": str(result.get("model", "")), "status": "valid",
            **parsed, "raw_response": str(result.get("output", ""))[:12000], "error_code": "",
        }
    except ProviderNotConfigured:
        code = "provider_not_configured_or_policy_locked"
    except ProviderRequestError:
        code = "provider_request_failed"
    except (ValueError, TypeError, KeyError):
        code = "invalid_provider_response"
    except Exception:
        code = "provider_internal_error"
    return {
        "principal_id": principal["id"], "provider": principal["provider"],
        "model": "", "status": "failed", "vote": "", "rationale": "",
        "evidence": [], "risks": [], "raw_response": "", "error_code": code,
    }


def run_council_decision(conn, owner: str, title: str, context: str, decision_type: str) -> dict:
    if decision_type not in DECISION_TYPES:
        raise ValueError("Unsupported council decision type.")
    if not title.strip() or not context.strip():
        raise ValueError("Decision title and context are required.")
    ensure_schema(conn)
    conn.execute("BEGIN IMMEDIATE")
    decision_id = secrets.token_hex(16)
    now = _now()
    conn.execute(
        """INSERT INTO principal_ai_decisions
        (id,owner_username,title,decision_type,context_text,status,owner_approval_status,result_json,created_at,updated_at)
        VALUES(?,?,?,?,?,'running','not_required','{}',?,?)""",
        (decision_id, owner, title.strip()[:160], decision_type, context.strip()[:12000], now, now),
    )
    _audit(conn, owner, "sintu_council_service", "council_decision_started", decision_id, {"decision_type": decision_type})
    conn.commit()
    state = council_status()
    eligible = [p for p, status in zip(PRINCIPALS, state["principal_ais"]) if status["eligible_to_call"]]
    prompt_template = (
        "You are an independent Principal AI on the SINTU AI YOUTUBE STUDIO Council. "
        "Do not claim to be another provider. Analyze only the supplied decision and evidence. "
        "Do not execute code changes, deployments, publishing, payments, or permissions. "
        "Return exactly one JSON object with keys vote, rationale, evidence, risks. "
        "vote must be APPROVE, REJECT, or ABSTAIN. Include concrete evidence; if evidence is insufficient, ABSTAIN.\n\n"
        "Decision type: {decision_type}\nDecision title: {title}\nContext and evidence:\n{context}"
    )
    prompt = prompt_template.format(
        decision_type=decision_type, title=title.strip(), context=context.strip()
    )
    records = []
    if eligible:
        with ThreadPoolExecutor(max_workers=min(4, len(eligible))) as pool:
            futures = {pool.submit(_call_principal, principal, prompt): principal for principal in eligible}
            for future in as_completed(futures):
                records.append(future.result())
    for principal in PRINCIPALS:
        if principal["id"] not in {item["principal_id"] for item in records}:
            provider_state = next(item for item in state["principal_ais"] if item["id"] == principal["id"])
            records.append({
                "principal_id": principal["id"], "provider": principal["provider"],
                "model": provider_state["model"], "status": "blocked",
                "vote": "", "rationale": "", "evidence": [], "risks": [],
                "raw_response": "", "error_code": provider_state["status"],
            })
    records.sort(key=lambda item: PRINCIPAL_IDS.index(item["principal_id"]))
    status, approval_status = _decision_outcome(decision_type, records)

    advisory = None
    if status == "blocked_incomplete_council" and state["local_fallback"]["configured"]:
        try:
            local_result = generate_text(
                "Provide a concise advisory analysis only. Do not cast a Principal AI vote. "
                "List evidence gaps, risks and suggested next research steps.\n\n" + prompt,
                "research",
                provider_override="local",
            )
            advisory = {"status": "advisory_only", "model": local_result.get("model", ""),
                        "output": str(local_result.get("output", ""))[:12000]}
        except Exception:
            advisory = {"status": "failed", "model": state["local_fallback"]["model"], "output": ""}

    conn.execute("BEGIN IMMEDIATE")
    for record in records:
        conn.execute(
            """INSERT INTO principal_ai_votes
            (decision_id,principal_id,provider,model,status,vote,rationale,evidence_json,risks_json,raw_response,error_code,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (decision_id, record["principal_id"], record["provider"], record.get("model", ""),
             record["status"], record.get("vote", ""), record.get("rationale", ""),
             json.dumps(record.get("evidence", []), ensure_ascii=False),
             json.dumps(record.get("risks", []), ensure_ascii=False),
             record.get("raw_response", ""), record.get("error_code", ""), _now()),
        )
    result = {
        "vote_counts": {vote: sum(1 for item in records if item.get("vote") == vote)
                        for vote in ("APPROVE", "REJECT", "ABSTAIN")},
        "all_four_valid_votes": all(item["status"] == "valid" for item in records),
        "owner_approval_required": approval_status == "pending",
        "local_advisory": advisory,
    }
    conn.execute(
        "UPDATE principal_ai_decisions SET status=?,owner_approval_status=?,result_json=?,updated_at=? WHERE id=? AND owner_username=?",
        (status, approval_status, json.dumps(result, ensure_ascii=False), _now(), decision_id, owner),
    )
    _audit(conn, owner, "sintu_council_service", "council_decision_completed", decision_id,
           {"status": status, "vote_counts": result["vote_counts"]})
    return get_decision(conn, owner, decision_id)


def get_decision(conn, owner: str, decision_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM principal_ai_decisions WHERE id=? AND owner_username=?",
        (decision_id, owner),
    ).fetchone()
    if not row:
        return None
    votes = conn.execute(
        "SELECT * FROM principal_ai_votes WHERE decision_id=? ORDER BY principal_id",
        (decision_id,),
    ).fetchall()
    return {
        "id": row["id"], "title": row["title"], "decision_type": row["decision_type"],
        "status": row["status"], "owner_approval_status": row["owner_approval_status"],
        "owner_approval_note": row["owner_approval_note"],
        "result": json.loads(row["result_json"] or "{}"),
        "votes": [{
            "principal_id": vote["principal_id"], "provider": vote["provider"],
            "model": vote["model"], "status": vote["status"], "vote": vote["vote"],
            "rationale": vote["rationale"], "evidence": json.loads(vote["evidence_json"] or "[]"),
            "risks": json.loads(vote["risks_json"] or "[]"), "error_code": vote["error_code"],
        } for vote in votes],
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def list_decisions(conn, owner: str, limit: int = 50) -> list[dict]:
    ensure_schema(conn)
    rows = conn.execute(
        "SELECT id FROM principal_ai_decisions WHERE owner_username=? ORDER BY created_at DESC LIMIT ?",
        (owner, max(1, min(int(limit), 100))),
    ).fetchall()
    return [item for row in rows if (item := get_decision(conn, owner, row["id"]))]


def owner_approve_decision(conn, owner: str, actor: str, decision_id: str, approved: bool, note: str = "") -> dict | None:
    ensure_schema(conn)
    conn.execute("BEGIN IMMEDIATE")
    row = conn.execute(
        "SELECT status,owner_approval_status FROM principal_ai_decisions WHERE id=? AND owner_username=?",
        (decision_id, owner),
    ).fetchone()
    if not row:
        return None
    if row["status"] != "pending_owner_approval" or row["owner_approval_status"] != "pending":
        raise ValueError("Decision is not waiting for Owner approval.")
    status = "owner_approved" if approved else "owner_rejected"
    approval_status = "approved" if approved else "rejected"
    conn.execute(
        "UPDATE principal_ai_decisions SET status=?,owner_approval_status=?,owner_approval_note=?,updated_at=? WHERE id=? AND owner_username=?",
        (status, approval_status, str(note or "")[:4000], _now(), decision_id, owner),
    )
    _audit(conn, owner, actor, "owner_approval_recorded", decision_id,
           {"approved": bool(approved), "note": str(note or "")[:4000]})
    return get_decision(conn, owner, decision_id)
