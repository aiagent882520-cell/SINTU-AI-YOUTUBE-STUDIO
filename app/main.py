from pathlib import Path
import os
import base64
import hashlib
import hmac
import json
import time
import io
import sqlite3
import re
import shutil
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agents import list_agents
from .agent_orchestrator import workflow_team, orchestration_summary
from .ai_brain import ProviderNotConfigured, ProviderRequestError, generate_text, provider_status, WORKFLOW_GUIDES
from .video_renderer import render_storyboard, render_ai_clips, render_mixed_timeline, RendererUnavailable, RenderFailed, OUTPUT_DIR
from .voice_generator import generate_voiceover, voice_status, VoiceUnavailable, VoiceGenerationFailed, AUDIO_DIR
from .image_generator import generate_image, image_status, ImageUnavailable, ImageGenerationFailed, IMAGE_DIR
from .music_generator import generate_music, music_status, MusicUnavailable, MusicGenerationFailed
from .video_generator import generate_video, video_status, VideoUnavailable, VideoGenerationFailed, AI_VIDEO_DIR

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("SINTU_DATA_DIR", str(ROOT.parent))).expanduser().resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "sintu_studio.db"
STATIC = ROOT / "static"
MUSIC_DIR = DATA_DIR / "generated_music"
ALLOWED_MUSIC_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg"}

app = FastAPI(title="SINTU AI STUDIO", version="0.3.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

SESSION_COOKIE = "sintu_admin_session"
SESSION_TTL_SECONDS = 12 * 60 * 60
_LOGIN_ATTEMPTS = {}


def _auth_required():
    return os.getenv("SINTU_AUTH_REQUIRED", "true").strip().lower() == "true"


def _session_secret():
    return os.getenv("SINTU_SESSION_SECRET", "")


def _hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 310000).hex()
    return "pbkdf2_sha256$310000$" + salt + "$" + digest


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256" or int(rounds) < 100000:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds)).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _ensure_bootstrap_admin():
    username = os.getenv("SINTU_ADMIN_USERNAME", "admin").strip()
    password = os.getenv("SINTU_ADMIN_PASSWORD", "")
    secret = _session_secret()
    if not username or len(password) < 12 or len(secret) < 32 or password.startswith("CHANGE-THIS") or secret.startswith("CHANGE-THIS"):
        return
    with db() as conn:
        exists = conn.execute("SELECT id FROM admin_users WHERE username = ?", (username,)).fetchone()
        if not exists:
            conn.execute("INSERT INTO admin_users(username,password_hash,role,is_active,created_at) VALUES(?,?,?,?,?)",
                         (username, _hash_password(password), "admin", 1, datetime.now(timezone.utc).isoformat()))


def _session_user(token: str | None):
    if not token or not _session_secret():
        return None
    try:
        payload, signature = token.rsplit(".", 1)
        expected = hmac.new(_session_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        decoded = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if int(decoded.get("e", 0)) <= int(time.time()):
            return None
        with db() as conn:
            row = conn.execute("SELECT id,username,role,is_active FROM admin_users WHERE id=?", (decoded.get("i"),)).fetchone()
        if not row or not row["is_active"] or row["username"] != decoded.get("u"):
            return None
        return dict(row)
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def _session_token(user: dict, expires: int) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"i": user["id"], "u": user["username"], "e": expires}, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(_session_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()
    return payload + "." + signature


def _valid_session(token: str | None) -> bool:
    return _session_user(token) is not None


def _write_audit(user, action: str, method: str, path: str, status: int, ip: str):
    try:
        actor = user or {}
        with db() as conn:
            conn.execute("INSERT INTO security_audit(actor_id,actor_username,actor_role,action,method,path,status_code,ip_address,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                         (actor.get("id"), actor.get("username", "anonymous"), actor.get("role", "guest"), action, method, path, status, ip[:64], datetime.now(timezone.utc).isoformat()))
    except sqlite3.Error:
        pass


@app.middleware("http")
async def admin_access_control(request, call_next):
    path = request.url.path
    user = _session_user(request.cookies.get(SESSION_COOKIE)) if _auth_required() else {"id": 0, "username": "local", "role": "admin", "is_active": 1}
    request.state.user = user
    if _auth_required():
        public_paths = {"/login", "/api/auth/login", "/api/auth/logout", "/api/health"}
        if path not in public_paths and not path.startswith("/static/") and not user:
            if path == "/":
                from fastapi.responses import RedirectResponse
                return RedirectResponse("/login", status_code=303)
            return JSONResponse(status_code=401, content={"detail": "Admin login required."})
        if path.startswith("/api/admin/") and (not user or user.get("role") != "admin"):
            return JSONResponse(status_code=403, content={"detail": "Admin role required."})
        if request.method not in {"GET", "HEAD", "OPTIONS"} and path != "/api/auth/logout" and user and user.get("role") == "viewer":
            return JSONResponse(status_code=403, content={"detail": "Viewer role is read-only."})
        if request.method in {"PUT", "PATCH", "DELETE"} and user and user.get("role") == "editor":
            return JSONResponse(status_code=403, content={"detail": "Editor role cannot perform destructive or administrative changes."})
    response = await call_next(request)
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and path != "/api/admin/audit":
        actor = getattr(request.state, "user", None)
        client_ip = request.client.host if request.client else "unknown"
        _write_audit(actor, "http_request", request.method, path, response.status_code, client_ip)
    return response


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
        conn.execute("""CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','editor','viewer')),
            is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS security_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id INTEGER, actor_username TEXT NOT NULL,
            actor_role TEXT NOT NULL, action TEXT NOT NULL, method TEXT NOT NULL, path TEXT NOT NULL,
            status_code INTEGER NOT NULL, ip_address TEXT NOT NULL, created_at TEXT NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_security_audit_created ON security_audit(id DESC)")
    _ensure_bootstrap_admin()

init_db()

class TaskInput(BaseModel):
    prompt: str = Field(min_length=1, max_length=10000)
    workflow: str = Field(default="content", max_length=80)

class RenderInput(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    scenes: list[str] = Field(min_length=1, max_length=25)
    seconds_per_scene: int = Field(default=4, ge=2, le=12)
    image_ids: list[str] = Field(default_factory=list, max_length=25)
    video_ids: list[str] = Field(default_factory=list, max_length=25)
    timeline: list[str] = Field(default_factory=list, max_length=25)
    audio_id: str | None = Field(default=None, max_length=32)
    subtitles: list[str] = Field(default_factory=list, max_length=25)
    music_id: str | None = Field(default=None, max_length=32)
    music_volume: float = Field(default=0.18, ge=0, le=1)
    transition: str = Field(default="fade", max_length=10)
    motion: str = Field(default="none", max_length=20)
    resolution: str = Field(default="720x1280", max_length=12)
    fps: int = Field(default=30, ge=24, le=60)
    quality: str = Field(default="high", max_length=12)

class MusicUploadInput(BaseModel):
    filename: str = Field(min_length=1, max_length=120)
    data_base64: str = Field(min_length=1, max_length=21_000_000)

class MusicGenerateInput(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    duration_seconds: int = Field(default=30, ge=5, le=360)

class AIVideoInput(BaseModel):
    prompt: str = Field(min_length=1, max_length=3000)
    aspect_ratio: str = Field(default="9:16", max_length=5)
    resolution: str = Field(default="720p", max_length=5)
    style: str = Field(default="cinematic", max_length=20)
    reference_image_id: str | None = Field(default=None, max_length=32)
    duration_seconds: int = Field(default=8, ge=3, le=10)

class ImageInput(BaseModel):
    prompt: str = Field(min_length=1, max_length=3000)
    kind: str = Field(default="scene", max_length=20)
    aspect: str = Field(default="portrait", max_length=20)

class VoiceInput(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    voice: str = Field(default="alloy", max_length=20)

class SubtitleInput(BaseModel):
    scenes: list[str] = Field(min_length=1, max_length=100)
    seconds_per_scene: int = Field(default=4, ge=1, le=60)

@app.get("/login", include_in_schema=False)
def login_page():
    return FileResponse(STATIC / "login.html")


class AdminLoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=256)
    role: str = Field(default="viewer", pattern=r"^(admin|editor|viewer)$")


class AdminUserUpdate(BaseModel):
    role: str | None = Field(default=None, pattern=r"^(admin|editor|viewer)$")
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=12, max_length=256)


@app.post("/api/auth/login")
def admin_login(payload: AdminLoginInput, request: Request):
    if (len(os.getenv("SINTU_ADMIN_PASSWORD", "")) < 12
            or len(_session_secret()) < 32
            or os.getenv("SINTU_ADMIN_PASSWORD", "").startswith("CHANGE-THIS")
            or _session_secret().startswith("CHANGE-THIS")):
        raise HTTPException(status_code=503, detail="Admin credentials and a 32+ character session secret must be configured by the host administrator.")
    _ensure_bootstrap_admin()
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    attempts = [stamp for stamp in _LOGIN_ATTEMPTS.get(client_ip, []) if now - stamp < 900]
    if len(attempts) >= 10:
        raise HTTPException(status_code=429, detail="Too many login attempts. 15 minutes baad try karein.")
    with db() as conn:
        user = conn.execute("SELECT id,username,password_hash,role,is_active FROM admin_users WHERE username=?", (payload.username,)).fetchone()
    if not user or not user["is_active"] or not _verify_password(payload.password, user["password_hash"]):
        attempts.append(now)
        _LOGIN_ATTEMPTS[client_ip] = attempts
        raise HTTPException(status_code=401, detail="Username ya password galat hai.")
    _LOGIN_ATTEMPTS.pop(client_ip, None)
    actor = dict(user)
    request.state.user = actor
    response = JSONResponse({"authenticated": True, "username": actor["username"], "role": actor["role"], "expires_in": SESSION_TTL_SECONDS})
    response.set_cookie(SESSION_COOKIE, _session_token(actor, int(now + SESSION_TTL_SECONDS)),
                        max_age=SESSION_TTL_SECONDS, httponly=True, secure=os.getenv("SINTU_COOKIE_SECURE", "true").lower() == "true",
                        samesite="strict", path="/")
    return response


@app.post("/api/auth/logout")
def admin_logout():
    response = JSONResponse({"authenticated": False})
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True,
                           secure=os.getenv("SINTU_COOKIE_SECURE", "true").lower() == "true", samesite="strict")
    return response


@app.get("/api/auth/session")
def admin_session(request: Request):
    user = _session_user(request.cookies.get(SESSION_COOKIE))
    return {"authenticated": bool(user), "username": user["username"] if user else None, "role": user["role"] if user else None}


@app.get("/api/admin/users")
def admin_list_users():
    with db() as conn:
        rows = conn.execute("SELECT id,username,role,is_active,created_at FROM admin_users ORDER BY id").fetchall()
    return {"users": [dict(row) for row in rows]}


@app.post("/api/admin/users")
def admin_create_user(payload: AdminUserCreate):
    now = datetime.now(timezone.utc).isoformat()
    try:
        with db() as conn:
            cur = conn.execute("INSERT INTO admin_users(username,password_hash,role,is_active,created_at) VALUES(?,?,?,?,?)",
                               (payload.username, _hash_password(payload.password), payload.role, 1, now))
            user_id = cur.lastrowid
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Username already exists.")
    return {"id": user_id, "username": payload.username, "role": payload.role, "is_active": True}


@app.patch("/api/admin/users/{user_id}")
def admin_update_user(user_id: int, payload: AdminUserUpdate, request: Request):
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="At least one user field is required.")
    actor = getattr(request.state, "user", {}) or {}
    with db() as conn:
        target = conn.execute("SELECT id,username,role,is_active FROM admin_users WHERE id=?", (user_id,)).fetchone()
        if not target:
            raise HTTPException(status_code=404, detail="User not found.")
        if actor.get("id") == user_id and (changes.get("is_active") is False or changes.get("role", target["role"]) != "admin"):
            raise HTTPException(status_code=400, detail="You cannot disable or demote your own active admin account.")
        next_role = changes.get("role", target["role"])
        next_active = changes.get("is_active", bool(target["is_active"]))
        if target["role"] == "admin" and target["is_active"] and (next_role != "admin" or not next_active):
            count = conn.execute("SELECT COUNT(*) AS n FROM admin_users WHERE role='admin' AND is_active=1").fetchone()["n"]
            if count <= 1:
                raise HTTPException(status_code=400, detail="At least one active admin account must remain.")
        updates, values = [], []
        if "role" in changes: updates.append("role=?"); values.append(changes["role"])
        if "is_active" in changes: updates.append("is_active=?"); values.append(1 if changes["is_active"] else 0)
        if changes.get("password"): updates.append("password_hash=?"); values.append(_hash_password(changes["password"]))
        values.append(user_id)
        conn.execute("UPDATE admin_users SET " + ", ".join(updates) + " WHERE id=?", values)
        row = conn.execute("SELECT id,username,role,is_active,created_at FROM admin_users WHERE id=?", (user_id,)).fetchone()
    return dict(row)


@app.get("/api/admin/audit")
def admin_audit(limit: int = 50):
    limit = max(1, min(limit, 200))
    with db() as conn:
        rows = conn.execute("SELECT id,actor_username,actor_role,action,method,path,status_code,ip_address,created_at FROM security_audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return {"events": [dict(row) for row in rows]}


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
        "storyboard_renderer": {"available": bool(shutil.which("ffmpeg")), "output": "720x1280 MP4 with optional scene images, narration, uploaded music and captions"},
        "voiceover": voice_status(),
        "image_generation": image_status(),
        "ai_music_generation": music_status(),
        "ai_video_generation": video_status(),
        "requires_external_integration": [
            "advanced_video_rendering", "youtube_oauth", "social_oauth",
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
    if payload.workflow not in WORKFLOW_GUIDES:
        raise HTTPException(status_code=400, detail="Unknown workflow. Choose an available workflow.")
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
        "supported_output": "MP4 / H.264; selectable 720x1280, 1080x1920, 1080x1080, 1280x720, 1920x1080; 24/30/60 FPS; standard/high/maximum CRF quality",
        "profiles": {"resolutions": ["720x1280", "1080x1920", "1080x1080", "1280x720", "1920x1080"], "fps": [24, 30, 60], "quality": ["standard", "high", "maximum"]},
        "limitations": ["background music is user-uploaded; music licensing remains user's responsibility", "basic slow zoom motion only; no advanced 2D/3D VFX", "FFmpeg must be installed"],
    }


@app.get("/api/music/capabilities")
def ai_music_capabilities():
    return music_status()

@app.post("/api/music/generate")
def create_ai_music(payload: MusicGenerateInput, media_token: str = Header(default="", alias="X-Media-Token")):
    import hmac, os
    expected = os.getenv("MEDIA_GENERATION_TOKEN", "")
    if not expected or not hmac.compare_digest(media_token, expected):
        raise HTTPException(status_code=403, detail="Valid media access token required.")
    try:
        return generate_music(payload.prompt, payload.duration_seconds)
    except MusicUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except MusicGenerationFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@app.get("/api/music/{music_id}")
def get_ai_music(music_id: str):
    if not re.fullmatch(r"[a-f0-9]{32}", music_id):
        raise HTTPException(status_code=400, detail="Invalid music ID")
    path = MUSIC_DIR / f"{music_id}.mp3"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Music not found")
    return FileResponse(path, media_type="audio/mpeg", filename=f"sintu-music-{music_id}.mp3")

@app.post("/api/music/upload")
def upload_music(payload: MusicUploadInput, media_token: str = Header(default="", alias="X-Media-Token")):
    import hmac, os
    expected = os.getenv("MEDIA_GENERATION_TOKEN", "")
    if not expected or not hmac.compare_digest(media_token, expected):
        raise HTTPException(status_code=403, detail="Valid media access token required.")
    suffix = Path(payload.filename).suffix.lower()
    if suffix not in ALLOWED_MUSIC_EXTENSIONS:
        raise HTTPException(status_code=400, detail="MP3, WAV, M4A, AAC ya OGG audio file upload karein.")
    try:
        raw = base64.b64decode(payload.data_base64, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid audio upload data.") from None
    if not raw or len(raw) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Audio file 15 MB se chhoti honi chahiye.")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise HTTPException(status_code=503, detail="Server par FFmpeg available nahi hai.")
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    import uuid
    music_id = uuid.uuid4().hex
    path = MUSIC_DIR / f"{music_id}{suffix}"
    path.write_bytes(raw)
    try:
        checked = shutil.which("ffprobe")
        if checked:
            import subprocess
            probe = subprocess.run([checked, "-v", "error", "-show_entries", "format=duration",
                                    "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                                   capture_output=True, text=True, timeout=15, check=False)
            if probe.returncode != 0 or not probe.stdout.strip():
                raise ValueError("Audio file decode nahi ho saki.")
        else:
            import subprocess
            probe = subprocess.run([ffmpeg, "-v", "error", "-i", str(path), "-t", "0.2",
                                    "-f", "null", "-"], capture_output=True, text=True, timeout=20, check=False)
            if probe.returncode != 0:
                raise ValueError("Audio file decode nahi ho saki.")
    except Exception:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Valid audio file upload karein.") from None
    return {"music_id": music_id, "filename": path.name, "format": suffix[1:].upper(),
            "size_bytes": len(raw), "notice": "Use only music you own or are licensed to use."}


@app.post("/api/render")
def render_video(payload: RenderInput):
    title = payload.title.strip()
    scenes = [scene.strip() for scene in payload.scenes]
    if not title or any(not scene or len(scene) > 500 for scene in scenes):
        raise HTTPException(status_code=400, detail="Title and all scenes must contain valid text (max 500 characters per scene).")
    if payload.image_ids and len(payload.image_ids) != len(scenes):
        raise HTTPException(status_code=400, detail="Har scene ke liye exactly ek image ID dein.")
    if payload.video_ids and len(payload.video_ids) != len(scenes):
        raise HTTPException(status_code=400, detail="Har scene ke liye exactly ek AI video ID dein.")
    if payload.video_ids and payload.image_ids:
        raise HTTPException(status_code=400, detail="AI video clips aur still-image storyboard ko ek render mein mix karna abhi supported nahi hai.")
    if payload.timeline and (payload.image_ids or payload.video_ids):
        raise HTTPException(status_code=400, detail="Mixed timeline use karte waqt alag image_ids/video_ids fields khaali rakhein.")
    if payload.timeline and len(payload.timeline) != len(scenes):
        raise HTTPException(status_code=400, detail="Har timeline item ke liye ek scene description dein.")
    if payload.subtitles and len(payload.subtitles) != len(scenes):
        raise HTTPException(status_code=400, detail="Subtitle lines ki sankhya scenes ke barabar honi chahiye.")
    if any((not line.strip() and not payload.timeline) or len(line) > 1000 for line in payload.subtitles):
        raise HTTPException(status_code=400, detail="Subtitle line 1000 characters se chhoti honi chahiye; mixed timeline mein blank captions allowed hain.")
    image_paths = []
    for image_id in payload.image_ids:
        if not re.fullmatch(r"[a-f0-9]{32}", image_id):
            raise HTTPException(status_code=400, detail="Invalid scene image ID.")
        path = IMAGE_DIR / f"{image_id}.jpg"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Scene image not found.")
        image_paths.append(path)
    video_paths = []
    for video_id in payload.video_ids:
        if not re.fullmatch(r"[a-f0-9]{32}", video_id):
            raise HTTPException(status_code=400, detail="Invalid AI video ID.")
        path = AI_VIDEO_DIR / f"{video_id}.mp4"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="AI video clip not found.")
        video_paths.append(path)
    audio_path = None
    if payload.transition not in {"cut", "fade"}:
        raise HTTPException(status_code=400, detail="Transition cut ya fade hona chahiye.")
    if payload.motion not in {"none", "slow-zoom-in", "slow-zoom-out"}:
        raise HTTPException(status_code=400, detail="Unsupported motion preset.")
    if payload.resolution not in {"720x1280", "1080x1920", "1080x1080", "1280x720", "1920x1080"}:
        raise HTTPException(status_code=400, detail="Unsupported output resolution profile.")
    if payload.fps not in {24, 30, 60}:
        raise HTTPException(status_code=400, detail="FPS 24, 30 ya 60 hona chahiye.")
    if payload.quality not in {"standard", "high", "maximum"}:
        raise HTTPException(status_code=400, detail="Quality standard, high ya maximum honi chahiye.")
    music_path = None
    if payload.music_id:
        if not re.fullmatch(r"[a-f0-9]{32}", payload.music_id):
            raise HTTPException(status_code=400, detail="Invalid background music ID.")
        matches = list(MUSIC_DIR.glob(payload.music_id + ".*"))
        if not matches or matches[0].suffix.lower() not in ALLOWED_MUSIC_EXTENSIONS:
            raise HTTPException(status_code=404, detail="Background music not found.")
        music_path = matches[0]
    audio_path = None
    if payload.audio_id:
        if not re.fullmatch(r"[a-f0-9]{32}", payload.audio_id):
            raise HTTPException(status_code=400, detail="Invalid voiceover audio ID.")
        audio_path = AUDIO_DIR / f"{payload.audio_id}.mp3"
        if not audio_path.is_file():
            raise HTTPException(status_code=404, detail="Voiceover audio not found.")
    try:
        if payload.timeline:
            timeline_items = []
            scene_transitions = []
            for entry in payload.timeline:
                video_with_volume = re.fullmatch(r"video:([a-f0-9]{32}):([^:]+):([^:]*):([^:]+):(cut|fade)", entry.strip())
                video_trim = re.fullmatch(r"video:([a-f0-9]{32}):([^:]+):([^:]*):(cut|fade)", entry.strip())
                video_legacy = re.fullmatch(r"video:([a-f0-9]{32}):0:(cut|fade)", entry.strip())
                image_match = re.fullmatch(r"image:([a-f0-9]{32}):(\d{1,2}):(cut|fade)", entry.strip())
                if video_with_volume:
                    asset_id, first_value, second_value, volume_text, transition_mode = video_with_volume.groups()
                    kind = "video"
                elif video_legacy:
                    asset_id, transition_mode = video_legacy.groups()
                    first_value, second_value, volume_text = "0", "", "0.25"
                    kind = "video"
                elif video_trim:
                    asset_id, first_value, second_value, transition_mode = video_trim.groups()
                    volume_text = "0.25"
                    kind = "video"
                elif image_match:
                    asset_id, first_value, transition_mode = image_match.groups()
                    second_value = "0"
                    volume_text = "0"
                    kind = "image"
                else:
                    raise HTTPException(status_code=400, detail="Timeline format image:ID:duration:transition ya video:ID:start:end:volume:transition hona chahiye.")
                if kind == "image":
                    try: duration = int(first_value)
                    except ValueError: raise HTTPException(status_code=400, detail="Image duration integer honi chahiye.") from None
                    if not 2 <= duration <= 12:
                        raise HTTPException(status_code=400, detail="Image scene duration 2 se 12 seconds honi chahiye.")
                    item = {"kind": kind, "path": IMAGE_DIR / f"{asset_id}.jpg", "duration": duration}
                else:
                    try:
                        trim_start = float(first_value or 0)
                        trim_end = float(second_value) if second_value else None
                        audio_volume = float(volume_text)
                    except ValueError:
                        raise HTTPException(status_code=400, detail="Video trim time aur audio volume valid number hone chahiye.") from None
                    if trim_start < 0 or (trim_end is not None and trim_end <= trim_start):
                        raise HTTPException(status_code=400, detail="Video trim end, start se bada hona chahiye.")
                    if not 0 <= audio_volume <= 2:
                        raise HTTPException(status_code=400, detail="Clip audio volume 0 se 200 percent ke beech hona chahiye.")
                    item = {"kind": kind, "path": AI_VIDEO_DIR / f"{asset_id}.mp4", "duration": 0,
                            "trim_start": trim_start, "trim_end": trim_end,
                            "audio_volume": audio_volume}
                if not item["path"].is_file():
                    raise HTTPException(status_code=404, detail=f"Timeline {kind} asset not found.")
                timeline_items.append(item)
                scene_transitions.append(transition_mode or payload.transition)
            if payload.motion != "none":
                raise HTTPException(status_code=400, detail="Mixed timeline mein abhi source clip motion use hota hai; extra zoom unsupported hai.")
            return render_mixed_timeline(timeline_items, title, scenes,
                                         seconds_per_scene=payload.seconds_per_scene,
                                         audio_path=audio_path, music_path=music_path,
                                         music_volume=payload.music_volume,
                                         subtitles=payload.subtitles, transition=payload.transition, transitions=scene_transitions,
                                         resolution=payload.resolution, fps=payload.fps, quality=payload.quality)
        if video_paths:
            if payload.motion != "none":
                raise HTTPException(status_code=400, detail="AI clip assembly mode mein source clips ka original motion use hota hai; extra zoom effects abhi supported nahi hain.")
            return render_ai_clips(video_paths, audio_path=audio_path, music_path=music_path,
                                   music_volume=payload.music_volume, subtitles=payload.subtitles,
                                   transition=payload.transition, resolution=payload.resolution,
                                   fps=payload.fps, quality=payload.quality)
        return render_storyboard(title, scenes, payload.seconds_per_scene,
                                 image_paths=image_paths, audio_path=audio_path,
                                 subtitles=payload.subtitles, music_path=music_path,
                                 music_volume=payload.music_volume, transition=payload.transition, motion=payload.motion,
                                 resolution=payload.resolution, fps=payload.fps, quality=payload.quality)
    except RendererUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except RenderFailed as exc:
        raise HTTPException(status_code=502, detail=f"Video render failed: {exc}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/video/capabilities")
def ai_video_capabilities():
    return video_status()


@app.post("/api/video/generate")
def create_ai_video(payload: AIVideoInput, media_token: str = Header(default="", alias="X-Media-Token")):
    import hmac, os
    expected = os.getenv("MEDIA_GENERATION_TOKEN", "")
    if not expected or not hmac.compare_digest(media_token, expected):
        raise HTTPException(status_code=403, detail="Valid media access token required.")
    if payload.aspect_ratio not in {"9:16", "16:9"}:
        raise HTTPException(status_code=400, detail="Aspect ratio 9:16 ya 16:9 hona chahiye.")
    if payload.resolution not in {"360p", "720p", "1080p", "4k"}:
        raise HTTPException(status_code=400, detail="Unsupported video resolution.")
    if payload.duration_seconds < 3 or payload.duration_seconds > 10:
        raise HTTPException(status_code=400, detail="Clip duration 3 se 10 seconds ke beech honi chahiye.")
    if payload.style not in {"cinematic", "2d-animation", "3d-animation", "documentary", "anime", "motion-graphics"}:
        raise HTTPException(status_code=400, detail="Unsupported video style.")
    try:
        return generate_video(payload.prompt, payload.aspect_ratio, payload.resolution,
                              payload.style, payload.reference_image_id, payload.duration_seconds)
    except VideoUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except VideoGenerationFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/ai-videos/{video_id}")
def get_ai_video(video_id: str):
    if not re.fullmatch(r"[a-f0-9]{32}", video_id):
        raise HTTPException(status_code=400, detail="Invalid AI video ID")
    path = AI_VIDEO_DIR / f"{video_id}.mp4"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="AI video not found")
    return FileResponse(path, media_type="video/mp4", filename=f"sintu-ai-{video_id}.mp4")


@app.get("/api/videos/{video_id}")
def get_video(video_id: str):
    if not re.fullmatch(r"[a-f0-9]{32}", video_id):
        raise HTTPException(status_code=400, detail="Invalid video ID")
    path = OUTPUT_DIR / f"{video_id}.mp4"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Video not found")
    return FileResponse(path, media_type="video/mp4", filename=f"sintu-{video_id}.mp4")


@app.get("/api/images/capabilities")
def image_capabilities():
    return image_status()


@app.post("/api/images")
def create_image(payload: ImageInput, media_token: str = Header(default="", alias="X-Media-Token")):
    import hmac, os
    expected = os.getenv("MEDIA_GENERATION_TOKEN", "")
    if not expected or not hmac.compare_digest(media_token, expected):
        raise HTTPException(status_code=403, detail="Valid media access token required.")
    try:
        return generate_image(payload.prompt, payload.kind, payload.aspect)
    except ImageUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ImageGenerationFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/images/{image_id}")
def get_image(image_id: str):
    if not re.fullmatch(r"[a-f0-9]{32}", image_id):
        raise HTTPException(status_code=400, detail="Invalid image ID")
    path = IMAGE_DIR / f"{image_id}.jpg"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(path, media_type="image/jpeg", filename=f"sintu-image-{image_id}.jpg")


@app.get("/api/voice/capabilities")
def voice_capabilities():
    return voice_status()


@app.post("/api/voice")
def create_voiceover(payload: VoiceInput, media_token: str = Header(default="", alias="X-Media-Token")):
    import hmac, os
    expected = os.getenv("MEDIA_GENERATION_TOKEN", "")
    if not expected or not hmac.compare_digest(media_token, expected):
        raise HTTPException(status_code=403, detail="Valid media access token required.")
    try:
        return generate_voiceover(payload.text, payload.voice)
    except VoiceUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except VoiceGenerationFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/audio/{audio_id}")
def get_audio(audio_id: str):
    if not re.fullmatch(r"[a-f0-9]{32}", audio_id):
        raise HTTPException(status_code=400, detail="Invalid audio ID")
    path = AUDIO_DIR / f"{audio_id}.mp3"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Audio not found")
    return FileResponse(path, media_type="audio/mpeg", filename=f"sintu-voice-{audio_id}.mp3")


def _srt_time(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},000"


@app.post("/api/subtitles")
def create_subtitles(payload: SubtitleInput):
    scenes = [scene.strip() for scene in payload.scenes]
    if any(not scene or len(scene) > 1000 for scene in scenes):
        raise HTTPException(status_code=400, detail="Each subtitle scene must contain 1 to 1000 characters.")
    chunks = []
    for index, scene in enumerate(scenes):
        start = index * payload.seconds_per_scene
        end = start + payload.seconds_per_scene
        chunks.append(f"{index + 1}\n{_srt_time(start)} --> {_srt_time(end)}\n{scene}")
    content = "\n\n".join(chunks) + "\n"
    return StreamingResponse(
        io.BytesIO(content.encode("utf-8")),
        media_type="application/x-subrip; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="sintu-subtitles.srt"'},
    )


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
