"""Local-first revenue and business income tracker for SINTU AI YOUTUBE STUDIO.

This module records real, estimated and pending income separately. It does not
promise or generate earnings; external monetization providers remain opt-in.
"""
from datetime import date, datetime, timezone
from pathlib import Path
import csv
import io
import os
import sqlite3
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

router = APIRouter(tags=["earning-system"])
SOURCES = {"youtube_ads", "youtube_memberships", "youtube_supers", "affiliate", "sponsorship", "brand_deal", "digital_product", "service", "licensing", "other"}
STATUSES = {"confirmed", "estimated", "pending", "received", "cancelled"}
CURRENCIES = {"INR", "USD", "EUR", "GBP"}

def _db_path() -> Path:
    root = Path(os.getenv("SINTU_DATA_DIR", str(Path(__file__).resolve().parent.parent))).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root / "sintu_earnings.sqlite3"

def _connect():
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS earning_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL CHECK(kind IN ('income','expense')),
        source TEXT NOT NULL, title TEXT NOT NULL, amount REAL NOT NULL CHECK(amount >= 0),
        currency TEXT NOT NULL DEFAULT 'INR', status TEXT NOT NULL, record_date TEXT NOT NULL,
        reference TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_earning_records_date ON earning_records(record_date DESC)")
    conn.execute("""CREATE TABLE IF NOT EXISTS earning_targets (
        id INTEGER PRIMARY KEY AUTOINCREMENT, month TEXT NOT NULL UNIQUE,
        target_amount REAL NOT NULL CHECK(target_amount >= 0), currency TEXT NOT NULL DEFAULT 'INR',
        created_at TEXT NOT NULL
    )""")
    conn.commit()
    return conn

class RecordInput(BaseModel):
    kind: str = Field(pattern=r"^(income|expense)$")
    source: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=160)
    amount: float = Field(gt=0, le=1_000_000_000)
    currency: str = Field(default="INR", pattern=r"^(INR|USD|EUR|GBP)$")
    status: str = Field(default="confirmed", pattern=r"^(confirmed|estimated|pending|received|cancelled)$")
    record_date: date
    reference: str = Field(default="", max_length=240)
    notes: str = Field(default="", max_length=2000)

class TargetInput(BaseModel):
    month: str = Field(pattern=r"^\\d{4}-(0[1-9]|1[0-2])$")
    target_amount: float = Field(gt=0, le=1_000_000_000)
    currency: str = Field(default="INR", pattern=r"^(INR|USD|EUR|GBP)$")

def _record(row):
    item = dict(row)
    item["amount"] = round(float(item["amount"]), 2)
    return item

@router.get("/earnings", include_in_schema=False)
def earnings_page():
    return FileResponse(Path(__file__).resolve().parent / "static" / "earnings.html")

@router.get("/api/earnings/summary")
def earnings_summary(month: str | None = Query(default=None, pattern=r"^\\d{4}-(0[1-9]|1[0-2])$")):
    month = month or datetime.now(timezone.utc).strftime("%Y-%m")
    with _connect() as conn:
        rows = conn.execute("SELECT kind,status,currency,SUM(amount) total,COUNT(*) count FROM earning_records WHERE substr(record_date,1,7)=? GROUP BY kind,status,currency", (month,)).fetchall()
        target = conn.execute("SELECT target_amount,currency FROM earning_targets WHERE month=?", (month,)).fetchone()
        by_source = conn.execute("SELECT source,currency,SUM(amount) total,COUNT(*) count FROM earning_records WHERE kind='income' AND status IN ('confirmed','received') AND substr(record_date,1,7)=? GROUP BY source,currency ORDER BY total DESC", (month,)).fetchall()
    totals = {"confirmed_income": {}, "estimated_income": {}, "pending_income": {}, "expenses": {}, "received_income": {}, "net_confirmed": {}}
    for row in rows:
        key = row["currency"]
        bucket = ("expenses" if row["kind"] == "expense" and row["status"] != "cancelled" else
                  "confirmed_income" if row["kind"] == "income" and row["status"] == "confirmed" else
                  "received_income" if row["kind"] == "income" and row["status"] == "received" else
                  "estimated_income" if row["kind"] == "income" and row["status"] == "estimated" else
                  "pending_income" if row["kind"] == "income" and row["status"] == "pending" else None)
        if bucket:
            totals[bucket][key] = round(totals[bucket].get(key, 0) + float(row["total"] or 0), 2)
    currencies = set(totals["confirmed_income"]) | set(totals["received_income"]) | set(totals["expenses"])
    for currency in currencies:
        totals["net_confirmed"][currency] = round(totals["confirmed_income"].get(currency, 0) + totals["received_income"].get(currency, 0) - totals["expenses"].get(currency, 0), 2)
    target_data = dict(target) if target else None
    target_progress = None
    if target_data:
        earned = totals["confirmed_income"].get(target_data["currency"], 0) + totals["received_income"].get(target_data["currency"], 0)
        target_progress = round(earned / target_data["target_amount"] * 100, 1) if target_data["target_amount"] else 0
    return {"month": month, **totals, "target": target_data, "target_progress_percent": target_progress,
            "income_by_source": [{"source": r["source"], "currency": r["currency"], "amount": round(float(r["total"]), 2), "records": r["count"]} for r in by_source],
            "notice": "Estimated and pending amounts are not received money. Totals are grouped by currency; no exchange-rate conversion is applied."}

@router.get("/api/earnings/records")
def list_earning_records(kind: str | None = None, month: str | None = None, limit: int = Query(default=100, ge=1, le=500)):
    if kind and kind not in {"income", "expense"}:
        raise HTTPException(400, "kind must be income or expense")
    if month and (len(month) != 7 or month[4] != "-"):
        raise HTTPException(400, "month must use YYYY-MM")
    clauses, values = [], []
    if kind:
        clauses.append("kind=?"); values.append(kind)
    if month:
        clauses.append("substr(record_date,1,7)=?"); values.append(month)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM earning_records" + where + " ORDER BY record_date DESC,id DESC LIMIT ?", (*values, limit)).fetchall()
    return {"records": [_record(r) for r in rows]}

@router.post("/api/earnings/records", status_code=201)
def create_earning_record(payload: RecordInput):
    if payload.source not in SOURCES:
        raise HTTPException(400, "Unsupported income/expense source.")
    if payload.kind == "expense" and payload.status == "estimated":
        pass
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        cur = conn.execute("""INSERT INTO earning_records(kind,source,title,amount,currency,status,record_date,reference,notes,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (payload.kind,payload.source,payload.title.strip(),payload.amount,payload.currency,payload.status,payload.record_date.isoformat(),payload.reference.strip(),payload.notes.strip(),now,now))
        row = conn.execute("SELECT * FROM earning_records WHERE id=?", (cur.lastrowid,)).fetchone()
    return {"record": _record(row)}

@router.patch("/api/earnings/records/{record_id}")
def update_earning_record(record_id: int, payload: RecordInput):
    if payload.source not in SOURCES:
        raise HTTPException(400, "Unsupported income/expense source.")
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        cur = conn.execute("""UPDATE earning_records SET kind=?,source=?,title=?,amount=?,currency=?,status=?,record_date=?,reference=?,notes=?,updated_at=? WHERE id=?""",
            (payload.kind,payload.source,payload.title.strip(),payload.amount,payload.currency,payload.status,payload.record_date.isoformat(),payload.reference.strip(),payload.notes.strip(),now,record_id))
        if not cur.rowcount:
            raise HTTPException(404, "Earning record not found.")
        row = conn.execute("SELECT * FROM earning_records WHERE id=?", (record_id,)).fetchone()
    return {"record": _record(row)}

@router.delete("/api/earnings/records/{record_id}")
def delete_earning_record(record_id: int):
    with _connect() as conn:
        cur = conn.execute("DELETE FROM earning_records WHERE id=?", (record_id,))
    if not cur.rowcount:
        raise HTTPException(404, "Earning record not found.")
    return {"deleted": True, "id": record_id}

@router.put("/api/earnings/target")
def set_earning_target(payload: TargetInput):
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute("""INSERT INTO earning_targets(month,target_amount,currency,created_at) VALUES(?,?,?,?)
            ON CONFLICT(month) DO UPDATE SET target_amount=excluded.target_amount,currency=excluded.currency""",
            (payload.month,payload.target_amount,payload.currency,now))
        row = conn.execute("SELECT * FROM earning_targets WHERE month=?", (payload.month,)).fetchone()
    return {"target": dict(row)}

@router.get("/api/earnings/export.csv")
def export_earning_records():
    with _connect() as conn:
        rows = conn.execute("SELECT id,kind,source,title,amount,currency,status,record_date,reference,notes,created_at FROM earning_records ORDER BY record_date DESC,id DESC").fetchall()
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["id","kind","source","title","amount","currency","status","record_date","reference","notes","created_at"])
    writer.writerows([tuple(r) for r in rows])
    stream.seek(0)
    return StreamingResponse(iter([stream.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=sintu-earnings.csv"})
