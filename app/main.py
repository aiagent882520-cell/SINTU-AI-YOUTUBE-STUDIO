from pathlib import Path
import json
import sqlite3
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agents import list_agents

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT.parent / "sintu_studio.db"
STATIC = ROOT / "static"

app = FastAPI(title="SINTU AI STUDIO", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                prompt TEXT NOT NULL,
                workflow TEXT NOT NULL DEFAULT 'content',
                status TEXT NOT NULL DEFAULT 'Pending',
                created_at TEXT NOT NULL
            )
        """)

init_db()

class TaskInput(BaseModel):
    prompt: str = Field(min_length=1, max_length=10000)
    workflow: str = Field(default="content", max_length=80)

@app.get("/")
def home():
    return FileResponse(STATIC / "index.html")

@app.get("/api/health")
def health():
    return {"status": "ok", "app": "SINTU AI STUDIO", "version": app.version}

@app.get("/api/agents")
def agents():
    return {"total": len(list_agents()), "agents": list_agents()}

@app.post("/api/tasks")
def create_task(payload: TaskInput):
    prompt = payload.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")
    created = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO tasks(prompt, workflow, status, created_at) VALUES (?, ?, ?, ?)",
            (prompt, payload.workflow, "Pending", created),
        )
        task_id = cur.lastrowid
    return {"id": task_id, "status": "Pending", "message": "Request saved. AI provider is not configured yet."}

@app.get("/api/tasks")
def tasks():
    with db() as conn:
        rows = conn.execute("SELECT * FROM tasks ORDER BY id DESC LIMIT 100").fetchall()
    return {"tasks": [dict(row) for row in rows]}

@app.get("/api/status")
def status():
    with db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    return {"agents_total": len(list_agents()), "agents_implemented": 0, "tasks_saved": count,
            "video_generation": "Not configured", "publishing": "Not configured"}
