"""Owner-controlled feature grants and fail-closed route authorization."""
from __future__ import annotations

FEATURES = (
    {"key": "dashboard", "name": "Dashboard", "description": "Studio overview and status"},
    {"key": "projects", "name": "Projects", "description": "Project files, versions and project memory"},
    {"key": "ai_assistant", "name": "AI Assistant", "description": "Chat, tasks and text generation"},
    {"key": "production", "name": "AI Production", "description": "Production runs, plans and approvals"},
    {"key": "video_editor", "name": "Video Editor", "description": "Rendering, Blender, audio, images and subtitles"},
    {"key": "media_library", "name": "Media Library", "description": "Uploaded media, assets and render queue"},
    {"key": "agents", "name": "Agent Management", "description": "Agent catalog and specialist workflows"},
    {"key": "youtube", "name": "YouTube Studio", "description": "YouTube connection, analytics, reviews and uploads"},
    {"key": "social_publish", "name": "Social & Publishing", "description": "Calendar, Meta, TikTok and publishing scheduler"},
    {"key": "integrations", "name": "Integrations", "description": "Connected platform status"},
    {"key": "ai_settings", "name": "AI Provider Settings", "description": "Select configured AI providers"},
    {"key": "earnings", "name": "Earning System", "description": "Income and expense ledger"},
)
FEATURE_KEYS = frozenset(item["key"] for item in FEATURES)

_ROUTE_FEATURES = (
    ("/api/admin/provider-settings", "ai_settings"),
    ("/api/admin/integrations", "integrations"),
    ("/api/admin/agent-catalog", "agents"),
    ("/api/admin/agent-system", "agents"),
    ("/api/admin/youtube", "youtube"),
    ("/api/admin/meta", "social_publish"),
    ("/api/admin/tiktok", "social_publish"),
    ("/api/admin/publishing", "social_publish"),
    ("/api/admin/scheduler", "social_publish"),
    ("/api/studio/production-plan", "production"),
    ("/api/studio/assets", "media_library"),
    ("/api/studio/render-queue", "media_library"),
    ("/api/studio/memory", "projects"),
    ("/api/studio/versions", "projects"),
    ("/api/studio/blender", "video_editor"),
    ("/api/studio/agents", "agents"),
    ("/api/studio/summary", "dashboard"),
    ("/api/studio/runs", "production"),
    ("/api/offline-media", "media_library"),
    ("/api/blender-renders", "video_editor"),
    ("/api/production-catalog", "production"),
    ("/api/production", "production"),
    ("/api/projects", "projects"),
    ("/api/conversations", "ai_assistant"),
    ("/api/capabilities", "dashboard"),
    ("/api/providers", "ai_assistant"),
    ("/api/workflows", "dashboard"),
    ("/api/calendar", "social_publish"),
    ("/api/agents", "agents"),
    ("/api/export", "ai_assistant"),
    ("/api/generate", "ai_assistant"),
    ("/api/tasks", "ai_assistant"),
    ("/api/rendering", "video_editor"),
    ("/api/render", "video_editor"),
    ("/api/music", "video_editor"),
    ("/api/ai-videos", "video_editor"),
    ("/api/videos", "video_editor"),
    ("/api/video", "video_editor"),
    ("/api/images", "video_editor"),
    ("/api/voice", "video_editor"),
    ("/api/audio", "video_editor"),
    ("/api/subtitles", "video_editor"),
    ("/api/flow", "video_editor"),
    ("/api/status", "dashboard"),
    ("/api/studio", "production"),
    ("/earnings", "earnings"),
)


def ensure_schema(conn) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(admin_users)").fetchall()}
    if "is_owner" not in columns:
        conn.execute("ALTER TABLE admin_users ADD COLUMN is_owner INTEGER NOT NULL DEFAULT 0")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_feature_permissions (
            user_id INTEGER NOT NULL,
            feature_key TEXT NOT NULL,
            granted_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(user_id, feature_key),
            FOREIGN KEY(user_id) REFERENCES admin_users(id) ON DELETE CASCADE
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_user_feature_permissions_user ON user_feature_permissions(user_id)")


def feature_for_path(path: str) -> str | None:
    if path == "/":
        return "dashboard"
    for prefix, feature in _ROUTE_FEATURES:
        if path == prefix or path.startswith(prefix + "/"):
            return feature
    return None


def list_user_features(conn, user_id: int) -> list[str]:
    rows = conn.execute(
        "SELECT feature_key FROM user_feature_permissions WHERE user_id=? ORDER BY feature_key",
        (user_id,),
    ).fetchall()
    return [row["feature_key"] for row in rows if row["feature_key"] in FEATURE_KEYS]


def has_feature_access(conn, user_id: int, feature_key: str) -> bool:
    if feature_key not in FEATURE_KEYS:
        return False
    return conn.execute(
        "SELECT 1 FROM user_feature_permissions WHERE user_id=? AND feature_key=?",
        (user_id, feature_key),
    ).fetchone() is not None
