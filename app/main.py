from pathlib import Path
import io
import sqlite3
import re
import shutil
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agents import list_agents
from .agent_orchestrator import workflow_team, orchestration_summary
from .ai_brain import ProviderNotConfigured, ProviderRequestError, generate_text, provider_status, WORKFLOW_GUIDES
from .video_renderer import render_storyboard, RendererUnavailable, RenderFailed, OUTPUT_DIR

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT.parent / "sintu_studio.db"
STATIC = ROOT / "static"

app = FastAPI(title="SINTU AI STUDIO", version="0.3.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "connect-src 'self'; object-src 'none'; base-uri 'self'; "
        "form-action 'self'; frame-ancestors 'none'"
    )
    return response

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
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)")}
        if "output" not in columns:
            conn.execute("ALTER TABLE tasks ADD COLUMN output TEXT")

init_db()

class TaskInput(BaseModel):
    prompt: str = Field(min_length=1, max_length=10000)
    workflow: str = Field(default="content", max_length=80)

class RenderInput(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    scenes: list[str] = Field(min_length=1, max_length=25)
    seconds_per_scene: int = Field(default=4, ge=2, le=12)

@app.get("/")
def home():
    return FileResponse(STATIC / "index.html")

@app.get("/sw.js", include_in_schema=False)
def service_worker():
    return FileResponse(
        STATIC / "sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )

@app.get("/api/health")
def health():
    return {"status": "ok", "app": "SINTU AI STUDIO", "version": app.version}

@app.get("/api/workflows")
def workflows():
    return {"total": len(WORKFLOW_GUIDES), "workflows": [
        {"id": key, "name": key.replace("-", " ").title(), "description": value.splitlines()[0]}
        for key, value in WORKFLOW_GUIDES.items()
    ]}

@app.get("/api/agents")
def agents():
    return {"total": len(list_agents()), "agents": list_agents(), "orchestration": orchestration_summary()}

@app.get("/api/capabilities")
def capabilities():
    providers = provider_status()
    return {
        "product": "SINTU AI STUDIO",
        "workflows": list(WORKFLOW_GUIDES.keys()),
        "agent_catalog": len(list_agents()),
        "orchestration": orchestration_summary(),
        "providers": {
            "openai": providers["openai"]["configured"],
            "gemini": providers["gemini"]["configured"],
        },
        "requires_external_integration": [
            "image_generation", "video_generation", "voice_generation",
            "licensed_music", "rendering", "youtube_oauth", "social_oauth",
            "channel_analytics", "managed_database"
        ],
        "safety": {
            "public_actions_require_approval": True,
            "secrets_returned_by_api": False,
            "cybersecurity_scope": "authorized defensive labs only"
        }
    }

@app.get("/api/workflows/{workflow_id}/team")
def workflow_team_detail(workflow_id: str):
    if workflow_id not in WORKFLOW_GUIDES:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return {"workflow": workflow_id, "team": workflow_team(workflow_id),
            "execution_mode": orchestration_summary()["execution_mode"]}

@app.get("/api/providers")
def providers():
    return provider_status()

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
    return {"id": task_id, "status": "Pending", "message": "Task saved. AI generation has not been run."}

@app.post("/api/generate")
def generate(payload: TaskInput):
    prompt = payload.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")
    if payload.workflow not in WORKFLOW_GUIDES:
        raise HTTPException(status_code=400, detail="Unknown workflow. Choose an available workflow.")
    created = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO tasks(prompt, workflow, status, created_at) VALUES (?, ?, ?, ?)",
            (prompt, payload.workflow, "Generating", created),
        )
        task_id = cur.lastrowid
    try:
        result = generate_text(prompt, payload.workflow)
    except ProviderNotConfigured as exc:
        with db() as conn:
            conn.execute("UPDATE tasks SET status = ? WHERE id = ?", ("Blocked", task_id))
        raise HTTPException(status_code=503, detail=str(exc))
    except ProviderRequestError as exc:
        with db() as conn:
            conn.execute("UPDATE tasks SET status = ? WHERE id = ?", ("Failed", task_id))
        raise HTTPException(status_code=502, detail=str(exc))
    with db() as conn:
        conn.execute(
            "UPDATE tasks SET status = ?, output = ? WHERE id = ?",
            ("Completed", result["output"], task_id),
        )
    return {"id": task_id, "status": "Completed", "provider": result["provider"],
            "model": result["model"], "output": result["output"]}

@app.get("/api/tasks")
def tasks():
    with db() as conn:
        rows = conn.execute(
            "SELECT id, prompt, workflow, status, created_at, output FROM tasks ORDER BY id DESC LIMIT 100"
        ).fetchall()
    return {"tasks": [dict(row) for row in rows]}

@app.get("/api/tasks/{task_id}")
def task_detail(task_id: int):
    with db() as conn:
        row = conn.execute(
            "SELECT id, prompt, workflow, status, created_at, output FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return dict(row)

@app.get("/api/export/{task_id}")
def export_task(task_id: int, format: str = "txt"):
    item = task_detail(task_id)
    if not item.get("output"):
        raise HTTPException(status_code=409, detail="Is task ka generated output available nahi hai.")
    if format not in {"txt", "md", "json"}:
        raise HTTPException(status_code=400, detail="format must be txt, md, or json")
    if format == "json":
        return JSONResponse(content={
            "product": "SINTU AI STUDIO",
            "task": {key: item[key] for key in ("id", "workflow", "status", "created_at", "prompt", "output")},
            "notice": "AI-generated production package; not a rendered or published video."
        }, headers={"Content-Disposition": f"attachment; filename=sintu-task-{task_id}.json"})
    if format == "md":
        content = (
            f"# SINTU AI STUDIO — {item['workflow']}\n\n"
            f"- Task: #{item['id']}\n- Created: {item['created_at']}\n"
            f"- Status: {item['status']}\n\n## Prompt\n\n{item['prompt']}\n\n"
            f"## Production package\n\n{item['output']}\n\n"
            "> Note: AI-generated production package; not a rendered or published video.\n"
        )
        media_type, extension = "text/markdown; charset=utf-8", "md"
    else:
        content = (
            f"SINTU AI STUDIO — {item['workflow']}\n"
            f"Task: #{item['id']}\nCreated: {item['created_at']}\n"
            f"Prompt: {item['prompt']}\n\n{'=' * 60}\n\n{item['output']}\n"
        )
        media_type, extension = "text/plain; charset=utf-8", "txt"
    return StreamingResponse(
        io.BytesIO(content.encode("utf-8")),
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename=sintu-task-{task_id}.{extension}"},
    )


@app.get("/api/render/capabilities")
def render_capabilities():
    return {
        "available": bool(shutil.which("ffmpeg")),
        "renderer": "FFmpeg + Pillow storyboard renderer",
        "supported_output": "Silent 720x1280 portrait MP4 (H.264)",
        "limitations": ["text scene cards only", "no generated images", "no voiceover", "no music"],
    }


@app.post("/api/render")
def render_video(payload: RenderInput):
    title = payload.title.strip()
    scenes = [scene.strip() for scene in payload.scenes]
    if not title or any(not scene or len(scene) > 500 for scene in scenes):
        raise HTTPException(status_code=400, detail="Title and all scenes must contain valid text (max 500 characters per scene).")
    try:
        return render_storyboard(title, scenes, payload.seconds_per_scene)
    except RendererUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except RenderFailed as exc:
        raise HTTPException(status_code=502, detail=f"Video render failed: {exc}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/videos/{video_id}")
def get_video(video_id: str):
    if not re.fullmatch(r"[a-f0-9]{32}", video_id):
        raise HTTPException(status_code=400, detail="Invalid video ID")
    path = OUTPUT_DIR / f"{video_id}.mp4"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Video not found")
    return FileResponse(path, media_type="video/mp4", filename=f"sintu-{video_id}.mp4")


@app.get("/api/status")
def status():
    with db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        completed = conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'Completed'").fetchone()[0]
    providers = provider_status()
    configured = providers["openai"]["configured"] or providers["gemini"]["configured"]
    return {
        "agents_total": len(list_agents()),
        "agents_implemented": 0,
        "roles_routed": orchestration_summary()["roles_routed"],
        "orchestration_mode": orchestration_summary()["execution_mode"],
        "workflows_available": len(WORKFLOW_GUIDES),
        "tasks_saved": count,
        "tasks_completed": completed,
        "ai_provider_configured": configured,
        "video_generation": "Not configured",
        "publishing": "Not configured",
    }
