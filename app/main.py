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

from fastapi import FastAPI, HTTPException, Header, Request, Query
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
    selected_provider: str = Field(pattern=r"^(auto|openai|gemini)$")


@app.get("/api/admin/provider-settings")
def admin_provider_settings():
    selected = _get_app_setting("selected_provider", os.getenv("AI_PROVIDER", "auto").lower())
    status = provider_status(selected)
    return {
        "selected_provider": status["selected"],
        "providers": {
            key: {"configured": value["configured"], "model": value["model"]}
            for key, value in status.items() if key in {"openai", "gemini"}
        },
        "secret_policy": "API keys are read only from server environment variables and are never accepted or returned by this dashboard."
    }


@app.patch("/api/admin/provider-settings")
def update_admin_provider_settings(payload: ProviderSettingsInput):
    status = provider_status(payload.selected_provider)
    if payload.selected_provider in {"openai", "gemini"} and not status[payload.selected_provider]["configured"]:
        raise HTTPException(status_code=400, detail=f"{payload.selected_provider} API key server par configured nahi hai.")
    _set_app_setting("selected_provider", payload.selected_provider)
    return admin_provider_settings()


@app.get("/api/admin/integrations")
def admin_integrations():
    providers = admin_provider_settings()
    paid_media = os.getenv("ENABLE_PAID_MEDIA_GENERATION", "false").lower() == "true"
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


@app.post("/api/admin/youtube/oauth/start")
def youtube_oauth_start(request: Request):
    config = _youtube_config()
    if not config["client_id"] or not config["client_secret"] or not config["redirect_uri"]:
        raise HTTPException(status_code=503, detail="YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET aur YOUTUBE_REDIRECT_URI configure karein.")
    _youtube_cipher()
    actor = getattr(request.state, "user", {}) or {}
    state = secrets.token_urlsafe(32)
    expiry = int(time.time()) + 600
    with db() as conn:
        conn.execute("DELETE FROM youtube_oauth_states WHERE expires_at < ?", (int(time.time()),))
        conn.execute("INSERT INTO youtube_oauth_states(state,admin_user_id,session_hash,expires_at) VALUES(?,?,?,?)",
                     (state, actor["id"], hashlib.sha256((request.cookies.get(SESSION_COOKIE) or "local-dev-session").encode()).hexdigest(), expiry))
    params = urllib.parse.urlencode({
        "client_id": config["client_id"], "redirect_uri": config["redirect_uri"],
        "response_type": "code", "scope": "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly https://www.googleapis.com/auth/yt-analytics.readonly https://www.googleapis.com/auth/yt-analytics-monetary.readonly",
        "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true", "state": state
    })
    return {"authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?" + params,
            "expires_in": 600, "message": "Google consent ke baad isi admin session mein callback complete hoga."}


@app.get("/api/admin/youtube/oauth/callback")
def youtube_oauth_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    from fastapi.responses import RedirectResponse
    if error:
        return RedirectResponse("/?youtube_oauth=denied", status_code=303)
    actor = getattr(request.state, "user", {}) or {}
    with db() as conn:
        saved = conn.execute("SELECT admin_user_id,session_hash,expires_at FROM youtube_oauth_states WHERE state=?", (state,)).fetchone()
        conn.execute("DELETE FROM youtube_oauth_states WHERE state=?", (state,))
    session_hash = hashlib.sha256((request.cookies.get(SESSION_COOKIE) or "local-dev-session").encode()).hexdigest()
    if not state or not saved or saved["admin_user_id"] != actor.get("id") or saved["session_hash"] != session_hash or saved["expires_at"] < int(time.time()):
        raise HTTPException(status_code=400, detail="OAuth state invalid/expired. Dobara Connect karein.")
    if not code:
        raise HTTPException(status_code=400, detail="Google authorization code missing.")
    config = _youtube_config()
    payload = urllib.parse.urlencode({
        "code": code, "client_id": config["client_id"], "client_secret": config["client_secret"],
        "redirect_uri": config["redirect_uri"], "grant_type": "authorization_code"
    }).encode()
    _, _, token_body = _youtube_request("https://oauth2.googleapis.com/token", payload,
                                        {"Content-Type": "application/x-www-form-urlencoded"})
    tokens = json.loads(token_body.decode())
    access_token = tokens.get("access_token")
    if not access_token:
        raise HTTPException(status_code=502, detail="Google ne access token return nahi kiya.")
    _, _, channel_body = _youtube_request(
        "https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true",
        headers={"Authorization": "Bearer " + access_token})
    channels = json.loads(channel_body.decode()).get("items", [])
    if not channels:
        raise HTTPException(status_code=404, detail="Is Google account par YouTube channel nahi mila.")
    channel = channels[0]
    with db() as conn:
        old = conn.execute("SELECT encrypted_tokens FROM youtube_connection WHERE id=1").fetchone()
    if not tokens.get("refresh_token") and old:
        try:
            previous = json.loads(_youtube_cipher().decrypt(old["encrypted_tokens"].encode()).decode())
            tokens["refresh_token"] = previous.get("refresh_token")
        except (InvalidToken, ValueError, json.JSONDecodeError):
            pass
    expiry = int(time.time()) + int(tokens.get("expires_in", 3600))
    encrypted = _youtube_cipher().encrypt(json.dumps(tokens).encode()).decode()
    with db() as conn:
        conn.execute("""INSERT INTO youtube_connection(id,channel_id,channel_title,encrypted_tokens,token_expiry,connected_at)
            VALUES(1,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET channel_id=excluded.channel_id,
            channel_title=excluded.channel_title,encrypted_tokens=excluded.encrypted_tokens,
            token_expiry=excluded.token_expiry,connected_at=excluded.connected_at""",
            (channel["id"], channel.get("snippet", {}).get("title", "YouTube Channel"), encrypted, expiry,
             datetime.now(timezone.utc).isoformat()))
    return RedirectResponse("/?youtube_oauth=connected", status_code=303)


@app.post("/api/admin/youtube/disconnect")
def youtube_disconnect():
    with db() as conn:
        conn.execute("DELETE FROM youtube_connection WHERE id=1")
    return {"connected": False, "message": "YouTube channel disconnected; encrypted tokens deleted."}


@app.post("/api/admin/youtube/publish/{calendar_id}")
def youtube_publish(calendar_id: int, video_id: str = Query(..., min_length=32, max_length=32),
                    title: str = Query(..., min_length=1, max_length=100),
                    description: str = Query(default="", max_length=5000),
                    privacy_status: str = Query(default="private", pattern=r"^(private|unlisted|public)$")):
    if not re.fullmatch(r"[a-f0-9]{32}", video_id):
        raise HTTPException(status_code=400, detail="Invalid rendered video ID.")
    with db() as conn:
        item = conn.execute("SELECT id,title,status,platform FROM content_calendar WHERE id=?", (calendar_id,)).fetchone()
    if not item:
        raise HTTPException(status_code=404, detail="Calendar item not found.")
    if item["status"] != "Approved" or item["platform"] not in {"youtube", "youtube_shorts"}:
        raise HTTPException(status_code=409, detail="YouTube calendar item approved hona chahiye.")
    path = OUTPUT_DIR / (video_id + ".mp4")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Rendered MP4 file nahi mili.")
    size = path.stat().st_size
    if size <= 0 or size > 512 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="MP4 size 1 byte se 512 MB ke beech honi chahiye.")
    access_token = _youtube_access_token()
    metadata = json.dumps({"snippet": {"title": title.strip(), "description": description,
        "categoryId": "22"}, "status": {"privacyStatus": privacy_status}}).encode()
    _, headers, _ = _youtube_request("https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        metadata, {"Authorization": "Bearer " + access_token, "Content-Type": "application/json; charset=UTF-8",
                   "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)}, "POST")
    upload_url = headers.get("Location")
    if not upload_url or not upload_url.startswith("https://www.googleapis.com/upload/youtube/"):
        raise HTTPException(status_code=502, detail="Google resumable upload URL invalid hai.")
    with path.open("rb") as video_file:
        _, _, result_body = _youtube_request(upload_url, video_file.read(), {"Authorization": "Bearer " + access_token,
            "Content-Type": "video/mp4", "Content-Length": str(size)}, "PUT")
    uploaded = json.loads(result_body.decode())
    youtube_id = uploaded.get("id")
    if not youtube_id:
        raise HTTPException(status_code=502, detail="YouTube ne video ID return nahi ki.")
    post_url = "https://www.youtube.com/watch?v=" + youtube_id
    with db() as conn:
        conn.execute("UPDATE content_calendar SET status='Published' WHERE id=?", (calendar_id,))
    _record_publish_event(calendar_id, item["platform"], "Published", youtube_id, "YouTube video uploaded", post_url)
    return {"calendar_id": calendar_id, "youtube_video_id": youtube_id, "status": "Published",
            "url": post_url, "privacy_status": privacy_status}



def _meta_config():
    return {"app_id": os.getenv("META_APP_ID", "").strip(),
            "app_secret": os.getenv("META_APP_SECRET", "").strip(),
            "redirect_uri": os.getenv("META_REDIRECT_URI", "").strip(),
            "version": os.getenv("META_GRAPH_API_VERSION", "v26.0").strip(), "encryption_key": os.getenv("YOUTUBE_TOKEN_ENCRYPTION_KEY", "").strip()}


def _meta_graph_request(path, data=None, access_token=None, method="POST"):
    config = _meta_config()
    if not path.startswith("/") or ".." in path:
        raise HTTPException(status_code=400, detail="Invalid Meta Graph API path.")
    params = dict(data or {})
    if access_token:
        params["access_token"] = access_token
    url = "https://graph.facebook.com/" + config["version"] + path
    payload = urllib.parse.urlencode(params).encode() if params else None
    if method == "GET" and payload:
        url += "?" + payload.decode()
        payload = None
    request = urllib.request.Request(url, data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read(2500).decode("utf-8", errors="replace")
        raise HTTPException(status_code=502, detail="Meta Graph API error ("+str(exc.code)+"): "+detail[:600]) from None
    except (urllib.error.URLError, TimeoutError):
        raise HTTPException(status_code=502, detail="Meta Graph API connection failed.") from None
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=502, detail="Meta API response invalid.") from None


def _meta_connection():
    with db() as conn:
        row = conn.execute("SELECT page_id,page_name,instagram_user_id,instagram_username,connected_at FROM meta_connection WHERE id=1").fetchone()
    return dict(row) if row else None


def _meta_tokens():
    config = _meta_config()
    if not config["app_id"] or not config["app_secret"]:
        raise HTTPException(status_code=503, detail="META_APP_ID aur META_APP_SECRET configure karein.")
    with db() as conn:
        row = conn.execute("SELECT encrypted_tokens FROM meta_connection WHERE id=1").fetchone()
    if not row:
        raise HTTPException(status_code=409, detail="Pehle Facebook Page connect karein.")
    try:
        return json.loads(_youtube_cipher().decrypt(row["encrypted_tokens"].encode()).decode())
    except (InvalidToken, ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=503, detail="Meta credentials decrypt nahi ho rahe; reconnect karein.") from None


@app.get("/api/admin/meta/status")
def meta_admin_status():
    config, connection = _meta_config(), _meta_connection()
    return {"oauth_configured": bool(config["app_id"] and config["app_secret"] and config["redirect_uri"]),
            "encryption_configured": bool(config["encryption_key"]),
            "connected": bool(connection),
            "page": {"id": connection["page_id"], "name": connection["page_name"]} if connection else None,
            "instagram": {"id": connection["instagram_user_id"], "username": connection["instagram_username"]} if connection and connection["instagram_user_id"] else None,
            "note": "Facebook Page upload local MP4 se hota hai. Instagram Reels ke liye Professional account aur public HTTPS video URL required hai."}


@app.post("/api/admin/meta/oauth/start")
def meta_oauth_start(request: Request):
    config = _meta_config()
    if not config["app_id"] or not config["app_secret"] or not config["redirect_uri"]:
        raise HTTPException(status_code=503, detail="META_APP_ID, META_APP_SECRET aur META_REDIRECT_URI configure karein.")
    _youtube_cipher()
    actor = getattr(request.state, "user", {}) or {}
    state, expiry = secrets.token_urlsafe(32), int(time.time()) + 600
    session_hash = hashlib.sha256((request.cookies.get(SESSION_COOKIE) or "local-dev-session").encode()).hexdigest()
    with db() as conn:
        conn.execute("DELETE FROM meta_oauth_states WHERE expires_at < ?", (int(time.time()),))
        conn.execute("INSERT INTO meta_oauth_states(state,admin_user_id,session_hash,expires_at) VALUES(?,?,?,?)",
                     (state, actor["id"], session_hash, expiry))
    params = urllib.parse.urlencode({"client_id": config["app_id"], "redirect_uri": config["redirect_uri"],
        "response_type": "code", "scope": "pages_show_list,pages_read_engagement,pages_manage_posts,instagram_basic,instagram_content_publish", "state": state})
    return {"authorization_url": "https://www.facebook.com/"+config["version"]+"/dialog/oauth?"+params, "expires_in": 600}


@app.get("/api/admin/meta/oauth/callback")
def meta_oauth_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    from fastapi.responses import RedirectResponse
    if error:
        return RedirectResponse("/?meta_oauth=denied", status_code=303)
    actor = getattr(request.state, "user", {}) or {}
    with db() as conn:
        saved = conn.execute("SELECT admin_user_id,session_hash,expires_at FROM meta_oauth_states WHERE state=?", (state,)).fetchone()
        conn.execute("DELETE FROM meta_oauth_states WHERE state=?", (state,))
    session_hash = hashlib.sha256((request.cookies.get(SESSION_COOKIE) or "local-dev-session").encode()).hexdigest()
    if not state or not saved or saved["admin_user_id"] != actor.get("id") or saved["session_hash"] != session_hash or saved["expires_at"] < int(time.time()):
        raise HTTPException(status_code=400, detail="Meta OAuth state invalid/expired. Dobara connect karein.")
    if not code:
        raise HTTPException(status_code=400, detail="Meta authorization code missing.")
    cfg = _meta_config()
    short = _meta_graph_request("/oauth/access_token", {"client_id":cfg["app_id"],"client_secret":cfg["app_secret"],"redirect_uri":cfg["redirect_uri"],"code":code}, method="GET")
    if not short.get("access_token"):
        raise HTTPException(status_code=502, detail="Meta access token missing.")
    long = _meta_graph_request("/oauth/access_token", {"grant_type":"fb_exchange_token","client_id":cfg["app_id"],"client_secret":cfg["app_secret"],"fb_exchange_token":short["access_token"]}, method="GET")
    user_token = long.get("access_token", short["access_token"])
    pages = _meta_graph_request("/me/accounts", {"fields":"id,name,access_token,instagram_business_account{id,username}","limit":100}, user_token, method="GET").get("data",[])
    page = next((p for p in pages if p.get("access_token")), None)
    if not page:
        raise HTTPException(status_code=404, detail="Manageable Facebook Page/access token nahi mila. Page roles aur permissions check karein.")
    ig = page.get("instagram_business_account") or {}
    encrypted = _youtube_cipher().encrypt(json.dumps({"page_access_token":page["access_token"],"user_access_token":user_token}).encode()).decode()
    with db() as conn:
        conn.execute("""INSERT INTO meta_connection(id,page_id,page_name,instagram_user_id,instagram_username,encrypted_tokens,connected_at)
            VALUES(1,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET page_id=excluded.page_id,page_name=excluded.page_name,
            instagram_user_id=excluded.instagram_user_id,instagram_username=excluded.instagram_username,
            encrypted_tokens=excluded.encrypted_tokens,connected_at=excluded.connected_at""",
            (page["id"],page.get("name","Facebook Page"),ig.get("id"),ig.get("username"),encrypted,datetime.now(timezone.utc).isoformat()))
    return RedirectResponse("/?meta_oauth=connected", status_code=303)


@app.post("/api/admin/meta/disconnect")
def meta_disconnect():
    with db() as conn:
        conn.execute("DELETE FROM meta_connection WHERE id=1")
    return {"connected":False,"message":"Meta Page disconnected; encrypted tokens deleted."}


@app.post("/api/admin/meta/facebook/publish/{calendar_id}")
def meta_facebook_publish(calendar_id:int, video_id:str=Query(...,min_length=32,max_length=32),
                          title:str=Query(...,min_length=1,max_length=255), description:str=Query(default="",max_length=5000)):
    if not re.fullmatch(r"[a-f0-9]{32}",video_id):
        raise HTTPException(status_code=400,detail="Invalid rendered video ID.")
    with db() as conn:
        item=conn.execute("SELECT id,status,platform FROM content_calendar WHERE id=?",(calendar_id,)).fetchone()
    if not item or item["status"]!="Approved" or item["platform"]!="facebook":
        raise HTTPException(status_code=409,detail="Facebook calendar item approved hona chahiye.")
    path=OUTPUT_DIR/(video_id+".mp4")
    if not path.is_file() or path.stat().st_size<=0 or path.stat().st_size>512*1024*1024:
        raise HTTPException(status_code=404,detail="Valid rendered MP4 (max 512 MB) nahi mili.")
    connection=_meta_connection()
    if not connection: raise HTTPException(status_code=409,detail="Meta Facebook Page connect nahi hai.")
    tokens=_meta_tokens()
    boundary="----SINTU"+secrets.token_hex(16)
    body=bytearray()
    for key,value in {"title":title.strip(),"description":description,"access_token":tokens["page_access_token"]}.items():
        body.extend(("--"+boundary+"\r\\n").encode())
        body.extend(('Content-Disposition: form-data; name="'+key+'"\\r\\n\\r\\n'+str(value)+"\\r\\n").encode())
    body.extend(("--"+boundary+"\\r\\n").encode())
    body.extend(('Content-Disposition: form-data; name="source"; filename="sintu.mp4"\\r\\nContent-Type: video/mp4\\r\\n\\r\\n').encode())
    body.extend(path.read_bytes()); body.extend(("\\r\\n--"+boundary+"--\\r\\n").encode())
    url="https://graph.facebook.com/"+_meta_config()["version"]+"/"+connection["page_id"]+"/videos"
    req=urllib.request.Request(url,data=bytes(body),headers={"Content-Type":"multipart/form-data; boundary="+boundary},method="POST")
    try:
        with urllib.request.urlopen(req,timeout=180) as response: uploaded=json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail=exc.read(2500).decode("utf-8",errors="replace")
        raise HTTPException(status_code=502,detail="Facebook upload failed ("+str(exc.code)+"): "+detail[:600]) from None
    except (urllib.error.URLError,TimeoutError):
        raise HTTPException(status_code=502,detail="Facebook upload connection failed.") from None
    post_id=uploaded.get("id")
    if not post_id: raise HTTPException(status_code=502,detail="Facebook video ID missing in API response.")
    post_url = "https://www.facebook.com/"+post_id
    with db() as conn: conn.execute("UPDATE content_calendar SET status='Published' WHERE id=?",(calendar_id,))
    _record_publish_event(calendar_id, "facebook", "Published", post_id, "Facebook Page video published", post_url)
    return {"calendar_id":calendar_id,"facebook_video_id":post_id,"status":"Published","url":post_url}


@app.post("/api/admin/meta/instagram/publish/{calendar_id}")
def meta_instagram_publish(calendar_id:int,video_url:str=Query(...,min_length=12,max_length=2048),caption:str=Query(default="",max_length=2200)):
    parsed=urllib.parse.urlparse(video_url)
    if parsed.scheme!="https" or not parsed.hostname or parsed.username or parsed.password or parsed.hostname.lower() in {"localhost","127.0.0.1","::1"} or parsed.hostname.lower().endswith(".local"):
        raise HTTPException(status_code=400,detail="Valid public HTTPS MP4 URL required; localhost/private URLs not supported.")
    with db() as conn:
        item=conn.execute("SELECT id,status,platform FROM content_calendar WHERE id=?",(calendar_id,)).fetchone()
    if not item or item["status"]!="Approved" or item["platform"]!="instagram":
        raise HTTPException(status_code=409,detail="Instagram calendar item approved hona chahiye.")
    connection=_meta_connection()
    if not connection or not connection["instagram_user_id"]:
        raise HTTPException(status_code=409,detail="Linked Instagram Professional (Business/Creator) account nahi mila.")
    token=_meta_tokens()["page_access_token"]
    ig=connection["instagram_user_id"]
    container=_meta_graph_request("/"+ig+"/media",{"media_type":"REELS","video_url":video_url,"caption":caption,"share_to_feed":"true"},token)
    creation_id=container.get("id")
    if not creation_id: raise HTTPException(status_code=502,detail="Instagram media container create nahi hua.")
    deadline=time.time()+150; status={}
    while time.time()<deadline:
        status=_meta_graph_request("/"+creation_id,{"fields":"status_code,status"},token,method="GET")
        if status.get("status_code")=="FINISHED": break
        if status.get("status_code") in {"ERROR","EXPIRED"}:
            raise HTTPException(status_code=502,detail="Instagram processing failed: "+str(status.get("status",status.get("status_code"))))
        time.sleep(3)
    if status.get("status_code")!="FINISHED":
        raise HTTPException(status_code=504,detail="Instagram processing pending; container ID: "+creation_id)
    published=_meta_graph_request("/"+ig+"/media_publish",{"creation_id":creation_id},token)
    media_id=published.get("id")
    if not media_id: raise HTTPException(status_code=502,detail="Instagram media ID missing.")
    with db() as conn: conn.execute("UPDATE content_calendar SET status='Published' WHERE id=?",(calendar_id,))
    _record_publish_event(calendar_id, "instagram", "Published", media_id, "Instagram Reel published")
    return {"calendar_id":calendar_id,"instagram_media_id":media_id,"status":"Published","message":"Instagram Reel published."}



def _tiktok_config():
    return {"client_key":os.getenv("TIKTOK_CLIENT_KEY","").strip(),
            "client_secret":os.getenv("TIKTOK_CLIENT_SECRET","").strip(),
            "redirect_uri":os.getenv("TIKTOK_REDIRECT_URI","").strip(),
            "encryption_key":os.getenv("YOUTUBE_TOKEN_ENCRYPTION_KEY","").strip()}


def _tiktok_request(url, payload=None, headers=None, method="POST", timeout=60):
    if not url.startswith("https://open.tiktokapis.com/") and not url.startswith("https://open-upload.tiktokapis.com/") and not url.startswith("https://www.tiktok.com/"):
        raise HTTPException(status_code=400,detail="TikTok API URL rejected.")
    request=urllib.request.Request(url,data=payload,headers=headers or {},method=method)
    try:
        with urllib.request.urlopen(request,timeout=timeout) as response:
            raw=response.read()
            return response.status,dict(response.headers.items()),json.loads(raw.decode()) if raw else {}
    except urllib.error.HTTPError as exc:
        detail=exc.read(3000).decode("utf-8",errors="replace")
        raise HTTPException(status_code=502,detail="TikTok API error ("+str(exc.code)+"): "+detail[:700]) from None
    except (urllib.error.URLError,TimeoutError):
        raise HTTPException(status_code=502,detail="TikTok API connection failed.") from None
    except (ValueError,UnicodeDecodeError):
        raise HTTPException(status_code=502,detail="TikTok API response invalid.") from None


def _tiktok_connection():
    with db() as conn:
        row=conn.execute("SELECT open_id,display_name,token_expiry,refresh_expiry,scopes,connected_at FROM tiktok_connection WHERE id=1").fetchone()
    return dict(row) if row else None


def _tiktok_tokens():
    config=_tiktok_config()
    if not config["client_key"] or not config["client_secret"]:
        raise HTTPException(status_code=503,detail="TIKTOK_CLIENT_KEY aur TIKTOK_CLIENT_SECRET configure karein.")
    with db() as conn:
        row=conn.execute("SELECT encrypted_tokens,token_expiry,refresh_expiry FROM tiktok_connection WHERE id=1").fetchone()
    if not row: raise HTTPException(status_code=409,detail="Pehle TikTok account connect karein.")
    try: tokens=json.loads(_youtube_cipher().decrypt(row["encrypted_tokens"].encode()).decode())
    except (InvalidToken,ValueError,json.JSONDecodeError):
        raise HTTPException(status_code=503,detail="TikTok credentials decrypt nahi ho rahe; reconnect karein.") from None
    if int(row["token_expiry"])<=int(time.time())+120:
        if int(row["refresh_expiry"])<=int(time.time()) or not tokens.get("refresh_token"):
            raise HTTPException(status_code=401,detail="TikTok refresh token expire ho gaya; account reconnect karein.")
        payload=urllib.parse.urlencode({"client_key":config["client_key"],"client_secret":config["client_secret"],
            "grant_type":"refresh_token","refresh_token":tokens["refresh_token"]}).encode()
        _,_,refreshed=_tiktok_request("https://open.tiktokapis.com/v2/oauth/token/",payload,
            {"Content-Type":"application/x-www-form-urlencoded"})
        if refreshed.get("error") not in (None,"","ok") or not refreshed.get("access_token"):
            raise HTTPException(status_code=401,detail="TikTok token refresh failed; reconnect karein.")
        tokens.update(refreshed)
        expiry=int(time.time())+int(refreshed.get("expires_in",86400))
        refresh_expiry=int(time.time())+int(refreshed.get("refresh_expires_in",0))
        encrypted=_youtube_cipher().encrypt(json.dumps(tokens).encode()).decode()
        with db() as conn:
            conn.execute("UPDATE tiktok_connection SET encrypted_tokens=?,token_expiry=?,refresh_expiry=?,scopes=? WHERE id=1",
                (encrypted,expiry,refresh_expiry,str(tokens.get("scope",""))))
    return tokens


def _tiktok_creator_info(tokens):
    _,_,body=_tiktok_request("https://open.tiktokapis.com/v2/post/publish/creator_info/query/",
        json.dumps({}).encode(),{"Authorization":"Bearer "+tokens["access_token"],"Content-Type":"application/json; charset=UTF-8"})
    if body.get("error",{}).get("code")!="ok":
        raise HTTPException(status_code=502,detail="TikTok creator info failed: "+str(body.get("error",{}).get("message","unknown error")))
    return body.get("data",{})


@app.get("/api/admin/tiktok/status")
def tiktok_admin_status():
    cfg=_tiktok_config(); connection=_tiktok_connection()
    return {"oauth_configured":bool(cfg["client_key"] and cfg["client_secret"] and cfg["redirect_uri"]),
        "encryption_configured":bool(cfg["encryption_key"]),"connected":bool(connection),
        "creator":{"open_id":connection["open_id"],"display_name":connection["display_name"]} if connection else None,
        "scopes":connection["scopes"].split(",") if connection and connection["scopes"] else [],
        "note":"TikTok Content Posting API approval and video.publish scope required. Unaudited apps can only post privately."}


@app.post("/api/admin/tiktok/oauth/start")
def tiktok_oauth_start(request:Request):
    cfg=_tiktok_config()
    if not cfg["client_key"] or not cfg["client_secret"] or not cfg["redirect_uri"]:
        raise HTTPException(status_code=503,detail="TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET aur TIKTOK_REDIRECT_URI configure karein.")
    parsed=urllib.parse.urlparse(cfg["redirect_uri"])
    if parsed.scheme!="https" or not parsed.netloc or parsed.query or parsed.fragment:
        raise HTTPException(status_code=503,detail="TikTok web redirect URI registered HTTPS static URL hona chahiye.")
    _youtube_cipher()
    actor=getattr(request.state,"user",{}) or {}
    state=secrets.token_urlsafe(32); expiry=int(time.time())+600
    session_hash=hashlib.sha256((request.cookies.get(SESSION_COOKIE) or "local-dev-session").encode()).hexdigest()
    with db() as conn:
        conn.execute("DELETE FROM tiktok_oauth_states WHERE expires_at < ?",(int(time.time()),))
        conn.execute("INSERT INTO tiktok_oauth_states(state,admin_user_id,session_hash,expires_at) VALUES(?,?,?,?)",
            (state,actor["id"],session_hash,expiry))
    params=urllib.parse.urlencode({"client_key":cfg["client_key"],"response_type":"code",
        "scope":"user.info.basic,video.publish","redirect_uri":cfg["redirect_uri"],"state":state})
    return {"authorization_url":"https://www.tiktok.com/v2/auth/authorize/?"+params,"expires_in":600}


@app.get("/api/admin/tiktok/oauth/callback")
def tiktok_oauth_callback(request:Request,code:str="",state:str="",error:str=""):
    from fastapi.responses import RedirectResponse
    if error: return RedirectResponse("/?tiktok_oauth=denied",status_code=303)
    actor=getattr(request.state,"user",{}) or {}
    with db() as conn:
        saved=conn.execute("SELECT admin_user_id,session_hash,expires_at FROM tiktok_oauth_states WHERE state=?",(state,)).fetchone()
        conn.execute("DELETE FROM tiktok_oauth_states WHERE state=?",(state,))
    session_hash=hashlib.sha256((request.cookies.get(SESSION_COOKIE) or "local-dev-session").encode()).hexdigest()
    if not state or not saved or saved["admin_user_id"]!=actor.get("id") or saved["session_hash"]!=session_hash or saved["expires_at"]<int(time.time()):
        raise HTTPException(status_code=400,detail="TikTok OAuth state invalid/expired. Dobara connect karein.")
    if not code: raise HTTPException(status_code=400,detail="TikTok authorization code missing.")
    cfg=_tiktok_config()
    payload=urllib.parse.urlencode({"client_key":cfg["client_key"],"client_secret":cfg["client_secret"],
        "code":code,"grant_type":"authorization_code","redirect_uri":cfg["redirect_uri"]}).encode()
    _,_,tokens=_tiktok_request("https://open.tiktokapis.com/v2/oauth/token/",payload,
        {"Content-Type":"application/x-www-form-urlencoded"})
    if tokens.get("error") not in (None,"","ok") or not tokens.get("access_token") or not tokens.get("open_id"):
        raise HTTPException(status_code=502,detail="TikTok token exchange failed: "+str(tokens.get("error_description",tokens.get("error","missing token"))))
    access=tokens["access_token"]
    _,_,profile=_tiktok_request("https://open.tiktokapis.com/v2/user/info/?fields=open_id,display_name",
        headers={"Authorization":"Bearer "+access},method="GET")
    if profile.get("error",{}).get("code")!="ok":
        raise HTTPException(status_code=502,detail="TikTok profile fetch failed.")
    user=profile.get("data",{}).get("user",{})
    expiry=int(time.time())+int(tokens.get("expires_in",86400))
    refresh_expiry=int(time.time())+int(tokens.get("refresh_expires_in",0))
    encrypted=_youtube_cipher().encrypt(json.dumps(tokens).encode()).decode()
    with db() as conn:
        conn.execute("""INSERT INTO tiktok_connection(id,open_id,display_name,encrypted_tokens,token_expiry,refresh_expiry,scopes,connected_at)
            VALUES(1,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET open_id=excluded.open_id,display_name=excluded.display_name,
            encrypted_tokens=excluded.encrypted_tokens,token_expiry=excluded.token_expiry,refresh_expiry=excluded.refresh_expiry,
            scopes=excluded.scopes,connected_at=excluded.connected_at""",
            (tokens["open_id"],user.get("display_name","TikTok creator"),encrypted,expiry,refresh_expiry,
             str(tokens.get("scope","")),datetime.now(timezone.utc).isoformat()))
    return RedirectResponse("/?tiktok_oauth=connected",status_code=303)


@app.get("/api/admin/tiktok/creator")
def tiktok_creator():
    tokens=_tiktok_tokens(); creator=_tiktok_creator_info(tokens)
    return {"creator":creator}


@app.post("/api/admin/tiktok/disconnect")
def tiktok_disconnect():
    with db() as conn:
        conn.execute("DELETE FROM tiktok_connection WHERE id=1")
        conn.execute("DELETE FROM tiktok_posts")
    return {"connected":False,"message":"TikTok account disconnected; encrypted tokens deleted."}


@app.post("/api/admin/tiktok/publish/{calendar_id}")
def tiktok_publish(calendar_id:int,video_id:str=Query(...,min_length=32,max_length=32),
                   title:str=Query(default="",max_length=2200),privacy_level:str=Query(default="SELF_ONLY"),
                   is_aigc:bool=Query(default=False)):
    if not re.fullmatch(r"[a-f0-9]{32}",video_id): raise HTTPException(status_code=400,detail="Invalid rendered video ID.")
    with db() as conn:
        item=conn.execute("SELECT id,status,platform FROM content_calendar WHERE id=?",(calendar_id,)).fetchone()
    if not item or item["status"]!="Approved" or item["platform"]!="tiktok":
        raise HTTPException(status_code=409,detail="TikTok calendar item approved hona chahiye.")
    with db() as conn:
        pending=conn.execute("SELECT status FROM tiktok_posts WHERE calendar_id=? ORDER BY created_at DESC LIMIT 1",(calendar_id,)).fetchone()
    if pending and pending["status"] not in {"PUBLISH_COMPLETE","FAILED","PUBLISH_FAILED","SEND_TO_USER_INBOX","INBOX_DELIVERED"}:
        raise HTTPException(status_code=409,detail="TikTok par ek post abhi processing mein hai. Pehle status check karein; duplicate upload roka gaya.")
    path=OUTPUT_DIR/(video_id+".mp4")
    if not path.is_file() or path.stat().st_size<=0 or path.stat().st_size>512*1024*1024:
        raise HTTPException(status_code=404,detail="Valid rendered MP4 (max 512 MB) nahi mili.")
    tokens=_tiktok_tokens(); creator=_tiktok_creator_info(tokens)
    allowed=creator.get("privacy_level_options",[])
    if privacy_level not in allowed:
        raise HTTPException(status_code=400,detail="Privacy option TikTok creator info ke mutabik valid nahi. Available: "+", ".join(allowed))
    size=path.stat().st_size; chunk_size=10*1024*1024; chunks=(size+chunk_size-1)//chunk_size
    body={"post_info":{"title":title,"privacy_level":privacy_level,"disable_duet":bool(creator.get("duet_disabled",False)),
        "disable_comment":bool(creator.get("comment_disabled",False)),"disable_stitch":bool(creator.get("stitch_disabled",False)),
        "brand_content_toggle":False,"brand_organic_toggle":False,"is_aigc":bool(is_aigc)},
        "source_info":{"source":"FILE_UPLOAD","video_size":size,"chunk_size":chunk_size,"total_chunk_count":chunks}}
    _,_,result=_tiktok_request("https://open.tiktokapis.com/v2/post/publish/video/init/",
        json.dumps(body).encode(),{"Authorization":"Bearer "+tokens["access_token"],"Content-Type":"application/json; charset=UTF-8"})
    if result.get("error",{}).get("code")!="ok":
        raise HTTPException(status_code=502,detail="TikTok publish init failed: "+str(result.get("error",{}).get("message","unknown error")))
    data=result.get("data",{}); publish_id=data.get("publish_id"); upload_url=data.get("upload_url")
    parsed=urllib.parse.urlparse(upload_url or "")
    if not publish_id or parsed.scheme!="https" or parsed.hostname!="open-upload.tiktokapis.com":
        raise HTTPException(status_code=502,detail="TikTok upload endpoint invalid.")
    with path.open("rb") as video:
        for index in range(chunks):
            start=index*chunk_size; block=video.read(chunk_size); end=start+len(block)-1
            _,_,_= _tiktok_request(upload_url,block,{"Content-Type":"video/mp4","Content-Length":str(len(block)),
                "Content-Range":f"bytes {start}-{end}/{size}"},method="PUT",timeout=180)
    now=datetime.now(timezone.utc).isoformat()
    with db() as conn:
        conn.execute("INSERT OR REPLACE INTO tiktok_posts(publish_id,calendar_id,status,status_detail,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (publish_id,calendar_id,"PROCESSING_UPLOAD","Video uploaded to TikTok; processing continues asynchronously.",now,now))
    _record_publish_event(calendar_id, "tiktok", "PROCESSING_UPLOAD", publish_id, "Video transferred; TikTok processing pending")
    return {"calendar_id":calendar_id,"publish_id":publish_id,"status":"PROCESSING_UPLOAD",
        "message":"Video TikTok par transfer ho gaya. TikTok processing status check karein; publish completion abhi pending hai."}


@app.post("/api/admin/tiktok/status/{calendar_id}")
def tiktok_publish_status(calendar_id:int):
    with db() as conn:
        row=conn.execute("SELECT publish_id,status,status_detail FROM tiktok_posts WHERE calendar_id=? ORDER BY created_at DESC LIMIT 1",(calendar_id,)).fetchone()
    if not row: raise HTTPException(status_code=404,detail="TikTok publish job not found.")
    tokens=_tiktok_tokens()
    _,_,result=_tiktok_request("https://open.tiktokapis.com/v2/post/publish/status/fetch/",
        json.dumps({"publish_id":row["publish_id"]}).encode(),{"Authorization":"Bearer "+tokens["access_token"],"Content-Type":"application/json; charset=UTF-8"})
    if result.get("error",{}).get("code")!="ok":
        raise HTTPException(status_code=502,detail="TikTok status fetch failed: "+str(result.get("error",{}).get("message","unknown error")))
    data=result.get("data",{}); status=data.get("status","UNKNOWN")
    detail=data.get("fail_reason") or data.get("publicaly_available_post_id") or ""
    now=datetime.now(timezone.utc).isoformat()
    with db() as conn:
        conn.execute("UPDATE tiktok_posts SET status=?,status_detail=?,updated_at=? WHERE publish_id=?",
            (status,str(detail),now,row["publish_id"]))
        if status=="PUBLISH_COMPLETE":
            conn.execute("UPDATE content_calendar SET status='Published' WHERE id=?",(calendar_id,))
    _record_publish_event(calendar_id, "tiktok", status, row["publish_id"], str(detail or "TikTok processing status updated"))
    return {"calendar_id":calendar_id,"publish_id":row["publish_id"],"status":status,
        "detail":detail,"published":status=="PUBLISH_COMPLETE"}


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
               SUM(CASE WHEN follow_up_at<>'' AND follow_up_at<? AND review_status<>'resolved' THEN 1 ELSE 0 END) AS overdue,
               SUM(CASE WHEN follow_up_at=? AND review_status<>'resolved' THEN 1 ELSE 0 END) AS due_today,
               SUM(CASE WHEN follow_up_at>? AND review_status<>'resolved' THEN 1 ELSE 0 END) AS upcoming,
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
