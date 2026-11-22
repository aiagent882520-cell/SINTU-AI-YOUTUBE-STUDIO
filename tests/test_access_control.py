from __future__ import annotations

import sqlite3

from app import access_control


def _connection():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
    """)
    return conn


def test_schema_migrates_existing_admin_users_and_creates_permission_store():
    conn = _connection()
    access_control.ensure_schema(conn)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(admin_users)")}
    assert "is_owner" in columns
    assert conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='user_feature_permissions'"
    ).fetchone()


def test_feature_route_registry_maps_known_paths_and_fails_closed():
    assert access_control.feature_for_path("/") == "dashboard"
    assert access_control.feature_for_path("/api/admin/youtube/status") == "youtube"
    assert access_control.feature_for_path("/api/admin/provider-settings") == "ai_settings"
    assert access_control.feature_for_path("/api/production/runs") == "production"
    assert access_control.feature_for_path("/api/offline-media") == "media_library"
    assert access_control.feature_for_path("/api/earnings/records") == "earnings"
    assert access_control.feature_for_path("/api/not-yet-classified") is None
    assert access_control.feature_for_path("/api/admin/users") is None


def test_feature_grants_are_explicit_and_revocable():
    conn = _connection()
    access_control.ensure_schema(conn)
    user_id = conn.execute(
        "INSERT INTO admin_users(username,password_hash,role,created_at) VALUES(?,?,?,?)",
        ("team", "hash", "admin", "now"),
    ).lastrowid
    assert access_control.list_user_features(conn, user_id) == []
    assert not access_control.has_feature_access(conn, user_id, "youtube")
    conn.execute(
        "INSERT INTO user_feature_permissions(user_id,feature_key,granted_by,created_at) VALUES(?,?,?,?)",
        (user_id, "youtube", "owner", "now"),
    )
    assert access_control.has_feature_access(conn, user_id, "youtube")
    assert access_control.list_user_features(conn, user_id) == ["youtube"]
    conn.execute("DELETE FROM user_feature_permissions WHERE user_id=?", (user_id,))
    assert not access_control.has_feature_access(conn, user_id, "youtube")


def test_every_registered_route_is_classified_or_explicitly_owner_public():
    from app import main

    public = {
        "/", "/login", "/sw.js", "/api/auth/login", "/api/auth/logout",
        "/api/auth/session", "/api/access/features", "/api/health",
    }
    owner_prefixes = (
        "/api/admin/users", "/api/admin/audit", "/api/admin/backups",
        "/api/admin/principal-ai", "/api/admin/features",
    )
    for route in main.app.routes:
        path = getattr(route, "path", "")
        if not path:
            continue
        if path in public or path == "/static" or path.startswith("/static/") or path.startswith("/api/termux-bridge/"):
            continue
        if any(path == prefix or path.startswith(prefix + "/") for prefix in owner_prefixes):
            continue
        assert access_control.feature_for_path(path), f"Unclassified route must fail closed: {path}"
