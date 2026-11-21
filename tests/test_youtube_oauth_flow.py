import json
import time
import urllib.parse

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app import main


def configure_youtube_test(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "sintu-test.sqlite3")
    monkeypatch.setenv("SINTU_AUTH_REQUIRED", "false")
    monkeypatch.setenv("YOUTUBE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("YOUTUBE_REDIRECT_URI", "https://studio.example.test/api/admin/youtube/oauth/callback")
    monkeypatch.setenv("YOUTUBE_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    main.init_db()


def test_youtube_oauth_state_channel_verification_and_encrypted_storage(tmp_path, monkeypatch):
    configure_youtube_test(tmp_path, monkeypatch)
    calls = []

    def fake_google_request(url, data=None, headers=None, method=None):
        calls.append((url, data, headers))
        if url == "https://oauth2.googleapis.com/token":
            return 200, {}, json.dumps({
                "access_token": "test-access-secret",
                "refresh_token": "test-refresh-secret",
                "expires_in": 3600,
                "token_type": "Bearer",
            }).encode("utf-8")
        assert url == "https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true"
        assert headers["Authorization"] == "Bearer test-access-secret"
        return 200, {}, json.dumps({
            "items": [{"id": "channel-123", "snippet": {"title": "Verified test channel"}}]
        }).encode("utf-8")

    monkeypatch.setattr(main, "_youtube_request", fake_google_request)
    client = TestClient(main.app, follow_redirects=False)

    started = client.post("/api/admin/youtube/oauth/start")
    assert started.status_code == 200
    authorization = urllib.parse.urlsplit(started.json()["authorization_url"])
    query = urllib.parse.parse_qs(authorization.query)
    assert authorization.netloc == "accounts.google.com"
    assert query["client_id"] == ["test-client-id"]
    assert query["redirect_uri"] == [main._youtube_config()["redirect_uri"]]
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert query["state"] and len(query["state"][0]) >= 32
    state = query["state"][0]

    callback = client.get(
        "/api/admin/youtube/oauth/callback",
        params={"code": "one-time-auth-code", "state": state},
    )
    assert callback.status_code == 303
    assert callback.headers["location"] == "/?youtube_oauth=connected"
    assert len(calls) == 2
    assert urllib.parse.parse_qs(calls[0][1].decode())["grant_type"] == ["authorization_code"]

    connection = main._youtube_connection()
    assert connection["channel_id"] == "channel-123"
    assert connection["channel_title"] == "Verified test channel"
    with main.db() as conn:
        row = conn.execute("SELECT encrypted_tokens FROM youtube_connection WHERE id=1").fetchone()
    stored = json.loads(main._youtube_cipher().decrypt(row["encrypted_tokens"].encode()).decode())
    assert stored["access_token"] == "test-access-secret"
    assert stored["refresh_token"] == "test-refresh-secret"

    status = client.get("/api/admin/youtube/status")
    assert status.status_code == 200
    assert status.json()["connected"] is True
    assert status.json()["channel"]["id"] == "channel-123"
    assert "test-access-secret" not in status.text
    assert "test-refresh-secret" not in status.text

    replay = client.get(
        "/api/admin/youtube/oauth/callback",
        params={"code": "replayed-code", "state": state},
    )
    assert replay.status_code == 400


def test_youtube_access_token_refresh_preserves_refresh_token(tmp_path, monkeypatch):
    configure_youtube_test(tmp_path, monkeypatch)
    cipher = main._youtube_cipher()
    encrypted = cipher.encrypt(json.dumps({
        "access_token": "expired-access",
        "refresh_token": "long-lived-refresh",
        "token_type": "Bearer",
    }).encode()).decode()
    with main.db() as conn:
        conn.execute(
            """INSERT INTO youtube_connection(
                id,channel_id,channel_title,encrypted_tokens,token_expiry,connected_at
            ) VALUES(1,?,?,?,?,?)""",
            ("channel-456", "Refresh test channel", encrypted, int(time.time()) - 10, "now"),
        )

    requests = []

    def fake_google_request(url, data=None, headers=None, method=None):
        requests.append((url, urllib.parse.parse_qs(data.decode()), headers))
        assert url == "https://oauth2.googleapis.com/token"
        return 200, {}, json.dumps({
            "access_token": "fresh-access-token",
            "expires_in": 3600,
            "token_type": "Bearer",
        }).encode("utf-8")

    monkeypatch.setattr(main, "_youtube_request", fake_google_request)
    assert main._youtube_access_token() == "fresh-access-token"
    assert len(requests) == 1
    assert requests[0][1]["refresh_token"] == ["long-lived-refresh"]
    with main.db() as conn:
        row = conn.execute("SELECT encrypted_tokens,token_expiry FROM youtube_connection WHERE id=1").fetchone()
    refreshed = json.loads(cipher.decrypt(row["encrypted_tokens"].encode()).decode())
    assert refreshed["access_token"] == "fresh-access-token"
    assert refreshed["refresh_token"] == "long-lived-refresh"
    assert row["token_expiry"] > int(time.time())



def test_youtube_oauth_state_is_bound_to_the_starting_browser_session(tmp_path, monkeypatch):
    configure_youtube_test(tmp_path, monkeypatch)
    client = TestClient(main.app, follow_redirects=False)
    started = client.post("/api/admin/youtube/oauth/start")
    assert started.status_code == 200
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(started.json()["authorization_url"]).query)
    state = query["state"][0]

    other_browser = TestClient(main.app, follow_redirects=False)
    other_browser.cookies.set(main.SESSION_COOKIE, "different-browser-session")
    rejected = other_browser.get(
        "/api/admin/youtube/oauth/callback",
        params={"code": "must-not-be-exchanged", "state": state},
    )
    assert rejected.status_code == 400


def test_youtube_refresh_is_serialized_across_concurrent_callers(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Lock

    configure_youtube_test(tmp_path, monkeypatch)
    cipher = main._youtube_cipher()
    encrypted = cipher.encrypt(json.dumps({
        "access_token": "expired-access",
        "refresh_token": "long-lived-refresh",
        "token_type": "Bearer",
    }).encode()).decode()
    with main.db() as conn:
        conn.execute(
            """INSERT INTO youtube_connection(
                id,channel_id,channel_title,encrypted_tokens,token_expiry,connected_at
            ) VALUES(1,?,?,?,?,?)""",
            ("channel-concurrent", "Concurrent refresh", encrypted, int(time.time()) - 10, "now"),
        )

    calls = []
    calls_lock = Lock()

    def fake_google_request(url, data=None, headers=None, method=None):
        with calls_lock:
            calls.append(urllib.parse.parse_qs(data.decode())["refresh_token"][0])
        time.sleep(0.15)
        return 200, {}, json.dumps({
            "access_token": "rotated-access",
            "refresh_token": "rotated-refresh",
            "expires_in": 3600,
            "token_type": "Bearer",
        }).encode()

    monkeypatch.setattr(main, "_youtube_request", fake_google_request)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: main._youtube_access_token(), range(8)))

    assert results == ["rotated-access"] * 8
    assert calls == ["long-lived-refresh"]
    with main.db() as conn:
        row = conn.execute("SELECT encrypted_tokens,token_expiry FROM youtube_connection WHERE id=1").fetchone()
        lock = conn.execute("SELECT owner FROM youtube_token_refresh_lock WHERE id=1").fetchone()
    stored = json.loads(cipher.decrypt(row["encrypted_tokens"].encode()).decode())
    assert stored["access_token"] == "rotated-access"
    assert stored["refresh_token"] == "rotated-refresh"
    assert row["token_expiry"] > int(time.time())
    assert lock is None


def test_youtube_forced_refresh_coalesces_after_another_caller_rotates_token(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Lock

    configure_youtube_test(tmp_path, monkeypatch)
    cipher = main._youtube_cipher()
    encrypted = cipher.encrypt(json.dumps({
        "access_token": "rejected-access",
        "refresh_token": "stable-refresh",
        "token_type": "Bearer",
    }).encode()).decode()
    with main.db() as conn:
        conn.execute(
            """INSERT INTO youtube_connection(
                id,channel_id,channel_title,encrypted_tokens,token_expiry,connected_at
            ) VALUES(1,?,?,?,?,?)""",
            ("channel-forced", "Forced refresh", encrypted, int(time.time()) + 3600, "now"),
        )

    calls = []
    calls_lock = Lock()

    def fake_google_request(url, data=None, headers=None, method=None):
        with calls_lock:
            calls.append(1)
        time.sleep(0.15)
        return 200, {}, json.dumps({
            "access_token": "replacement-access",
            "expires_in": 3600,
            "token_type": "Bearer",
        }).encode()

    monkeypatch.setattr(main, "_youtube_request", fake_google_request)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(
            lambda _: main._youtube_access_token(
                force_refresh=True, stale_access_token="rejected-access"
            ),
            range(8),
        ))

    assert results == ["replacement-access"] * 8
    assert len(calls) == 1


def test_youtube_oauth_invalid_grant_is_sanitized(tmp_path, monkeypatch):
    import io
    from fastapi import HTTPException

    configure_youtube_test(tmp_path, monkeypatch)

    def rejected_request(request, timeout):
        raise main.urllib.error.HTTPError(
            request.full_url, 400, "Bad Request", {},
            io.BytesIO(b'{"error":"invalid_grant","error_description":"sensitive refresh token detail"}'),
        )

    monkeypatch.setattr(main.urllib.request, "urlopen", rejected_request)
    try:
        main._youtube_request(
            "https://oauth2.googleapis.com/token",
            data=b"grant_type=refresh_token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    except HTTPException as exc:
        assert exc.status_code == 401
        assert "sensitive refresh token detail" not in exc.detail
    else:
        raise AssertionError("invalid_grant must require channel reconnection")
