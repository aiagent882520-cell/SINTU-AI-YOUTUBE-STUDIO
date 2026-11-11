from pathlib import Path
import os
import base64
import hashlib
import hmac
import json
import time
import io
import csv
import gzip
import sqlite3
import re
import shutil
import secrets
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from cryptography.fernet import Fernet, InvalidToken

from fastapi import FastAPI, HTTPException, Header, Request, Query, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agents import list_agents
from .production_catalog import production_catalog
from .studio_scope import agent_registry, production_plan, scope_summary
from . import studio_engine
from .policy import paid_upgrades_allowed
from .blender_renderer import BLENDER_DIR, blender_status, render_scene, BlenderUnavailable, BlenderRenderFailed
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


def _record_publish_event(calendar_id: int, platform: str, status: str,
                          external_id: str | None = None, detail: str = "", post_url: str = ""):
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        latest = conn.execute("SELECT status,external_id FROM publishing_history WHERE calendar_id=? ORDER BY id DESC LIMIT 1",
                              (calendar_id,)).fetchone()
        if latest and latest["status"] == status and latest["external_id"] == external_id:
            return
        conn.execute("""INSERT INTO publishing_history(calendar_id,platform,status,external_id,detail,post_url,created_at)
            VALUES(?,?,?,?,?,?,?)""",
            (calendar_id, platform, status, external_id, str(detail or "")[:1000], str(post_url or "")[:2048], now))

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
        conn.execute("""CREATE TABLE IF NOT EXISTS app_settings (
            setting_key TEXT PRIMARY KEY, setting_value TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS content_calendar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL, platform TEXT NOT NULL, prompt TEXT NOT NULL,
            scheduled_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Needs approval',
            created_at TEXT NOT NULL, approved_at TEXT
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_content_calendar_date ON content_calendar(scheduled_at)")
        conn.execute("""CREATE TABLE IF NOT EXISTS youtube_oauth_states (
            state TEXT PRIMARY KEY, admin_user_id INTEGER NOT NULL, session_hash TEXT NOT NULL, expires_at INTEGER NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS youtube_connection (
            id INTEGER PRIMARY KEY CHECK(id=1), channel_id TEXT NOT NULL, channel_title TEXT NOT NULL,
            encrypted_tokens TEXT NOT NULL, token_expiry INTEGER NOT NULL, connected_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS meta_oauth_states (
            state TEXT PRIMARY KEY, admin_user_id INTEGER NOT NULL, session_hash TEXT NOT NULL, expires_at INTEGER NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS meta_connection (
            id INTEGER PRIMARY KEY CHECK(id=1), page_id TEXT NOT NULL, page_name TEXT NOT NULL,
            instagram_user_id TEXT, instagram_username TEXT, encrypted_tokens TEXT NOT NULL, connected_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS tiktok_oauth_states (
            state TEXT PRIMARY KEY, admin_user_id INTEGER NOT NULL, session_hash TEXT NOT NULL, expires_at INTEGER NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS tiktok_connection (
            id INTEGER PRIMARY KEY CHECK(id=1), open_id TEXT NOT NULL, display_name TEXT NOT NULL,
            encrypted_tokens TEXT NOT NULL, token_expiry INTEGER NOT NULL, refresh_expiry INTEGER NOT NULL,
            scopes TEXT NOT NULL, connected_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS tiktok_posts (
            publish_id TEXT PRIMARY KEY, calendar_id INTEGER NOT NULL, status TEXT NOT NULL,
            status_detail TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS publishing_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, calendar_id INTEGER NOT NULL, platform TEXT NOT NULL,
            status TEXT NOT NULL, external_id TEXT, detail TEXT NOT NULL DEFAULT '', post_url TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_publishing_history_created ON publishing_history(id DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_publishing_history_platform_status ON publishing_history(platform,status)")
        conn.execute("""CREATE TABLE IF NOT EXISTS youtube_comment_reviews (
            comment_id TEXT PRIMARY KEY, video_id TEXT NOT NULL, review_status TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_youtube_comment_reviews_status ON youtube_comment_reviews(review_status,updated_at DESC)")
        conn.execute("""CREATE TABLE IF NOT EXISTS youtube_comment_review_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            comment_id TEXT NOT NULL,
            video_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            previous_status TEXT NOT NULL DEFAULT '',
            new_status TEXT NOT NULL,
            note_changed INTEGER NOT NULL DEFAULT 0,
            changed_at TEXT NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_youtube_comment_review_history_comment ON youtube_comment_review_history(comment_id,changed_at DESC)")
        history_columns = {row["name"] for row in conn.execute("PRAGMA table_info(youtube_comment_review_history)").fetchall()}
        for column, definition in {
            "previous_assigned_to": "TEXT NOT NULL DEFAULT ''",
            "new_assigned_to": "TEXT NOT NULL DEFAULT ''",
            "previous_follow_up_at": "TEXT NOT NULL DEFAULT ''",
            "new_follow_up_at": "TEXT NOT NULL DEFAULT ''",
        }.items():
            if column not in history_columns:
                conn.execute(f"ALTER TABLE youtube_comment_review_history ADD COLUMN {column} {definition}")
        review_columns = {row["name"] for row in conn.execute("PRAGMA table_info(youtube_comment_reviews)").fetchall()}
        for column, definition in {
            "author": "TEXT NOT NULL DEFAULT ''",
            "comment_text": "TEXT NOT NULL DEFAULT ''",
            "published_at": "TEXT NOT NULL DEFAULT ''",
            "likes": "INTEGER NOT NULL DEFAULT 0",
            "classification": "TEXT NOT NULL DEFAULT 'other'",
            "assigned_to": "TEXT NOT NULL DEFAULT ''",
            "follow_up_at": "TEXT NOT NULL DEFAULT ''",
        }.items():
            if column not in review_columns:
                conn.execute(f"ALTER TABLE youtube_comment_reviews ADD COLUMN {column} {definition}")
    _ensure_bootstrap_admin()

init_db()

class TaskInput(BaseModel):
    prompt: str = Field(min_length=1, max_length=10000)
    workflow: str = Field(default="content", max_length=80)

class YouTubeCommentReviewInput(BaseModel):
    comment_id: str = Field(min_length=1, max_length=200)
    video_id: str = Field(min_length=11, max_length=20, pattern=r"^[A-Za-z0-9_-]+$")
    review_status: str = Field(pattern=r"^(pending|reviewed|follow_up|resolved)$")
    notes: str = Field(default="", max_length=1000)
    author: str = Field(default="", max_length=200)
    text: str = Field(default="", max_length=5000)
    published_at: str = Field(default="", max_length=40)
    likes: int = Field(default=0, ge=0, le=100000000)
    classification: str = Field(default="other", pattern=r"^(possible_spam|positive|negative|question|other)$")
    assigned_to: str = Field(default="", max_length=120)
    follow_up_at: str = Field(default="", max_length=40)


class YouTubeCommentBulkReviewInput(BaseModel):
    comment_ids: list[str] = Field(min_length=1, max_length=100)
    review_status: str = Field(pattern=r"^(pending|reviewed|follow_up|resolved)$")


class YouTubeCommentAssignmentInput(BaseModel):
    comment_ids: list[str] = Field(min_length=1, max_length=100)
    assigned_to: str = Field(max_length=120)
    follow_up_at: str = Field(default="", max_length=40)


class CalendarItemInput(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    platform: str = Field(pattern=r"^(youtube|youtube_shorts|instagram|facebook|tiktok|website)$")
    prompt: str = Field(min_length=1, max_length=10000)
    scheduled_at: str = Field(min_length=20, max_length=40)

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
                        samesite="lax", path="/")
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


def _get_app_setting(key: str, default: str = "") -> str:
    with db() as conn:
        row = conn.execute("SELECT setting_value FROM app_settings WHERE setting_key=?", (key,)).fetchone()
    return row["setting_value"] if row else default


def _set_app_setting(key: str, value: str):
    with db() as conn:
        conn.execute("""INSERT INTO app_settings(setting_key,setting_value,updated_at)
            VALUES(?,?,?) ON CONFLICT(setting_key) DO UPDATE SET
            setting_value=excluded.setting_value, updated_at=excluded.updated_at""",
            (key, value, datetime.now(timezone.utc).isoformat()))


class ProviderSettingsInput(BaseModel):
    selected_provider: str = Field(pattern=r"^(auto|local|openai|gemini)$")


@app.get("/api/admin/provider-settings")
def admin_provider_settings():
    selected = _get_app_setting("selected_provider", os.getenv("AI_PROVIDER", "local").lower())
    status = provider_status(selected)
    return {
        "selected_provider": status["selected"],
        "providers": {
            key: {"configured": value["configured"], "model": value["model"]}
            for key, value in status.items() if key in {"local", "openai", "gemini"}
        },
        "secret_policy": "API keys are read only from server environment variables and are never accepted or returned by this dashboard."
    }


@app.patch("/api/admin/provider-settings")
def update_admin_provider_settings(payload: ProviderSettingsInput):
    status = provider_status(payload.selected_provider)
    if payload.selected_provider in {"openai", "gemini"} and not paid_upgrades_allowed():
        raise HTTPException(status_code=403, detail="Paid upgrade locked until SINTU earns revenue and the user explicitly approves it.")
    if payload.selected_provider in {"openai", "gemini"} and not status[payload.selected_provider]["configured"]:
        raise HTTPException(status_code=400, detail=f"{payload.selected_provider} API key server par configured nahi hai.")
    _set_app_setting("selected_provider", payload.selected_provider)
    return admin_provider_settings()


@app.get("/api/admin/integrations")
def admin_integrations():
    providers = admin_provider_settings()
    paid_media = os.getenv("ENABLE_PAID_MEDIA_GENERATION", "false").lower() == "true" and paid_upgrades_allowed()
    media_token = bool(os.getenv("MEDIA_GENERATION_TOKEN"))
    ffmpeg = bool(shutil.which("ffmpeg"))
    return {
        "text_ai": {"status": "ready" if any(x["configured"] for x in providers["providers"].values()) else "needs_server_key", "selected": providers["selected_provider"], "providers": providers["providers"]},
        "video_rendering": {"status": "ready" if ffmpeg else "needs_ffmpeg"},
        "paid_media_generation": {"status": "enabled" if paid_media and media_token else "disabled", "provider_keys_present": {"openai": bool(os.getenv("OPENAI_API_KEY")), "gemini": bool(os.getenv("GEMINI_API_KEY")), "stability": bool(os.getenv("STABILITY_API_KEY"))}},
        "youtube_publishing": {"status": "connected" if _youtube_connection() else ("needs_credentials" if not (_youtube_config()["client_id"] and _youtube_config()["client_secret"] and _youtube_config()["redirect_uri"] and _youtube_config()["encryption_key"]) else "not_connected"), "note": "Google OAuth channel connection and manual approved MP4 upload endpoints are available; server credentials required."},
        "social_publishing": {"status": "connected" if _meta_connection() else ("needs_credentials" if not (_meta_config()["app_id"] and _meta_config()["app_secret"] and _meta_config()["redirect_uri"] and _meta_config()["encryption_key"]) else "not_connected"), "note": "Meta OAuth: Facebook Page video upload and Instagram Reels (public HTTPS video URL) are available; server app credentials and Meta permissions required."},
        "analytics": {"status": "not_connected", "note": "Channel analytics connection not implemented."},
        "other_text_providers": {"status": "not_connected", "providers": ["Claude", "DeepSeek", "GLM", "Doubao", "Kimi"]}
    }


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



class ProductionProjectInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    brief: str = Field(min_length=1, max_length=12000)
    format_id: str = Field(min_length=1, max_length=80)
    language: str = Field(default="Hindi", min_length=1, max_length=40)
    duration_seconds: int = Field(default=60, ge=5, le=7200)


class ProductionProjectGenerateInput(BaseModel):
    workflow: str = Field(default="content", min_length=1, max_length=80)


def _ensure_production_projects_table():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS production_projects (
                id TEXT PRIMARY KEY,
                owner_username TEXT NOT NULL,
                name TEXT NOT NULL,
                brief TEXT NOT NULL,
                format_id TEXT NOT NULL,
                language TEXT NOT NULL,
                duration_seconds INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'Draft',
                version INTEGER NOT NULL DEFAULT 1,
                last_task_id INTEGER,
                last_task_status TEXT,
                last_task_updated_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_production_projects_owner_updated ON production_projects(owner_username, updated_at DESC)")
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(production_projects)").fetchall()}
        for column, declaration in (("last_task_id", "INTEGER"), ("last_task_status", "TEXT"), ("last_task_updated_at", "TEXT")):
            if column not in columns:
                conn.execute(f"ALTER TABLE production_projects ADD COLUMN {column} {declaration}")


def _validate_production_project_payload(payload: ProductionProjectInput):
    if not payload.name.strip() or not payload.brief.strip() or not payload.language.strip():
        raise HTTPException(status_code=400, detail="Project name, brief and language cannot be blank.")


def _production_project_owner(request: Request) -> str:
    user = getattr(request.state, "user", None) or {}
    return str(user.get("username") or "local")[:120]


def _production_project_dict(row):
    return dict(row) if row else None


@app.get("/api/projects")
def list_production_projects(request: Request, limit: int = Query(default=100, ge=1, le=200)):
    _ensure_production_projects_table()
    owner = _production_project_owner(request)
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM production_projects WHERE owner_username=? ORDER BY updated_at DESC LIMIT ?",
            (owner, limit)
        ).fetchall()
    return {"projects": [_production_project_dict(row) for row in rows], "total": len(rows), "storage": "server"}


@app.post("/api/projects", status_code=201)
def create_production_project(payload: ProductionProjectInput, request: Request):
    _validate_production_project_payload(payload)
    _ensure_production_projects_table()
    valid_formats = {item["id"] for item in production_catalog()["formats"]}
    if payload.format_id not in valid_formats:
        raise HTTPException(status_code=400, detail="Unknown production format.")
    now = datetime.now(timezone.utc).isoformat()
    project_id = secrets.token_hex(16)
    owner = _production_project_owner(request)
    with db() as conn:
        conn.execute("""
            INSERT INTO production_projects
            (id,owner_username,name,brief,format_id,language,duration_seconds,status,version,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,'Draft',1,?,?)
        """, (project_id, owner, payload.name.strip(), payload.brief.strip(),
              payload.format_id, payload.language.strip(), payload.duration_seconds, now, now))
        row = conn.execute("SELECT * FROM production_projects WHERE id=?", (project_id,)).fetchone()
    return {"project": _production_project_dict(row), "storage": "server"}


@app.get("/api/projects/{project_id}")
def get_production_project(project_id: str, request: Request):
    if not re.fullmatch(r"[a-f0-9]{32}", project_id):
        raise HTTPException(status_code=400, detail="Invalid project ID.")
    _ensure_production_projects_table()
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM production_projects WHERE id=? AND owner_username=?",
            (project_id, _production_project_owner(request))
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Project not found.")
    return {"project": _production_project_dict(row)}


@app.put("/api/projects/{project_id}")
def update_production_project(project_id: str, payload: ProductionProjectInput, request: Request):
    _validate_production_project_payload(payload)
    if not re.fullmatch(r"[a-f0-9]{32}", project_id):
        raise HTTPException(status_code=400, detail="Invalid project ID.")
    _ensure_production_projects_table()
    valid_formats = {item["id"] for item in production_catalog()["formats"]}
    if payload.format_id not in valid_formats:
        raise HTTPException(status_code=400, detail="Unknown production format.")
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        cursor = conn.execute("""
            UPDATE production_projects
            SET name=?,brief=?,format_id=?,language=?,duration_seconds=?,version=version+1,updated_at=?
            WHERE id=? AND owner_username=?
        """, (payload.name.strip(), payload.brief.strip(), payload.format_id,
              payload.language.strip(), payload.duration_seconds, now,
              project_id, _production_project_owner(request)))
        if cursor.rowcount != 1:
            raise HTTPException(status_code=404, detail="Project not found.")
        row = conn.execute("SELECT * FROM production_projects WHERE id=?", (project_id,)).fetchone()
    return {"project": _production_project_dict(row), "storage": "server"}


@app.delete("/api/projects/{project_id}")
def delete_production_project(project_id: str, request: Request):
    if not re.fullmatch(r"[a-f0-9]{32}", project_id):
        raise HTTPException(status_code=400, detail="Invalid project ID.")
    _ensure_production_projects_table()
    with db() as conn:
        cursor = conn.execute(
            "DELETE FROM production_projects WHERE id=? AND owner_username=?",
            (project_id, _production_project_owner(request))
        )
    if cursor.rowcount != 1:
        raise HTTPException(status_code=404, detail="Project not found.")
    return {"deleted": True, "id": project_id}



@app.post("/api/projects/{project_id}/generate")
def generate_production_project(project_id: str, payload: ProductionProjectGenerateInput, request: Request):
    if not re.fullmatch(r"[a-f0-9]{32}", project_id):
        raise HTTPException(status_code=400, detail="Invalid project ID.")
    _ensure_production_projects_table()
    owner = _production_project_owner(request)
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM production_projects WHERE id=? AND owner_username=?",
            (project_id, owner)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Project not found.")
    project = _production_project_dict(row)
    if payload.workflow not in WORKFLOW_GUIDES:
        raise HTTPException(status_code=400, detail="Unknown AI workflow.")
    format_info = next((item for item in production_catalog()["formats"] if item["id"] == project["format_id"]), None)
    prompt = (
        project["brief"] + "\n\nProduction format: " + (format_info["name"] if format_info else project["format_id"]) +
        "\nLanguage: " + project["language"] +
        "\nTarget duration: " + str(project["duration_seconds"]) +
        " seconds. Return a complete production package with scene-by-scene narration, visuals, on-screen text, sound cues, CTA, and publishing metadata."
    )
    if len(prompt) > 10000:
        raise HTTPException(status_code=400, detail="Brief bahut lamba hai. AI generation ke liye ise 9,000 characters se chhota karein.")
    try:
        task = generate(TaskInput(prompt=prompt, workflow=payload.workflow))
    except HTTPException as exc:
        if exc.status_code in (502, 503):
            failed_at = datetime.now(timezone.utc).isoformat()
            with db() as conn:
                conn.execute("UPDATE production_projects SET last_task_status=?,last_task_updated_at=? WHERE id=? AND owner_username=?", ("Blocked" if exc.status_code == 503 else "Failed", failed_at, project_id, owner))
        raise
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        conn.execute(
            "UPDATE production_projects SET last_task_id=?,last_task_status=?,last_task_updated_at=?,updated_at=?,version=version+1 WHERE id=? AND owner_username=?",
            (task["id"], task["status"], now, now, project_id, owner)
        )
        updated = conn.execute("SELECT * FROM production_projects WHERE id=?", (project_id,)).fetchone()
    return {"project": _production_project_dict(updated), "task": task}



@app.get("/api/projects/{project_id}/task-output")
def get_production_project_task_output(project_id: str, request: Request):
    if not re.fullmatch(r"[a-f0-9]{32}", project_id):
        raise HTTPException(status_code=400, detail="Invalid project ID.")
    _ensure_production_projects_table()
    with db() as conn:
        project = conn.execute(
            "SELECT last_task_id FROM production_projects WHERE id=? AND owner_username=?",
            (project_id, _production_project_owner(request))
        ).fetchone()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found.")
        if not project["last_task_id"]:
            raise HTTPException(status_code=404, detail="This project has no generated task yet.")
        task = conn.execute(
            "SELECT id,prompt,workflow,status,output,created_at FROM tasks WHERE id=?",
            (project["last_task_id"],)
        ).fetchone()
    if not task:
        raise HTTPException(status_code=404, detail="Generated task output not found.")
    return {"task": dict(task)}


@app.get("/api/projects/{project_id}/export")
def export_production_project(project_id: str, request: Request):
    if not re.fullmatch(r"[a-f0-9]{32}", project_id):
        raise HTTPException(status_code=400, detail="Invalid project ID.")
    _ensure_production_projects_table()
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM production_projects WHERE id=? AND owner_username=?",
            (project_id, _production_project_owner(request))
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Project not found.")
    project = _production_project_dict(row)
    project["format"] = next((item for item in production_catalog()["formats"] if item["id"] == project["format_id"]), None)
    project["pipeline"] = production_catalog()["pipeline"]
    content = json.dumps({"project": project, "notice": "Project brief and production plan only; external AI generation and video rendering require configured providers/engines."}, ensure_ascii=False, indent=2)
    return StreamingResponse(io.BytesIO(content.encode("utf-8")), media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="sintu-project-{project_id}.json"'})


@app.get("/api/production-catalog")
def production_catalog_api():
    """Return API-independent production formats, presets and pipeline stages."""
    return production_catalog()

@app.get("/api/studio/agents")
def studio_agent_registry():
    return agent_registry()


@app.get("/api/studio/production-plan/{format_id}")
def studio_production_plan(format_id: str):
    try:
        return production_plan(format_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown video format.")




class BlenderRenderInput(BaseModel):
    project_id: str = Field(min_length=32, max_length=32, pattern=r"^[a-f0-9]{32}$")
    title: str = Field(min_length=1, max_length=100)
    objects: list[dict] = Field(min_length=1, max_length=20)
    duration_seconds: int = Field(default=8, ge=1, le=30)
    resolution: str = Field(default="1280x720", max_length=12)
    fps: int = Field(default=24, ge=24, le=60)

class StudioRunInput(BaseModel):
    project_id: str = Field(min_length=32, max_length=32, pattern=r"^[a-f0-9]{32}$")
    format_id: str = Field(min_length=1, max_length=80)
class StudioWorkerOutputInput(BaseModel):
    output: str = Field(min_length=1, max_length=50000)
class StudioCheckerInput(BaseModel):
    decision: str = Field(pattern=r"^(PASS|FAIL|pass|fail)$")
    evidence: str = Field(min_length=1, max_length=12000)
    issues: str = Field(default="", max_length=12000)
class StudioApprovalInput(BaseModel):
    approved: bool
    note: str = Field(default="", max_length=4000)
class StudioAssetInput(BaseModel):
    project_id: str = Field(min_length=32, max_length=32, pattern=r"^[a-f0-9]{32}$")
    kind: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=160)
    uri: str = Field(default="", max_length=2048)
    metadata: dict = Field(default_factory=dict)
class StudioMemoryInput(BaseModel):
    project_id: str = Field(min_length=32, max_length=32, pattern=r"^[a-f0-9]{32}$")
    key: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=12000)
class StudioVersionInput(BaseModel):
    project_id: str = Field(min_length=32, max_length=32, pattern=r"^[a-f0-9]{32}$")
class StudioRenderInput(BaseModel):
    project_id: str = Field(min_length=32, max_length=32, pattern=r"^[a-f0-9]{32}$")
    payload: dict = Field(default_factory=dict)
class StudioRenderUpdateInput(BaseModel):
    status: str = Field(pattern=r"^(running|completed|failed)$")
    result: dict | None = None

def _studio_owner(request: Request) -> str:
    return _production_project_owner(request)

def _studio_project_or_404(project_id: str, request: Request):
    if not re.fullmatch(r"[a-f0-9]{32}", project_id):
        raise HTTPException(status_code=400, detail="Invalid project ID.")
    _ensure_production_projects_table()
    with db() as conn:
        row = conn.execute("SELECT * FROM production_projects WHERE id=? AND owner_username=?",
                           (project_id, _studio_owner(request))).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Project not found.")
    return dict(row)

@app.get("/api/studio/blender/status")
def studio_blender_status():
    return blender_status()

@app.post("/api/studio/blender/render", status_code=201)
def studio_blender_render(payload: BlenderRenderInput, request: Request):
    project = _studio_project_or_404(payload.project_id, request)
    try:
        result = render_scene(payload.title, payload.objects, payload.duration_seconds, payload.resolution, payload.fps)
    except BlenderUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except BlenderRenderFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    studio_engine.add_asset(_studio_owner(request), payload.project_id, "render", payload.title,
                            result["url"], {"engine":"Blender","render_id":result["render_id"],"resolution":result["resolution"]})
    return {"render":result,"project_id":project["id"]}

@app.get("/api/blender-renders/{render_id}")
def get_blender_render(render_id: str):
    if not re.fullmatch(r"[a-f0-9]{32}", render_id):
        raise HTTPException(status_code=400, detail="Invalid Blender render ID.")
    path = BLENDER_DIR / render_id / (render_id + ".mp4")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Blender render not found.")
    return FileResponse(path, media_type="video/mp4", filename="sintu-3d-" + render_id + ".mp4")

@app.get("/api/studio/summary")
def studio_summary():
    return {"scope": scope_summary(), "orchestration": orchestration_summary(),
            "execution": "Persistent worker/checker queue is available; actual model calls require local Ollama.",
            "free_policy": "No paid API, subscription or GPU can be enabled before revenue and explicit user approval."}

@app.post("/api/studio/runs", status_code=201)
def studio_create_run(payload: StudioRunInput, request: Request):
    project = _studio_project_or_404(payload.project_id, request)
    if project["format_id"] != payload.format_id:
        raise HTTPException(status_code=400, detail="Run format must match the saved project format.")
    try:
        run = studio_engine.create_run(_studio_owner(request), payload.project_id, payload.format_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"run": run}

@app.get("/api/studio/runs")
def studio_list_runs(request: Request):
    return {"runs": studio_engine.list_runs(_studio_owner(request))}

@app.get("/api/studio/runs/{run_id}")
def studio_get_run(run_id: str, request: Request):
    run = studio_engine.get_run(_studio_owner(request), run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Production run not found.")
    return {"run": run}

@app.post("/api/studio/runs/{run_id}/tasks/{task_id}/submit")
def studio_submit_worker(run_id: str, task_id: str, payload: StudioWorkerOutputInput, request: Request):
    try:
        result = studio_engine.submit_worker_output(_studio_owner(request), run_id, task_id, payload.output)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if not result:
        raise HTTPException(status_code=404, detail="Run or task not found.")
    return {"run": result}

@app.post("/api/studio/runs/{run_id}/tasks/{task_id}/check")
def studio_submit_checker(run_id: str, task_id: str, payload: StudioCheckerInput, request: Request):
    try:
        result = studio_engine.submit_checker_result(_studio_owner(request), run_id, task_id,
                                                     payload.decision, payload.evidence, payload.issues)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if not result:
        raise HTTPException(status_code=404, detail="Run or task not found.")
    return {"run": result}

@app.post("/api/studio/runs/{run_id}/tasks/{task_id}/revise")
def studio_revise_worker(run_id: str, task_id: str, payload: StudioWorkerOutputInput, request: Request):
    try:
        result = studio_engine.revise_worker_output(_studio_owner(request), run_id, task_id, payload.output)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if not result:
        raise HTTPException(status_code=404, detail="Run or task not found.")
    return {"run": result}

def _execute_studio_task_pair(owner: str, run_id: str):
    run = studio_engine.get_run(owner, run_id)
    if not run:
        return {"error":"Production run not found."}
    task = next((item for item in run["tasks"] if item["id"] == run["current_task_id"]), None)
    if not task or task["status"] not in {"pending","needs_revision","waiting_checker"}:
        return {"error":"No worker/checker task is ready."}
    _ensure_production_projects_table()
    with db() as conn:
        project_row = conn.execute("SELECT * FROM production_projects WHERE id=? AND owner_username=?",
                                   (run["project_id"], owner)).fetchone()
    if not project_row:
        return {"error":"Project not found for this production run."}
    project = dict(project_row)
    worker = None
    try:
        if task["status"] == "waiting_checker":
            worker = {"output":task["worker_output"],"model":"existing submitted worker output"}
        else:
            worker_prompt = (
                "Act as the specialist role: " + task["specialist"] + ".\nProject: " + project["name"] +
                "\nFormat: " + run["format_id"] + "\nLanguage: " + project["language"] +
                "\nDuration seconds: " + str(project["duration_seconds"]) + "\nProject brief:\n" + project["brief"] +
                "\n\nCreate only your department deliverable. Be specific and practical. Do not claim external tools, live research, media generation or publishing unless actually done.\n"
                "Previous independent checker revision instructions:\n" + (task.get("checker_issues") or "")
            )
            worker = generate_text(worker_prompt, "content", "local")
            studio_engine.submit_worker_output(owner, run_id, task["id"], worker["output"])
        checker_prompt = (
            "You are the independent checker role " + task["checker"] + ". You did not create this work. "
            "Strictly review the output of " + task["specialist"] + " against the project brief. "
            "Return ONLY valid JSON: decision (PASS or FAIL), evidence (specific checks performed), "
            "issues (empty for PASS; actionable corrections for FAIL). PASS only when requirements are met.\n\n"
            "Project brief:\n" + project["brief"] + "\n\nWorker output:\n" + str(worker["output"])[:30000]
        )
        checker = generate_text(checker_prompt, "content", "local")
    except (ProviderNotConfigured, ProviderRequestError, ValueError) as exc:
        studio_engine.set_run_status(owner, run_id, "paused", str(exc))
        return {"error":str(exc),"run":studio_engine.get_run(owner,run_id)}
    parsed = None
    match = re.search(r"\{[\s\S]*\}", checker["output"])
    if match:
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            parsed = None
    if not isinstance(parsed, dict) or str(parsed.get("decision","")).upper() not in {"PASS","FAIL"} or not str(parsed.get("evidence","")).strip():
        decision, evidence, issues = "FAIL", checker["output"][:10000] or "No structured checker evidence returned.", "Checker response was not valid strict JSON. Review manually and resubmit checker result."
    else:
        decision = str(parsed["decision"]).upper()
        evidence = str(parsed["evidence"])[:12000]
        issues = str(parsed.get("issues",""))[:12000]
        if decision == "FAIL" and not issues:
            issues = "Checker reported FAIL but omitted revision instructions."
    result = studio_engine.submit_checker_result(owner, run_id, task["id"], decision, evidence, issues)
    return {"run":result,
            "worker":{"role":task["specialist"],"model":worker.get("model","local"),"output":worker["output"]},
            "checker":{"role":task["checker"],"model":checker["model"],"decision":decision,"evidence":evidence,"issues":issues}}

def _run_studio_background(owner: str, run_id: str):
    while True:
        run = studio_engine.get_run(owner, run_id)
        if not run or run["status"] in {"awaiting_human_approval","completed","approval_rejected"}:
            return
        result = _execute_studio_task_pair(owner, run_id)
        if result.get("error"):
            return
        if result.get("checker",{}).get("decision") == "FAIL":
            return

@app.post("/api/studio/runs/{run_id}/execute-next")
def studio_execute_next(run_id: str, request: Request):
    result = _execute_studio_task_pair(_studio_owner(request), run_id)
    if result.get("error"):
        raise HTTPException(status_code=503, detail=result["error"])
    result["note"] = "Worker and checker used separate local-model requests. Human judgment remains necessary for factual, legal and copyright decisions."
    return result

@app.post("/api/studio/runs/{run_id}/execute-all")
def studio_execute_all(run_id: str, background_tasks: BackgroundTasks, request: Request):
    owner = _studio_owner(request)
    run = studio_engine.get_run(owner, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Production run not found.")
    try:
        run = studio_engine.start_run(owner, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if run["status"] == "awaiting_human_approval":
        return {"run":run,"started":False,"note":"All checker gates already passed; final human approval is pending."}
    background_tasks.add_task(_run_studio_background, owner, run_id)
    return {"run":run,"started":True,"note":"All specialist/checker pairs will run sequentially through the free local model. The run pauses on provider errors or the first checker FAIL."}

@app.post("/api/studio/runs/{run_id}/approve")
def studio_approve_run(run_id: str, payload: StudioApprovalInput, request: Request):
    try:
        result = studio_engine.approve_run(_studio_owner(request), run_id, payload.approved, payload.note)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if not result:
        raise HTTPException(status_code=404, detail="Production run not found.")
    return {"run": result, "publishing_started": False, "note": "Human approval records workflow completion; it does not publish publicly."}

@app.get("/api/studio/assets")
def studio_list_assets(project_id: str, request: Request):
    _studio_project_or_404(project_id, request)
    return {"assets": studio_engine.list_assets(_studio_owner(request), project_id)}

@app.post("/api/studio/assets", status_code=201)
def studio_add_asset(payload: StudioAssetInput, request: Request):
    _studio_project_or_404(payload.project_id, request)
    if len(json.dumps(payload.metadata, ensure_ascii=False)) > 12000:
        raise HTTPException(status_code=400, detail="Asset metadata is too large.")
    return {"asset": studio_engine.add_asset(_studio_owner(request), payload.project_id, payload.kind,
                                               payload.name, payload.uri, payload.metadata)}

@app.delete("/api/studio/assets/{asset_id}")
def studio_delete_asset(asset_id: str, request: Request):
    if not studio_engine.delete_asset(_studio_owner(request), asset_id):
        raise HTTPException(status_code=404, detail="Asset not found.")
    return {"deleted": True}

@app.get("/api/studio/memory/{project_id}")
def studio_get_memory(project_id: str, request: Request):
    _studio_project_or_404(project_id, request)
    return {"memory": studio_engine.list_memory(_studio_owner(request), project_id)}

@app.put("/api/studio/memory")
def studio_set_memory(payload: StudioMemoryInput, request: Request):
    _studio_project_or_404(payload.project_id, request)
    return {"memory": studio_engine.set_memory(_studio_owner(request), payload.project_id, payload.key, payload.value)}

@app.delete("/api/studio/memory/{project_id}/{key}")
def studio_delete_memory(project_id: str, key: str, request: Request):
    _studio_project_or_404(project_id, request)
    if not studio_engine.delete_memory(_studio_owner(request), project_id, key):
        raise HTTPException(status_code=404, detail="Memory item not found.")
    return {"deleted": True}

@app.get("/api/studio/versions/{project_id}")
def studio_get_versions(project_id: str, request: Request):
    _studio_project_or_404(project_id, request)
    return {"versions": studio_engine.list_versions(_studio_owner(request), project_id)}

@app.post("/api/studio/versions", status_code=201)
def studio_create_version(payload: StudioVersionInput, request: Request):
    project = _studio_project_or_404(payload.project_id, request)
    snapshot = {"project": project, "memory": studio_engine.list_memory(_studio_owner(request), payload.project_id),
                "assets": studio_engine.list_assets(_studio_owner(request), payload.project_id)}
    return {"version": studio_engine.create_version(_studio_owner(request), payload.project_id, snapshot)}

@app.post("/api/studio/render-queue/{item_id}/execute")
def studio_execute_render_queue(item_id: str, request: Request):
    owner = _studio_owner(request)
    item = next((entry for entry in studio_engine.list_render_queue(owner) if entry["id"] == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Render queue item not found.")
    try:
        studio_engine.update_render_item(owner, item_id, "running")
        render_payload = RenderInput(**item["payload"])
        result = render_video(render_payload)
        completed = studio_engine.update_render_item(owner, item_id, "completed", result)
        return {"item": completed, "render": result}
    except HTTPException as exc:
        try:
            studio_engine.update_render_item(owner, item_id, "failed", {"status_code": exc.status_code, "error": str(exc.detail)})
        except ValueError:
            pass
        raise
    except (ValueError, TypeError) as exc:
        try:
            studio_engine.update_render_item(owner, item_id, "failed", {"error": str(exc)})
        except ValueError:
            pass
        raise HTTPException(status_code=400, detail="Render queue payload invalid: " + str(exc))
    except Exception as exc:
        try:
            studio_engine.update_render_item(owner, item_id, "failed", {"error": type(exc).__name__})
        except ValueError:
            pass
        raise HTTPException(status_code=500, detail="Render queue item failed (" + type(exc).__name__ + ").") from None

@app.get("/api/studio/render-queue")
def studio_get_render_queue(request: Request, project_id: str | None = None):
    if project_id:
        _studio_project_or_404(project_id, request)
    return {"queue": studio_engine.list_render_queue(_studio_owner(request), project_id)}

@app.post("/api/studio/render-queue", status_code=201)
def studio_enqueue_render(payload: StudioRenderInput, request: Request):
    _studio_project_or_404(payload.project_id, request)
    if len(json.dumps(payload.payload, ensure_ascii=False)) > 20000:
        raise HTTPException(status_code=400, detail="Render payload is too large.")
    return {"item": studio_engine.enqueue_render(_studio_owner(request), payload.project_id, payload.payload)}

@app.patch("/api/studio/render-queue/{item_id}")
def studio_update_render_queue(item_id: str, payload: StudioRenderUpdateInput, request: Request):
    try:
        item = studio_engine.update_render_item(_studio_owner(request), item_id, payload.status, payload.result)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if not item:
        raise HTTPException(status_code=404, detail="Render queue item not found.")
    return {"item": item}


@app.get("/api/agents")
def agents():
    return {"total": len(list_agents()), "agents": list_agents(), "orchestration": orchestration_summary()}

@app.get("/api/capabilities")
def capabilities():
    providers = provider_status(_get_app_setting("selected_provider", os.getenv("AI_PROVIDER", "auto").lower()))
    return {
        "product": "SINTU AI STUDIO",
        "workflows": list(WORKFLOW_GUIDES.keys()),
        "agent_catalog": len(list_agents()),
        "orchestration": orchestration_summary(),
        "providers": {
            "local": providers["local"]["configured"],
            "openai": providers["openai"]["configured"],
            "gemini": providers["gemini"]["configured"],
        },
        "studio_scope": scope_summary(),
        "blender_3d": blender_status(),
        "paid_upgrades_allowed": paid_upgrades_allowed(),
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
    return provider_status(_get_app_setting("selected_provider", os.getenv("AI_PROVIDER", "auto").lower()))

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
        selected_provider = _get_app_setting("selected_provider", os.getenv("AI_PROVIDER", "auto").lower())
        if selected_provider == os.getenv("AI_PROVIDER", "auto").lower():
            result = generate_text(prompt, payload.workflow)
        else:
            result = generate_text(prompt, payload.workflow, selected_provider)
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


def _youtube_config():
    return {
        "client_id": os.getenv("YOUTUBE_CLIENT_ID", "").strip(),
        "client_secret": os.getenv("YOUTUBE_CLIENT_SECRET", "").strip(),
        "redirect_uri": os.getenv("YOUTUBE_REDIRECT_URI", "").strip(),
        "encryption_key": os.getenv("YOUTUBE_TOKEN_ENCRYPTION_KEY", "").strip(),
    }


def _youtube_cipher():
    key = _youtube_config()["encryption_key"]
    if not key:
        raise HTTPException(status_code=503, detail="YOUTUBE_TOKEN_ENCRYPTION_KEY server secret configure karein.")
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError):
        raise HTTPException(status_code=503, detail="YouTube token encryption key invalid hai.") from None


def _youtube_request(url, data=None, headers=None, method=None):
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read(2000).decode("utf-8", errors="replace")
        raise HTTPException(status_code=502, detail="Google API request failed (" + str(exc.code) + "). " + body[:500]) from None
    except (urllib.error.URLError, TimeoutError):
        raise HTTPException(status_code=502, detail="Google API se connection nahi ho paya.") from None


def _youtube_connection():
    with db() as conn:
        row = conn.execute("SELECT channel_id,channel_title,token_expiry,connected_at FROM youtube_connection WHERE id=1").fetchone()
    return dict(row) if row else None


def _youtube_access_token():
    config = _youtube_config()
    if not config["client_id"] or not config["client_secret"]:
        raise HTTPException(status_code=503, detail="YouTube OAuth client ID/secret server environment mein configure nahi hain.")
    with db() as conn:
        row = conn.execute("SELECT encrypted_tokens,token_expiry FROM youtube_connection WHERE id=1").fetchone()
    if not row:
        raise HTTPException(status_code=409, detail="Pehle YouTube channel connect karein.")
    try:
        tokens = json.loads(_youtube_cipher().decrypt(row["encrypted_tokens"].encode()).decode())
    except (InvalidToken, ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=503, detail="Stored YouTube credentials decrypt nahi ho rahe; reconnect karein.") from None
    if int(row["token_expiry"]) <= int(time.time()) + 90:
        if not tokens.get("refresh_token"):
            raise HTTPException(status_code=401, detail="YouTube session expire ho gayi; channel reconnect karein.")
        payload = urllib.parse.urlencode({
            "client_id": config["client_id"], "client_secret": config["client_secret"],
            "refresh_token": tokens["refresh_token"], "grant_type": "refresh_token"
        }).encode()
        _, _, body = _youtube_request("https://oauth2.googleapis.com/token", payload,
                                      {"Content-Type": "application/x-www-form-urlencoded"})
        refreshed = json.loads(body.decode())
        tokens.update(refreshed)
        tokens["refresh_token"] = tokens.get("refresh_token") or refreshed.get("refresh_token")
        expiry = int(time.time()) + int(refreshed.get("expires_in", 3600))
        encrypted = _youtube_cipher().encrypt(json.dumps(tokens).encode()).decode()
        with db() as conn:
            conn.execute("UPDATE youtube_connection SET encrypted_tokens=?,token_expiry=? WHERE id=1",
                         (encrypted, expiry))
    return tokens["access_token"]


@app.get("/api/admin/youtube/status")
def youtube_admin_status():
    config = _youtube_config()
    connection = _youtube_connection()
    return {
        "oauth_configured": bool(config["client_id"] and config["client_secret"] and config["redirect_uri"]),
        "encryption_configured": bool(config["encryption_key"]),
        "connected": bool(connection),
        "channel": {"id": connection["channel_id"], "title": connection["channel_title"]} if connection else None,
        "connected_at": connection["connected_at"] if connection else None,
        "upload_enabled": bool(connection),
        "note": "OAuth credentials aur token encryption key server secrets mein configure karein. Upload ke liye approved calendar item aur rendered MP4 required hai."
    }



@app.get("/api/admin/youtube/analytics")
def youtube_channel_analytics(
    start_date: str = Query(default="", max_length=10),
    end_date: str = Query(default="", max_length=10),
):
    """Return official YouTube Analytics API data for the connected channel."""
    today = datetime.now(timezone.utc).date()
    end = today - timedelta(days=1)
    start = end - timedelta(days=27)
    try:
        start_value = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else start
        end_value = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else end
    except ValueError:
        raise HTTPException(status_code=422, detail="Dates YYYY-MM-DD format mein honi chahiye.") from None
    if end_value < start_value:
        raise HTTPException(status_code=422, detail="End date, start date ke baad honi chahiye.")
    if (end_value - start_value).days > 364:
        raise HTTPException(status_code=422, detail="Ek request mein maximum 365 din ka range allowed hai.")
    access_token = _youtube_access_token()
    headers = {"Authorization": "Bearer " + access_token}
    base = {
        "ids": "channel==MINE",
        "startDate": start_value.isoformat(),
        "endDate": end_value.isoformat(),
        "metrics": "views,estimatedMinutesWatched,averageViewDuration,subscribersGained,subscribersLost",
    }
    try:
        daily_url = "https://youtubeanalytics.googleapis.com/v2/reports?" + urllib.parse.urlencode(
            {**base, "dimensions": "day", "sort": "day", "maxResults": "366"}
        )
        _, _, daily_body = _youtube_request(daily_url, headers=headers)
        daily_report = json.loads(daily_body.decode("utf-8"))
        video_url = "https://youtubeanalytics.googleapis.com/v2/reports?" + urllib.parse.urlencode(
            {**base, "dimensions": "video", "sort": "-views", "maxResults": "10"}
        )
        _, _, video_body = _youtube_request(video_url, headers=headers)
        video_report = json.loads(video_body.decode("utf-8"))
    except HTTPException as exc:
        if exc.status_code == 502:
            raise HTTPException(status_code=424, detail="YouTube Analytics API data nahi de paaya. Google Cloud project mein YouTube Analytics API enable karein aur zarurat par YouTube account dobara connect karein.") from None
        raise
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status_code=502, detail="YouTube Analytics response samajh nahi aaya.") from None

    def unpack(report):
        headers_list = [column.get("name", "") for column in report.get("columnHeaders", [])]
        return [dict(zip(headers_list, row)) for row in report.get("rows", [])]

    revenue = {"available": False, "currency": "INR", "note": "Revenue ke liye channel ka YouTube Partner Program mein hona aur monetary OAuth permission zaroori hai."}
    revenue_url = "https://youtubeanalytics.googleapis.com/v2/reports?" + urllib.parse.urlencode({
        "ids": "channel==MINE", "startDate": start_value.isoformat(), "endDate": end_value.isoformat(),
        "metrics": "estimatedRevenue,estimatedAdRevenue,estimatedRedPartnerRevenue,grossRevenue,adImpressions,playbackBasedCpm",
        "currency": "INR"
    })
    try:
        _, _, revenue_body = _youtube_request(revenue_url, headers=headers)
        revenue_report = json.loads(revenue_body.decode("utf-8"))
        revenue_rows = unpack(revenue_report)
        revenue_values = revenue_rows[0] if revenue_rows else {}
        revenue = {
            "available": bool(revenue_rows), "currency": "INR",
            "estimated_revenue": float(revenue_values.get("estimatedRevenue", 0) or 0),
            "estimated_ad_revenue": float(revenue_values.get("estimatedAdRevenue", 0) or 0),
            "estimated_premium_revenue": float(revenue_values.get("estimatedRedPartnerRevenue", 0) or 0),
            "gross_ad_revenue": float(revenue_values.get("grossRevenue", 0) or 0),
            "ad_impressions": int(revenue_values.get("adImpressions", 0) or 0),
            "playback_based_cpm": float(revenue_values.get("playbackBasedCpm", 0) or 0),
            "note": "YouTube ke estimated revenue figures hain; final amount month-end adjustment se badal sakta hai."
        }
    except (HTTPException, ValueError, KeyError, TypeError):
        revenue["note"] = "Revenue abhi available nahi. Monetization eligibility, monetary OAuth permission aur Google API setup check karein."

    daily_rows = unpack(daily_report)
    video_rows = unpack(video_report)
    totals = {"views": 0, "estimatedMinutesWatched": 0.0, "averageViewDuration": 0.0,
              "subscribersGained": 0, "subscribersLost": 0}
    views_for_average = 0
    daily = []
    for row in daily_rows:
        views = int(row.get("views", 0) or 0)
        watched = float(row.get("estimatedMinutesWatched", 0) or 0)
        duration = float(row.get("averageViewDuration", 0) or 0)
        gained = int(row.get("subscribersGained", 0) or 0)
        lost = int(row.get("subscribersLost", 0) or 0)
        totals["views"] += views
        totals["estimatedMinutesWatched"] += watched
        totals["subscribersGained"] += gained
        totals["subscribersLost"] += lost
        views_for_average += views
        daily.append({"date": row.get("day"), "views": views, "watch_minutes": watched,
                      "average_view_duration_seconds": duration, "subscribers_gained": gained,
                      "subscribers_lost": lost})
    if views_for_average:
        totals["averageViewDuration"] = sum(
            float(row.get("averageViewDuration", 0) or 0) * int(row.get("views", 0) or 0)
            for row in daily_rows
        ) / views_for_average
    top_videos = []
    for row in video_rows:
        video_id = str(row.get("video", ""))
        if not video_id:
            continue
        top_videos.append({
            "video_id": video_id,
            "url": "https://www.youtube.com/watch?v=" + urllib.parse.quote(video_id, safe=""),
            "views": int(row.get("views", 0) or 0),
            "watch_minutes": float(row.get("estimatedMinutesWatched", 0) or 0),
            "average_view_duration_seconds": float(row.get("averageViewDuration", 0) or 0),
        })
    totals["estimatedMinutesWatched"] = round(totals["estimatedMinutesWatched"], 2)
    totals["averageViewDuration"] = round(totals["averageViewDuration"], 2)
    return {
        "source": "YouTube Analytics API",
        "channel": (_youtube_connection() or {}).get("channel_title"),
        "start_date": start_value.isoformat(),
        "end_date": end_value.isoformat(),
        "totals": totals,
        "daily": daily,
        "top_videos": top_videos,
        "revenue": revenue,
        "note": "YouTube ke official reported metrics. Recent dates par data delay ho sakta hai; thumbnail impressions aur CTR alag daily Reporting API report se aate hain.",
    }


@app.get("/api/admin/youtube/comments")
def youtube_channel_comments(limit: int = Query(default=50, ge=1, le=100), page_token: str = Query(default="", max_length=2048)):
    """Read recent channel comments and provide transparent heuristic triage; never moderates or replies."""
    connection = _youtube_connection()
    if not connection:
        raise HTTPException(status_code=409, detail="Pehle YouTube channel connect karein.")
    token = _youtube_access_token()
    params = {
        "part": "snippet", "allThreadsRelatedToChannelId": connection["channel_id"],
        "order": "time", "textFormat": "plainText", "maxResults": str(limit),
    }
    if page_token:
        params["pageToken"] = page_token
    url = "https://www.googleapis.com/youtube/v3/commentThreads?" + urllib.parse.urlencode(params)
    try:
        _, _, body = _youtube_request(url, headers={"Authorization": "Bearer " + token})
        payload = json.loads(body.decode("utf-8"))
    except HTTPException as exc:
        if exc.status_code == 502:
            raise HTTPException(status_code=424, detail="YouTube comments nahi mil paaye. YouTube Data API v3 enable karein aur channel permissions check karein.") from None
        raise
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status_code=502, detail="YouTube comments response samajh nahi aaya.") from None

    spam_patterns = [
        r"\b(whatsapp|telegram)\b",
        r"\b(guaranteed|double|risk[- ]free)\s+(profit|returns?|income)\b",
        r"\b(crypto|forex|investment)\b.{0,50}\b(profit|guaranteed|double|signals)\b",
        r"\b(subscribers?\s*for\s*subscribers?|sub4sub|follow\s*for\s*follow)\b",
        r"https?://|www\.",
        r"\b(earn money fast|work from home|giveaway winner|claim your prize)\b",
    ]
    positive = {"good", "great", "awesome", "excellent", "love", "thanks", "thank", "helpful", "शानदार", "अच्छा", "धन्यवाद", "बढ़िया", "बहुत"}
    negative = {"bad", "worst", "fake", "hate", "useless", "boring", "गलत", "बकवास", "बेकार", "झूठ"}
    comments = []
    counts = {"total": 0, "possible_spam": 0, "positive": 0, "negative": 0, "questions": 0, "other": 0}
    for thread in payload.get("items", []):
        top = (thread.get("snippet") or {}).get("topLevelComment") or {}
        snippet = top.get("snippet") or {}
        text_value = str(snippet.get("textOriginal") or snippet.get("textDisplay") or "")[:5000]
        lowered = text_value.lower()
        words = set(re.findall(r"[a-zA-Z]+|[\u0900-\u097f]+", lowered))
        spam = any(re.search(pattern, lowered, re.I) for pattern in spam_patterns)
        sentiment = "positive" if words & positive else "negative" if words & negative else "question" if "?" in text_value or any(w in words for w in {"how", "what", "why", "when", "kaise", "kya", "क्यों", "कैसे", "क्या"}) else "other"
        if spam:
            counts["possible_spam"] += 1
            suggested_reply = "Is comment ko manually review karein; suspicious links/promotions par click na karein."
        elif sentiment == "question":
            counts["questions"] += 1
            suggested_reply = "Achha sawal hai! Hum is par detail mein jawab denge."
        elif sentiment == "positive":
            counts["positive"] += 1
            suggested_reply = "Bahut shukriya! Aapka support humein aur achha content banane ke liye motivate karta hai."
        elif sentiment == "negative":
            counts["negative"] += 1
            suggested_reply = "Feedback ke liye shukriya. Hum ise review karke sudhar karne ki koshish karenge."
        else:
            counts["other"] += 1
            suggested_reply = "Comment karne ke liye shukriya!"
        comments.append({
            "comment_id": top.get("id"), "video_id": snippet.get("videoId"),
            "author": snippet.get("authorDisplayName", "YouTube user"),
            "text": text_value, "published_at": snippet.get("publishedAt"),
            "likes": int(snippet.get("likeCount", 0) or 0),
            "classification": "possible_spam" if spam else sentiment,
            "suggested_reply": suggested_reply,
        })
    counts["total"] = len(comments)
    if comments:
        ids = [item["comment_id"] for item in comments if item.get("comment_id")]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            with db() as conn:
                saved = {row["comment_id"]: row for row in conn.execute(
                    f"SELECT comment_id,review_status,notes,updated_at FROM youtube_comment_reviews WHERE comment_id IN ({placeholders})",
                    ids,
                ).fetchall()}
            for item in comments:
                review = saved.get(item.get("comment_id"))
                item["review_status"] = review["review_status"] if review else "pending"
                item["review_notes"] = review["notes"] if review else ""
                item["review_updated_at"] = review["updated_at"] if review else None
    return {
        "source": "YouTube Data API v3", "channel": connection.get("channel_title"),
        "comments": comments, "counts": counts,
        "next_page_token": payload.get("nextPageToken", ""),
        "note": "Spam aur sentiment labels simple keyword heuristics hain, AI verdict nahi. Suggestions draft-only hain. Koi comment delete, hide, approve ya reply nahi kiya gaya.",
    }


@app.post("/api/admin/youtube/comments/review")
def save_youtube_comment_review(item: YouTubeCommentReviewInput):
    """Save an internal review decision only; does not modify anything on YouTube."""
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        previous = conn.execute(
            "SELECT review_status,notes,assigned_to,follow_up_at FROM youtube_comment_reviews WHERE comment_id=?",
            (item.comment_id,),
        ).fetchone()
        event_type = "created" if previous is None else "updated"
        previous_status = previous["review_status"] if previous else ""
        note_changed = previous is not None and previous["notes"] != item.notes.strip()
        conn.execute(
            """INSERT INTO youtube_comment_reviews(
                 comment_id,video_id,review_status,notes,updated_at,author,comment_text,published_at,likes,classification,assigned_to,follow_up_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(comment_id) DO UPDATE SET video_id=excluded.video_id,
                 review_status=excluded.review_status,notes=excluded.notes,updated_at=excluded.updated_at,
                 author=excluded.author,comment_text=excluded.comment_text,published_at=excluded.published_at,
                 likes=excluded.likes,classification=excluded.classification,
                 assigned_to=excluded.assigned_to,follow_up_at=excluded.follow_up_at""",
            (item.comment_id, item.video_id, item.review_status, item.notes.strip(), now,
             item.author.strip(), item.text, item.published_at, item.likes, item.classification,
             item.assigned_to.strip(), item.follow_up_at.strip()),
        )
        conn.execute(
            """INSERT INTO youtube_comment_review_history(
                 comment_id,video_id,event_type,previous_status,new_status,note_changed,changed_at,
                 previous_assigned_to,new_assigned_to,previous_follow_up_at,new_follow_up_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (item.comment_id,item.video_id,event_type,previous_status,item.review_status,int(note_changed),now,
             previous["assigned_to"] if previous else "",item.assigned_to.strip(),
             previous["follow_up_at"] if previous else "",item.follow_up_at.strip()),
        )
    return {"saved": True, "comment_id": item.comment_id, "review_status": item.review_status,
            "notes": item.notes.strip(), "updated_at": now, "author": item.author.strip(),
            "assigned_to": item.assigned_to.strip(), "follow_up_at": item.follow_up_at.strip(),
            "note": "Review SINTU mein save hua hai. YouTube comment par koi action nahi hua."}


@app.post("/api/admin/youtube/comments/reviews/bulk")
def bulk_update_youtube_comment_reviews(item: YouTubeCommentBulkReviewInput):
    """Apply an internal review status to selected saved comments; never modifies YouTube."""
    comment_ids = list(dict.fromkeys(value.strip() for value in item.comment_ids))
    if len(comment_ids) != len(item.comment_ids) or any(not value or len(value) > 200 for value in comment_ids):
        raise HTTPException(status_code=422, detail="Invalid or duplicate comment IDs")
    now = datetime.now(timezone.utc).isoformat()
    placeholders = ",".join("?" for _ in comment_ids)
    with db() as conn:
        rows = conn.execute(
            f"SELECT comment_id,video_id,review_status FROM youtube_comment_reviews WHERE comment_id IN ({placeholders})",
            comment_ids,
        ).fetchall()
        if len(rows) != len(comment_ids):
            raise HTTPException(status_code=404, detail="One or more saved comments were not found; no changes applied")
        for row in rows:
            conn.execute(
                "UPDATE youtube_comment_reviews SET review_status=?,updated_at=? WHERE comment_id=?",
                (item.review_status,now,row["comment_id"]),
            )
            conn.execute(
                """INSERT INTO youtube_comment_review_history(
                     comment_id,video_id,event_type,previous_status,new_status,note_changed,changed_at
                   ) VALUES(?,?,?,?,?,?,?)""",
                (row["comment_id"],row["video_id"],"bulk_updated",row["review_status"],item.review_status,0,now),
            )
    return {"updated":len(rows),"review_status":item.review_status,"updated_at":now,
            "note":"Bulk review SINTU ke internal records mein save hua. YouTube par koi action nahi hua."}


@app.post("/api/admin/youtube/comments/reviews/assign")
def assign_youtube_comment_reviews(item: YouTubeCommentAssignmentInput):
    """Assign internal owners and follow-up dates for saved reviews only."""
    ids = [value.strip() for value in item.comment_ids]
    if len(set(ids)) != len(ids) or any(not value or len(value) > 200 for value in ids):
        raise HTTPException(status_code=422, detail="Invalid or duplicate comment IDs")
    now = datetime.now(timezone.utc).isoformat()
    placeholders = ",".join("?" for _ in ids)
    with db() as conn:
        rows = conn.execute(
            f"SELECT comment_id,video_id,assigned_to,follow_up_at,review_status FROM youtube_comment_reviews WHERE comment_id IN ({placeholders})",
            ids,
        ).fetchall()
        if len(rows) != len(ids):
            raise HTTPException(status_code=404, detail="One or more saved comments were not found; no changes applied")
        for row in rows:
            conn.execute(
                "UPDATE youtube_comment_reviews SET assigned_to=?,follow_up_at=?,updated_at=? WHERE comment_id=?",
                (item.assigned_to.strip(),item.follow_up_at.strip(),now,row["comment_id"]),
            )
            conn.execute(
                """INSERT INTO youtube_comment_review_history(
                     comment_id,video_id,event_type,previous_status,new_status,note_changed,changed_at,
                     previous_assigned_to,new_assigned_to,previous_follow_up_at,new_follow_up_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (row["comment_id"],row["video_id"],"assignment_updated",row["review_status"],row["review_status"],0,now,
                 row["assigned_to"],item.assigned_to.strip(),row["follow_up_at"],item.follow_up_at.strip()),
            )
    return {"updated":len(rows),"assigned_to":item.assigned_to.strip(),"follow_up_at":item.follow_up_at.strip(),
            "note":"Assignment SINTU ke internal records mein save hua. YouTube par koi action nahi hua."}


@app.get("/api/admin/youtube/comments/reviews")
def list_youtube_comment_reviews(
    review_status: str = Query(default="", regex=r"^(|pending|reviewed|follow_up|resolved)$"),
    classification: str = Query(default="", regex=r"^(|possible_spam|positive|negative|question|other)$"),
    search: str = Query(default="", max_length=200),
    sort: str = Query(default="newest", regex=r"^(newest|likes|spam)$"),
    assigned_to: str = Query(default="", max_length=120),
    follow_up_filter: str = Query(default="", pattern=r"^(|overdue|today|upcoming|unscheduled)$"),
    as_of: str = Query(default="", max_length=10),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1000000),
):
    """Search, filter and page through saved internal review records."""
    clauses = []
    params = []
    if review_status:
        clauses.append("review_status=?")
        params.append(review_status)
    if classification:
        clauses.append("classification=?")
        params.append(classification)
    if assigned_to.strip():
        clauses.append("assigned_to=?")
        params.append(assigned_to.strip())
    if follow_up_filter:
        today = as_of or datetime.now(timezone.utc).date().isoformat()
        try:
            datetime.strptime(today, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=422, detail="as_of must use YYYY-MM-DD")
        if follow_up_filter == "overdue":
            clauses.append("follow_up_at<>'' AND follow_up_at<?")
            params.append(today)
        elif follow_up_filter == "today":
            clauses.append("follow_up_at=?")
            params.append(today)
        elif follow_up_filter == "upcoming":
            clauses.append("follow_up_at>?")
            params.append(today)
        else:
            clauses.append("follow_up_at=''")
    if search.strip():
        clauses.append("(author LIKE ? OR comment_text LIKE ? OR notes LIKE ? OR video_id LIKE ?)")
        term = f"%{search.strip()}%"
        params.extend([term, term, term, term])
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    ordering = {
        "newest": "updated_at DESC, comment_id ASC",
        "likes": "likes DESC, updated_at DESC",
        "spam": "CASE WHEN classification='possible_spam' THEN 0 ELSE 1 END, updated_at DESC",
    }[sort]
    with db() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM youtube_comment_reviews {where}", params).fetchone()[0]
        rows = conn.execute(
            f"""SELECT comment_id,video_id,review_status,notes,updated_at,author,
                       comment_text AS text,published_at,likes,classification,assigned_to,follow_up_at
                FROM youtube_comment_reviews {where}
                ORDER BY {ordering} LIMIT ? OFFSET ?""",
            (*params, limit, offset),
        ).fetchall()
    return {"items": [dict(row) for row in rows], "total": total,
            "limit": limit, "offset": offset, "sort": sort,
            "note": "Yeh SINTU mein save kiye gaye internal review records hain; YouTube par koi moderation action nahi hota."}


@app.get("/api/admin/youtube/comments/reviews/follow-ups/due")
def youtube_comment_follow_up_due(
    as_of: str = Query(default="", max_length=10),
    limit: int = Query(default=50, ge=1, le=100),
):
    """Return actionable overdue and due-today internal community follow-ups."""
    today = as_of or datetime.now(timezone.utc).date().isoformat()
    try:
        datetime.strptime(today, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=422, detail="as_of must use YYYY-MM-DD")
    with db() as conn:
        rows = conn.execute(
            """SELECT comment_id,video_id,review_status,author,comment_text AS text,
                      classification,assigned_to,follow_up_at,updated_at,likes
               FROM youtube_comment_reviews
               WHERE follow_up_at<>'' AND follow_up_at<=? AND review_status<>'resolved'
               ORDER BY follow_up_at ASC,likes DESC,updated_at DESC LIMIT ?""",
            (today,limit)
        ).fetchall()
    items=[]
    for row in rows:
        item=dict(row)
        item["due_state"]="overdue" if item["follow_up_at"]<today else "due_today"
        items.append(item)
    return {"as_of":today,"items":items,"total":len(items),
            "note":"Yeh internal SINTU follow-up inbox hai; yeh push notification nahi bhejta aur YouTube par koi action nahi karta."}


@app.get("/api/admin/youtube/comments/reviews/follow-ups/summary")
def youtube_comment_follow_up_summary(as_of: str = Query(default="", max_length=10)):
    """Return due/overdue follow-up counts and internal assignee workload."""
    today = as_of or datetime.now(timezone.utc).date().isoformat()
    try:
        datetime.strptime(today, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=422, detail="as_of must use YYYY-MM-DD")
    with db() as conn:
        totals = conn.execute(
            """SELECT COUNT(*) AS total,
               SUM(CASE WHEN follow_up_at<>'' AND follow_up_at<? THEN 1 ELSE 0 END) AS overdue,
               SUM(CASE WHEN follow_up_at=? THEN 1 ELSE 0 END) AS due_today,
               SUM(CASE WHEN follow_up_at>? THEN 1 ELSE 0 END) AS upcoming,
               SUM(CASE WHEN follow_up_at='' THEN 1 ELSE 0 END) AS unscheduled,
               SUM(CASE WHEN review_status='resolved' THEN 1 ELSE 0 END) AS resolved
               FROM youtube_comment_reviews""", (today,today,today)
        ).fetchone()
        owners = conn.execute(
            """SELECT CASE WHEN assigned_to='' THEN 'Unassigned' ELSE assigned_to END AS owner,
               COUNT(*) AS total,
               SUM(CASE WHEN follow_up_at<>'' AND follow_up_at<? THEN 1 ELSE 0 END) AS overdue,
               SUM(CASE WHEN follow_up_at=? THEN 1 ELSE 0 END) AS due_today,
               SUM(CASE WHEN follow_up_at>? THEN 1 ELSE 0 END) AS upcoming,
               SUM(CASE WHEN follow_up_at<>'' THEN 1 ELSE 0 END) AS scheduled,
               SUM(CASE WHEN review_status='resolved' THEN 1 ELSE 0 END) AS resolved
               FROM youtube_comment_reviews GROUP BY assigned_to ORDER BY total DESC,owner ASC""",
            (today,today,today)
        ).fetchall()
    total_values={key:(value or 0) for key,value in dict(totals).items()}
    owner_values=[]
    for row in owners:
        item={key:(value or 0) for key,value in dict(row).items()}
        item["open"]=item["total"]-item["resolved"]
        item["resolution_rate"]=round(item["resolved"]*100/item["total"],1) if item["total"] else 0
        item["follow_up_coverage"]=round(item["scheduled"]*100/item["total"],1) if item["total"] else 0
        owner_values.append(item)
    total_values["open"]=total_values["total"]-total_values["resolved"]
    total_values["resolution_rate"]=round(total_values["resolved"]*100/total_values["total"],1) if total_values["total"] else 0
    return {"as_of":today,"totals":total_values,"owners":owner_values,
            "note":"Performance metrics SINTU ke saved internal review records par aadharit hain; yeh YouTube analytics ya individual employee evaluation nahi hain."}


@app.get("/api/admin/youtube/comments/reviews/follow-ups/export")
def export_youtube_comment_follow_up_workload(as_of: str = Query(default="", max_length=10)):
    """Export internal follow-up totals and owner workload as CSV."""
    summary = youtube_comment_follow_up_summary(as_of=as_of)
    totals = summary["totals"]
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["report_type","as_of","owner","total","open","resolved","overdue","due_today",
                     "upcoming","unscheduled","resolution_rate_percent","follow_up_coverage_percent"])
    writer.writerow(["overall",summary["as_of"],"All owners",totals["total"],totals["open"],
                     totals["resolved"],totals["overdue"],totals["due_today"],totals["upcoming"],
                     totals["unscheduled"],totals["resolution_rate"],""])
    for owner in summary["owners"]:
        writer.writerow(["owner",summary["as_of"],owner["owner"],owner["total"],owner["open"],
                         owner["resolved"],owner["overdue"],owner["due_today"],owner["upcoming"],
                         owner["total"]-owner["scheduled"],owner["resolution_rate"],
                         owner["follow_up_coverage"]])
    content = "\ufeff" + output.getvalue()
    return StreamingResponse(
        iter([content]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="sintu-community-follow-up-workload.csv"'},
    )


@app.get("/api/admin/youtube/comments/reviews/{comment_id}/history")
def get_youtube_comment_review_history(comment_id: str):
    """Return internal status-change history for one saved comment."""
    if not comment_id.strip():
        raise HTTPException(status_code=422, detail="comment_id is required")
    with db() as conn:
        exists = conn.execute(
            "SELECT 1 FROM youtube_comment_reviews WHERE comment_id=?", (comment_id,)
        ).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="Saved comment review not found")
        rows = conn.execute(
            """SELECT event_type,previous_status,new_status,note_changed,changed_at,
                      previous_assigned_to,new_assigned_to,previous_follow_up_at,new_follow_up_at
               FROM youtube_comment_review_history WHERE comment_id=?
               ORDER BY changed_at DESC,id DESC LIMIT 100""",
            (comment_id,),
        ).fetchall()
    return {"comment_id":comment_id,"items":[dict(row) for row in rows],
            "note":"History sirf SINTU ke internal review changes dikhata hai; YouTube par koi action nahi hota."}


@app.get("/api/admin/youtube/comments/reviews/export")
def export_youtube_comment_reviews(
    review_status: str = Query(default="", regex=r"^(|pending|reviewed|follow_up|resolved)$"),
    classification: str = Query(default="", regex=r"^(|possible_spam|positive|negative|question|other)$"),
    search: str = Query(default="", max_length=200),
    sort: str = Query(default="newest", regex=r"^(newest|likes|spam)$"),
):
    """Export every saved review matching the queue filters as CSV."""
    clauses = []
    params = []
    if review_status:
        clauses.append("review_status=?")
        params.append(review_status)
    if classification:
        clauses.append("classification=?")
        params.append(classification)
    if search.strip():
        clauses.append("(author LIKE ? OR comment_text LIKE ? OR notes LIKE ? OR video_id LIKE ?)")
        term = f"%{search.strip()}%"
        params.extend([term, term, term, term])
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    ordering = {
        "newest": "updated_at DESC, comment_id ASC",
        "likes": "likes DESC, updated_at DESC",
        "spam": "CASE WHEN classification='possible_spam' THEN 0 ELSE 1 END, updated_at DESC",
    }[sort]
    with db() as conn:
        rows = conn.execute(
            f"""SELECT author,classification,review_status,notes,updated_at,comment_text,
                       published_at,likes,video_id,comment_id
                FROM youtube_comment_reviews {where} ORDER BY {ordering}""",
            params,
        ).fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["author","classification","review_status","review_notes","review_updated_at",
                     "comment_text","published_at","likes","video_id","comment_id"])
    writer.writerows([tuple(row) for row in rows])
    content = "\ufeff" + output.getvalue()
    return StreamingResponse(
        iter([content]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="sintu-community-review-queue.csv"'},
    )


@app.get("/api/admin/youtube/retention")
def youtube_video_retention(
    video_id: str = Query(..., min_length=11, max_length=20, regex=r"^[A-Za-z0-9_-]+$"),
    start_date: str = Query(default="", max_length=10),
    end_date: str = Query(default="", max_length=10),
):
    """Return official audience-retention curve for one YouTube video."""
    today = datetime.now(timezone.utc).date()
    default_end = today - timedelta(days=1)
    default_start = default_end - timedelta(days=27)
    try:
        start_value = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else default_start
        end_value = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else default_end
    except ValueError:
        raise HTTPException(status_code=422, detail="Dates YYYY-MM-DD format mein honi chahiye.") from None
    if end_value < start_value or (end_value - start_value).days > 364:
        raise HTTPException(status_code=422, detail="Date range valid hona chahiye aur maximum 365 din ka ho sakta hai.")
    token = _youtube_access_token()
    params = {
        "ids": "channel==MINE", "startDate": start_value.isoformat(), "endDate": end_value.isoformat(),
        "dimensions": "elapsedVideoTimeRatio",
        "metrics": "audienceWatchRatio,relativeRetentionPerformance,startedWatching,stoppedWatching",
        "filters": "video==" + video_id, "sort": "elapsedVideoTimeRatio", "maxResults": "200",
    }
    url = "https://youtubeanalytics.googleapis.com/v2/reports?" + urllib.parse.urlencode(params)
    try:
        _, _, body = _youtube_request(url, headers={"Authorization": "Bearer " + token})
        report = json.loads(body.decode("utf-8"))
        columns = [column.get("name", "") for column in report.get("columnHeaders", [])]
        rows = [dict(zip(columns, row)) for row in report.get("rows", [])]
    except HTTPException as exc:
        if exc.status_code == 502:
            raise HTTPException(status_code=424, detail="Audience retention data nahi mili. YouTube Analytics API, video ownership aur account permission check karein.") from None
        raise
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status_code=502, detail="YouTube audience-retention response samajh nahi aaya.") from None
    points = [{
        "elapsed_ratio": float(row.get("elapsedVideoTimeRatio", 0) or 0),
        "audience_watch_ratio": float(row.get("audienceWatchRatio", 0) or 0),
        "relative_retention_performance": float(row.get("relativeRetentionPerformance", 0) or 0),
        "started_watching": int(row.get("startedWatching", 0) or 0),
        "stopped_watching": int(row.get("stoppedWatching", 0) or 0),
    } for row in rows]
    return {
        "source": "YouTube Analytics API", "video_id": video_id,
        "video_url": "https://www.youtube.com/watch?v=" + urllib.parse.quote(video_id, safe=""),
        "start_date": start_value.isoformat(), "end_date": end_value.isoformat(),
        "available": bool(points), "points": points,
        "note": "AudienceWatchRatio segment ko total video views ke muqable mein dikhata hai; rewind se 1 se zyada ho sakta hai. Relative retention 0–1 par similar-length videos se comparison hai."
        if points else "Is video aur date range ke liye retention report abhi available nahi hai.",
    }


@app.post("/api/admin/youtube/reach/setup")
def youtube_reach_setup():
    """Create the official daily channel reach report job for thumbnail impressions and CTR."""
    token = _youtube_access_token()
    headers = {"Authorization": "Bearer " + token}
    base = "https://youtubereporting.googleapis.com/v1"
    try:
        _, _, jobs_body = _youtube_request(base + "/jobs?includeSystemManaged=true", headers=headers)
        jobs = json.loads(jobs_body.decode("utf-8")).get("jobs", [])
        existing = next((job for job in jobs if job.get("reportTypeId") == "channel_reach_basic_a1"), None)
        if existing:
            return {"configured": True, "job_id": existing.get("id"), "created": False,
                    "note": "Thumbnail reach report job pehle se active hai."}
        _, _, types_body = _youtube_request(base + "/reportTypes?includeSystemManaged=true", headers=headers)
        types = json.loads(types_body.decode("utf-8")).get("reportTypes", [])
        if not any(item.get("id") == "channel_reach_basic_a1" for item in types):
            raise HTTPException(status_code=424, detail="YouTube account ke liye channel_reach_basic_a1 report type abhi available nahi hai.")
        payload = json.dumps({"reportTypeId": "channel_reach_basic_a1",
                              "name": "SINTU AI Studio channel thumbnail reach"}).encode()
        _, _, created_body = _youtube_request(base + "/jobs", payload,
            {"Authorization": "Bearer " + token, "Content-Type": "application/json"}, method="POST")
        job = json.loads(created_body.decode("utf-8"))
        return {"configured": True, "job_id": job.get("id"), "created": True,
                "note": "Daily thumbnail impressions aur CTR reports enable ho gayi. Pehli report banne mein 24 ghante ya usse zyada lag sakte hain."}
    except HTTPException as exc:
        if exc.status_code == 502 and ("(409)" in str(exc.detail) or "(403)" in str(exc.detail)):
            raise HTTPException(status_code=409, detail="Reach report job create nahi hua; ho sakta hai job pehle se ho ya YouTube is report ko system-managed rakhta ho. Refresh karke status check karein.") from None
        raise
    except (ValueError, TypeError):
        raise HTTPException(status_code=502, detail="YouTube Reporting API ka response samajh nahi aaya.") from None


@app.get("/api/admin/youtube/reach")
def youtube_channel_reach():
    """Read official daily channel thumbnail impressions and click-through rates."""
    token = _youtube_access_token()
    headers = {"Authorization": "Bearer " + token}
    base = "https://youtubereporting.googleapis.com/v1"
    try:
        _, _, jobs_body = _youtube_request(base + "/jobs?includeSystemManaged=true", headers=headers)
        jobs = json.loads(jobs_body.decode("utf-8")).get("jobs", [])
        job = next((item for item in jobs if item.get("reportTypeId") == "channel_reach_basic_a1"), None)
        if not job:
            return {"configured": False, "available": False, "daily": [], "top_videos": [],
                    "note": "Thumbnail impressions/CTR ke daily reports enable karne ke liye Enable reports dabayein."}
        reports_url = base + "/jobs/" + urllib.parse.quote(str(job["id"]), safe="") + "/reports?pageSize=50"
        _, _, reports_body = _youtube_request(reports_url, headers=headers)
        reports = json.loads(reports_body.decode("utf-8")).get("reports", [])
        reports = sorted(reports, key=lambda item: item.get("startTime", ""))[-31:]
        daily_map = {}
        video_map = {}
        for report in reports:
            download_url = report.get("downloadUrl", "")
            parsed = urllib.parse.urlparse(download_url)
            host = (parsed.hostname or "").lower()
            if parsed.scheme != "https" or not (host == "storage.googleapis.com" or host.endswith(".googleapis.com") or host.endswith(".googleusercontent.com")):
                continue
            _, response_headers, csv_body = _youtube_request(download_url, headers=headers)
            encoding = response_headers.get("Content-Encoding", "") if hasattr(response_headers, "get") else ""
            if encoding.lower() == "gzip":
                csv_body = gzip.decompress(csv_body)
            reader = csv.DictReader(io.StringIO(csv_body.decode("utf-8-sig")))
            for row in reader:
                date_value = row.get("date") or report.get("startTime", "")[:10]
                impressions = int(float(row.get("video_thumbnail_impressions", 0) or 0))
                ctr = float(row.get("video_thumbnail_impressions_ctr", 0) or 0)
                video_id = str(row.get("video_id", ""))
                day = daily_map.setdefault(date_value, {"date": date_value, "impressions": 0, "_weighted_ctr": 0.0})
                day["impressions"] += impressions
                day["_weighted_ctr"] += ctr * impressions
                if video_id:
                    item = video_map.setdefault(video_id, {"video_id": video_id, "impressions": 0, "_weighted_ctr": 0.0})
                    item["impressions"] += impressions
                    item["_weighted_ctr"] += ctr * impressions
        daily = []
        for item in sorted(daily_map.values(), key=lambda x: x["date"]):
            weight = item.pop("_weighted_ctr")
            item["ctr"] = round((weight / item["impressions"]) if item["impressions"] else 0, 6)
            daily.append(item)
        videos = []
        for item in sorted(video_map.values(), key=lambda x: x["impressions"], reverse=True)[:10]:
            weight = item.pop("_weighted_ctr")
            item["ctr"] = round((weight / item["impressions"]) if item["impressions"] else 0, 6)
            item["url"] = "https://www.youtube.com/watch?v=" + urllib.parse.quote(item["video_id"], safe="")
            videos.append(item)
        total_impressions = sum(item["impressions"] for item in daily)
        total_ctr = (sum(item["ctr"] * item["impressions"] for item in daily) / total_impressions) if total_impressions else 0
        return {"configured": True, "available": bool(daily), "source": "YouTube Reporting API",
                "report_type": "channel_reach_basic_a1", "reports_checked": len(reports),
                "totals": {"thumbnail_impressions": total_impressions, "thumbnail_ctr": round(total_ctr, 6)},
                "daily": daily, "top_videos": videos,
                "note": "Official YouTube thumbnail reach data. Daily bulk reports may arrive with delay." if daily else "Report job active hai; pehli daily report abhi generate nahi hui."}
    except HTTPException:
        raise
    except (ValueError, KeyError, TypeError, csv.Error, gzip.BadGzipFile):
        raise HTTPException(status_code=502, detail="YouTube reach report parse nahi ho paayi.") from None


@app.get("/api/admin/publishing/history")
def publishing_history(platform: str = Query(default="", max_length=30),
                       status: str = Query(default="", max_length=40),
                       limit: int = Query(default=100, ge=1, le=250)):
    allowed = {"youtube","youtube_shorts","facebook","instagram","tiktok","website"}
    if platform and platform not in allowed:
        raise HTTPException(status_code=422, detail="Unsupported publishing platform filter.")
    clauses=[]; params=[]
    if platform: clauses.append("h.platform=?"); params.append(platform)
    if status: clauses.append("h.status=?"); params.append(status)
    where=(" WHERE "+" AND ".join(clauses)) if clauses else ""
    with db() as conn:
        rows=conn.execute("""SELECT h.id,h.calendar_id,h.platform,h.status,h.external_id,h.detail,h.post_url,h.created_at,
            c.title FROM publishing_history h LEFT JOIN content_calendar c ON c.id=h.calendar_id
            """+where+" ORDER BY h.id DESC LIMIT ?",(*params,limit)).fetchall()
        counts=conn.execute("SELECT status,COUNT(*) AS total FROM publishing_history GROUP BY status").fetchall()
    totals={"events":sum(int(r["total"]) for r in counts),
        "published":sum(int(r["total"]) for r in counts if r["status"]=="Published"),
        "processing":sum(int(r["total"]) for r in counts if r["status"] in {"PROCESSING_UPLOAD","PROCESSING","PUBLISHING"}),
        "failed":sum(int(r["total"]) for r in counts if r["status"] in {"FAILED","PUBLISH_FAILED","ERROR"})}
    return {"items":[dict(r) for r in rows],"totals":totals,"filters":{"platform":platform,"status":status,"limit":limit},
        "note":"Actual platform responses aur processing states record hote hain; legacy events backfill nahi hue hain."}


@app.get("/api/admin/scheduler/queue")
def scheduler_queue(hours: int = Query(default=24, ge=1, le=168),
                    limit: int = Query(default=100, ge=1, le=250)):
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(hours=hours)
    with db() as conn:
        rows = conn.execute("""SELECT id,title,platform,prompt,scheduled_at,status,created_at,approved_at
            FROM content_calendar WHERE status NOT IN ('Cancelled','Published')
            ORDER BY scheduled_at ASC LIMIT ?""", (limit,)).fetchall()
    items=[]
    for row in rows:
        item=dict(row)
        try:
            scheduled=datetime.fromisoformat(item["scheduled_at"].replace("Z","+00:00"))
            if scheduled.tzinfo is None: scheduled=scheduled.replace(tzinfo=timezone.utc)
            scheduled=scheduled.astimezone(timezone.utc)
        except (ValueError,TypeError):
            item["queue_state"]="invalid_schedule";items.append(item);continue
        item["queue_state"]=("awaiting_approval" if item["status"]=="Needs approval" else
            "overdue_awaiting_manual_publish" if item["status"]=="Approved" and scheduled<=now else
            "approved_upcoming" if item["status"]=="Approved" and scheduled<=horizon else
            "scheduled_later" if item["status"]=="Approved" else "not_approved")
        item["scheduled_at_utc"]=scheduled.isoformat()
        items.append(item)
    return {"items":items,"summary":{
        "awaiting_approval":sum(x["queue_state"]=="awaiting_approval" for x in items),
        "due_for_manual_action":sum(x["queue_state"]=="overdue_awaiting_manual_publish" for x in items),
        "approved_next_window":sum(x["queue_state"]=="approved_upcoming" for x in items),
        "approved_later":sum(x["queue_state"]=="scheduled_later" for x in items)},
        "window_hours":hours,"checked_at":now.isoformat(),
        "notice":"Scheduler due items ko queue mein dikhata hai. Public publishing hamesha admin ke separate manual confirmation ke baad hoti hai."}


@app.get("/api/calendar")
def calendar_items():
    with db() as conn:
        rows = conn.execute(
            "SELECT id,title,platform,prompt,scheduled_at,status,created_at,approved_at FROM content_calendar ORDER BY scheduled_at ASC LIMIT 200"
        ).fetchall()
    return {"items": [dict(row) for row in rows],
            "publishing_mode": "manual_approval_only",
            "notice": "Calendar reminders and approvals only; automatic publishing is not connected."}


@app.post("/api/calendar")
def create_calendar_item(payload: CalendarItemInput):
    title, prompt = payload.title.strip(), payload.prompt.strip()
    if not title or not prompt:
        raise HTTPException(status_code=400, detail="Title and content prompt are required.")
    try:
        scheduled = datetime.fromisoformat(payload.scheduled_at.replace("Z", "+00:00"))
        if scheduled.tzinfo is None:
            raise ValueError("Timezone offset required")
        scheduled = scheduled.astimezone(timezone.utc)
    except ValueError:
        raise HTTPException(status_code=422, detail="scheduled_at must be an ISO-8601 datetime with timezone.")
    if scheduled <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Choose a future date and time.")
    created = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO content_calendar(title,platform,prompt,scheduled_at,status,created_at) VALUES(?,?,?,?,?,?)",
            (title, payload.platform, prompt, scheduled.isoformat(), "Needs approval", created)
        )
        item_id = cur.lastrowid
    return {"id": item_id, "status": "Needs approval", "scheduled_at": scheduled.isoformat(),
            "message": "Saved to calendar. Admin/editor approval is required; nothing will publish automatically."}


@app.post("/api/calendar/{item_id}/approve")
def approve_calendar_item(item_id: int):
    with db() as conn:
        row = conn.execute("SELECT id,status FROM content_calendar WHERE id=?", (item_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Calendar item not found.")
        if row["status"] != "Needs approval":
            raise HTTPException(status_code=409, detail="Only items awaiting approval can be approved.")
        approved = datetime.now(timezone.utc).isoformat()
        conn.execute("UPDATE content_calendar SET status='Approved',approved_at=? WHERE id=?", (approved,item_id))
    return {"id": item_id, "status": "Approved", "approved_at": approved,
            "message": "Approved in calendar. Publishing still requires a connected official platform integration and a separate publish action."}


@app.post("/api/calendar/{item_id}/cancel")
def cancel_calendar_item(item_id: int):
    with db() as conn:
        row = conn.execute("SELECT id,status FROM content_calendar WHERE id=?", (item_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Calendar item not found.")
        if row["status"] in {"Cancelled", "Published"}:
            raise HTTPException(status_code=409, detail="This calendar item cannot be cancelled.")
        conn.execute("UPDATE content_calendar SET status='Cancelled' WHERE id=?", (item_id,))
    return {"id": item_id, "status": "Cancelled"}


@app.get("/api/tasks")
def tasks():
    with db() as conn:
        rows = conn.execute(
            "SELECT id, prompt, workflow, status, created_at, output FROM tasks ORDER BY id DESC LIMIT 100"
        ).fetchall()
    return {"tasks": [dict(row) for row in rows]}

@app.post("/api/tasks/{task_id}/retry")
def retry_task(task_id: int):
    with db() as conn:
        row = conn.execute("SELECT id, prompt, workflow, status FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Task not found")
        if row["status"] not in {"Failed", "Blocked"}:
            raise HTTPException(status_code=409, detail="Only Failed or Blocked tasks can be retried.")
        conn.execute("UPDATE tasks SET status='Generating', output=NULL WHERE id=?", (task_id,))
    try:
        selected_provider = _get_app_setting("selected_provider", os.getenv("AI_PROVIDER", "auto").lower())
        if selected_provider == os.getenv("AI_PROVIDER", "auto").lower():
            result = generate_text(row["prompt"], row["workflow"])
        else:
            result = generate_text(row["prompt"], row["workflow"], selected_provider)
    except ProviderNotConfigured as exc:
        with db() as conn:
            conn.execute("UPDATE tasks SET status='Blocked' WHERE id=?", (task_id,))
        raise HTTPException(status_code=503, detail=str(exc))
    except ProviderRequestError as exc:
        with db() as conn:
            conn.execute("UPDATE tasks SET status='Failed' WHERE id=?", (task_id,))
        raise HTTPException(status_code=502, detail=str(exc))
    with db() as conn:
        conn.execute("UPDATE tasks SET status='Completed', output=? WHERE id=?", (result["output"], task_id))
    return {"id": task_id, "status": "Completed", "provider": result["provider"],
            "model": result["model"], "output": result["output"]}


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
    paid_selected = os.getenv("MUSIC_PROVIDER", "local").strip().lower() == "stability" and music_status().get("paid_available", False)
    if paid_selected and (not expected or not hmac.compare_digest(media_token, expected)):
        raise HTTPException(status_code=403, detail="Valid media access token required for the optional paid music provider.")
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
    media_type, filename = "audio/mpeg", f"sintu-music-{music_id}.mp3"
    if not path.is_file():
        path = MUSIC_DIR / f"{music_id}.wav"
        media_type, filename = "audio/wav", f"sintu-music-{music_id}.wav"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Music not found")
    return FileResponse(path, media_type=media_type, filename=filename)

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
            audio_path = AUDIO_DIR / f"{payload.audio_id}.wav"
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
    if not image_status().get("local_available") and (not expected or not hmac.compare_digest(media_token, expected)):
        raise HTTPException(status_code=403, detail="Valid media access token required for the optional paid image provider.")
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
    if not voice_status().get("local_available") and (not expected or not hmac.compare_digest(media_token, expected)):
        raise HTTPException(status_code=403, detail="Valid media access token required for the optional paid voice provider.")
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
    media_type, filename = "audio/mpeg", f"sintu-voice-{audio_id}.mp3"
    if not path.is_file():
        path = AUDIO_DIR / f"{audio_id}.wav"
        media_type, filename = "audio/wav", f"sintu-voice-{audio_id}.wav"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Audio not found")
    return FileResponse(path, media_type=media_type, filename=filename)


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
    configured = providers["local"]["configured"]
    return {
        "agents_total": len(list_agents()),
        "agents_implemented": 0,
        "specialist_roles": scope_summary()["specialist_count"],
        "independent_checker_roles": scope_summary()["independent_checker_count"],
        "video_formats": scope_summary()["video_format_count"],
        "studio_modules": scope_summary()["studio_module_count"],
        "paid_upgrades_allowed": paid_upgrades_allowed(),
        "roles_routed": orchestration_summary()["roles_routed"],
        "orchestration_mode": orchestration_summary()["execution_mode"],
        "workflows_available": len(WORKFLOW_GUIDES),
        "tasks_saved": count,
        "tasks_completed": completed,
        "ai_provider_configured": configured,
        "video_generation": "Not configured",
        "publishing": "Not configured",
    }
